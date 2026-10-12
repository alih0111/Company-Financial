package qvt

// کنترل مستقل و فقط‌خواندنی تازگی قیمت (گام ۲-ط-۱).
//
// درس گام ۲-ح-۱: بازخوانی عدد از متن هشدار stale_price به‌تنهایی اثبات
// مستقل نیست — همان متن را که موتور نوشته دوباره می‌خواند. قاعده B1 اصلاح
// شد: «آخرین قیمت معتبر» باید از منبع واقعی ثبت‌شده کنترل شود.
//
// منبع: جدول market.price_observations در canonical postgres — همان جدولی
// که خود موتور قیمت‌ها را از آن بارگذاری می‌کند (compute_metrics.py). جلسه
// با default_transaction_read_only=on باز می‌شود؛ هیچ نوشتنی وجود ندارد و
// هیچ جدولی تغییر نمی‌کند.
//
// قرارداد خواندن (عیناً قرارداد PIT موتور، نه اختراع جدید):
//   - security فعال شرکت: is_primary، سپس بیشترین ردیف قیمت، سپس id
//     (compute_metrics.build_subjects)
//   - آخرین ردیف قیمت آن security در پنجره PIT آرتیفکت:
//     collected_at <= cutoff آرتیفکت، مرتب‌شده trade_date DESC سپس
//     collected_at DESC (حالت canonical market_pit="collected_at")
//   - سن قیمت = (as_of آرتیفکت − trade_date) روز تقویمی
//     (pilot_v2_value.py: price_age_days = (as_of - ptd).days)
//   - سیاست تازگی از خود آرتیفکت V خوانده می‌شود:
//     construction.freshness_policy.price_stale_days (ثابت اعلام‌شده
//     PRICE_STALE_DAYS در score_v2_value_raw.py) — اینجا عددی هاردکد
//     نمی‌شود و سیاست تغییر داده نمی‌شود
//
// تخریب محترمانه: اگر DSN تنظیم نباشد، پینگ/کوئری خطا دهد یا برای شرکتی
// ردیف قیمتی یافت نشود، کنترل «ممکن نشد» اعلام می‌شود — هشدار مشکوک می‌ماند
// و هرگز ادعای «مانع اثبات‌شده» صادر نمی‌شود. خطای endpoint هرگز از این
// مسیر نمی‌آید.

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"sync"
	"time"

	"go-app/integration"

	"github.com/gin-gonic/gin"
)

const (
	priceCheckSource = "market.price_observations (canonical postgres — جلسه فقط‌خواندنی)"
	priceCheckWindow = "آخرین ردیف هر security با collected_at ≤ cutoff آرتیفکت، مرتب‌شده trade_date DESC سپس collected_at DESC — همان قرارداد PIT موتور (market_pit=collected_at)"
	priceCheckBasis  = "روز تقویمی: سن = (as_of آرتیفکت) − (trade_date آخرین ردیف)"
)

var errPriceNoDSN = errors.New("canonical DSN تنظیم نشده — کنترل مستقل قیمت در این محیط ممکن نیست")

var (
	pxMu sync.Mutex
	pxDB *sql.DB
)

// qvtPriceDB استخر فقط‌خواندنی canonical را تنبل باز می‌کند. خطا کش
// نمی‌شود تا یک خطای گذرا در فراخوانی بعدی دوباره تلاش کند؛ اتصال موفق کش
// می‌شود.
func qvtPriceDB() (*sql.DB, error) {
	pxMu.Lock()
	defer pxMu.Unlock()
	if pxDB != nil {
		return pxDB, nil
	}
	cfg := integration.LoadConfig()
	if cfg.CanonicalDSN == "" {
		return nil, errPriceNoDSN
	}
	pg, err := integration.OpenPG(cfg)
	if err != nil {
		return nil, err
	}
	if pg == nil {
		return nil, errPriceNoDSN
	}
	pxDB = pg.DB()
	return pxDB, nil
}

// priceCheck نتیجه کنترل مستقل تازگی قیمت یک شرکت. هر وضعیتِ ممکنِ منبع
// صریح است: در دسترس نبودن منبع، نبود ردیف قیمت، یا ردیف یافت‌شده با سن
// محاسبه‌شده.
type priceCheck struct {
	Requested     bool   `json:"requested"`
	Available     bool   `json:"available"` // منبع پاسخ داد
	RowFound      bool   `json:"row_found"` // ردیف قیمت در پنجره PIT یافت شد
	Note          string `json:"note"`
	Source        string `json:"source,omitempty"`
	CompanyID     string `json:"company_id,omitempty"`
	SecurityID    string `json:"security_id,omitempty"`
	LastTradeDate string `json:"last_trade_date,omitempty"`
	CollectedAt   string `json:"collected_at,omitempty"`
	AsOfDate      string `json:"as_of_date,omitempty"`
	AgeDays       *int   `json:"age_days,omitempty"`
	PolicyDays    *int   `json:"policy_days,omitempty"`
	PolicyBasis   string `json:"policy_basis,omitempty"`
	WindowRule    string `json:"window_rule,omitempty"`
	Violation     *bool  `json:"violation,omitempty"` // فقط وقتی سن و سیاست هر دو موجودند
}

// bundlePricePolicy سیاست تازگی قیمت را از خود آرتیفکت V می‌خواند —
// construction.freshness_policy.price_stale_days. نبودش یعنی B1 قابل اثبات
// نیست (خط‌مشی ثبت‌شده‌ای برای سنجش وجود ندارد).
func bundlePricePolicy(b *qvtBundle) *int {
	c, ok := b.V["construction"].(map[string]any)
	if !ok {
		return nil
	}
	fp, ok := c["freshness_policy"].(map[string]any)
	if !ok {
		return nil
	}
	f, ok := fp["price_stale_days"].(float64)
	if !ok || f <= 0 {
		return nil
	}
	n := int(f)
	return &n
}

// priceUnavailable یک نتیجه «کنترل ممکن نشد» می‌سازد.
func priceUnavailable(cid, note string, policy *int, asOf string) *priceCheck {
	return &priceCheck{
		Requested: true, Available: false, RowFound: false,
		Note: note, Source: priceCheckSource,
		CompanyID: cid, PolicyDays: policy, AsOfDate: asOf,
		PolicyBasis: priceCheckBasis, WindowRule: priceCheckWindow,
	}
}

// priceChecksFor برای مجموعه شرکت‌ها، آخرین ردیف قیمت را در یک کوئری از
// منبع مستقل می‌خواند و سن تقویمی آن را نسبت به as_of و سیاست آرتیفکت
// محاسبه می‌کند. اگر منبع در دسترس نباشد برای همه شرکت‌ها نتیجه «ممکن
// نشد» برمی‌گردد و هیچ خطایی به endpoint نمی‌رسد.
func priceChecksFor(cids []string, cutoffRaw, asOfDate string, policy *int) (map[string]*priceCheck, bool, string) {
	out := make(map[string]*priceCheck, len(cids))
	for _, cid := range cids {
		out[cid] = priceUnavailable(cid, "کنترل آغاز نشده", policy, asOfDate)
	}
	if len(cids) == 0 {
		return out, true, ""
	}
	db, err := qvtPriceDB()
	if err != nil {
		note := "کنترل مستقل تازگی قیمت ممکن نشد: " + err.Error()
		for _, cid := range cids {
			out[cid] = priceUnavailable(cid, note, policy, asOfDate)
		}
		return out, false, note
	}

	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	var cutoff any
	if t, err := qvtParseInstant(cutoffRaw); err == nil {
		cutoff = t
	} else {
		cutoff = cutoffRaw
	}
	rows, err := db.QueryContext(ctx, `
WITH sec AS (
    SELECT DISTINCT ON (s.company_id::text)
        s.company_id::text AS company_id,
        s.id::text         AS security_id
    FROM core.securities s
    WHERE s.company_id::text = ANY($1) AND s.is_active
    ORDER BY s.company_id::text, s.is_primary DESC,
             (SELECT count(*) FROM market.price_observations p0 WHERE p0.security_id = s.id) DESC,
             s.id::text DESC
)
SELECT sec.company_id, sec.security_id, px.trade_date::date AS trade_date, px.collected_at
FROM sec
LEFT JOIN LATERAL (
    SELECT po.trade_date, po.collected_at
    FROM market.price_observations po
    WHERE po.security_id = sec.security_id::uuid AND po.collected_at <= $2
    ORDER BY po.trade_date DESC, po.collected_at DESC
    LIMIT 1
) px ON true`, cids, cutoff)
	if err != nil {
		note := "کنترل مستقل تازگی قیمت ممکن نشد (کوئری منبع): " + err.Error()
		for _, cid := range cids {
			out[cid] = priceUnavailable(cid, note, policy, asOfDate)
		}
		return out, false, note
	}
	defer rows.Close()

	asOf, err := time.Parse("2006-01-02", asOfDate)
	if err != nil {
		note := "as_of آرتیفکت قابل تفسیر نیست: " + asOfDate
		for _, cid := range cids {
			out[cid] = priceUnavailable(cid, note, policy, asOfDate)
		}
		return out, false, note
	}
	for rows.Next() {
		var cid, sid string
		var td, ca sql.NullString
		if err := rows.Scan(&cid, &sid, &td, &ca); err != nil {
			continue
		}
		// pgx ممکن است date را به‌صورت timestamp متن دهد («2026-10-05T00:00:00Z»)
		// — معنای قراردادی موتور، تاریخ تقویمی است
		tdNorm := td.String
		if len(tdNorm) >= 10 {
			tdNorm = tdNorm[:10]
		}
		pc := &priceCheck{
			Requested: true, Available: true, RowFound: false,
			Note: "هیچ ردیف قیمتی در پنجره PIT آرتیفکت برای این security یافت نشد",
			Source: priceCheckSource, CompanyID: cid, SecurityID: sid,
			AsOfDate: asOfDate, PolicyDays: policy,
			PolicyBasis: priceCheckBasis, WindowRule: priceCheckWindow,
		}
		if td.Valid {
			pc.RowFound = true
			pc.LastTradeDate = tdNorm
			pc.CollectedAt = ca.String
			if tdp, err := time.Parse("2006-01-02", tdNorm); err == nil {
				age := int(asOf.Sub(tdp).Hours() / 24)
				pc.AgeDays = &age
				if policy != nil {
					v := age > *policy
					pc.Violation = &v
					if v {
						pc.Note = fmt.Sprintf("آخرین قیمت %d روز تقویمی قبل از as_of است — بیش از سیاست %d روز (نقض سیاست اثبات شد)", age, *policy)
					} else {
						pc.Note = fmt.Sprintf("آخرین قیمت %d روز تقویمی قبل از as_of است — در محدوده سیاست %d روز", age, *policy)
					}
				} else {
					pc.Note = fmt.Sprintf("آخرین قیمت %d روز تقویمی قبل از as_of است؛ سیاست تازگی در آرتیفکت ثبت نشده — سنجش نقض ممکن نیست", age)
				}
			}
		}
		out[cid] = pc
	}
	return out, true, ""
}

// priceSourceMeta قرارداد منبع قیمت را برای UI منتشر می‌کند.
func priceSourceMeta(available bool, note string) gin.H {
	m := gin.H{
		"source":             priceCheckSource,
		"window_rule":        priceCheckWindow,
		"policy_basis":       priceCheckBasis,
		"policy_source":      "آرتیفکت V: construction.freshness_policy.price_stale_days — ثابت اعلام‌شده PRICE_STALE_DAYS در score_v2_value_raw.py؛ این سرویس سیاست را تغییر نمی‌دهد",
		"security_selection": "security فعال شرکت با is_primary و بیشترین ردیف قیمت — مطابق compute_metrics.build_subjects",
		"read_only":          "اتصال با default_transaction_read_only=on باز می‌شود؛ فقط SELECT و بدون هیچ نوشتنی",
		"independent_of_warning_text": "بازخوانی عدد از متن هشدار اثبات مستقل نیست؛ تنها نتیجه این کنترل می‌تواند B1 را اثبات کند",
		"available": available,
	}
	if note != "" {
		m["note"] = note
	}
	return m
}
