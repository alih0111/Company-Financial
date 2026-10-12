package qvt

// اعتبارسنجی زنجیره داده نامزدهای QVT (گام ۲-ی-۱) — فقط‌خواندنی.
//
// هدف: برای هر شرکت (به‌ویژه نامزدهای فهرست کوتاه) مشخص کند ورودی‌های مالی
// (Q)، ارزندگی (V) و بازار (T) از کدام ردیف‌های واقعی دیتابیس می‌آیند، با
// کدام تاریخ‌ها (تاریخ داده / گردآوری / انتشار / مؤثر) و آیا شواهد با خود
// آرتیفکت هم‌خوان است یا تعارض دارد.
//
// قرارداد وضعیت شواهد (چهار حالت، بدون حالت پنجم):
//   verified_from_source — مقدار/منبع/تاریخ‌ها از منبع واقعی خوانده و با
//                          قرارداد محاسبه موتور تطبیق داده شد
//   partially_verified   — بخشی از زنجیره اثبات شد ولی محدودیت مشخصی باقی است
//                          (مثلاً published_at غایب است و دیده‌شدن با
//                          period_end جایگزین شده)
//   unverified           — شواهد لازم موجود نیست یا کنترل ممکن نشد؛ «نبود
//                          داده» و «خطای کنترل» با فیلد checked جدا می‌شوند
//   conflicting          — شواهد واقعی با محاسبه یا متادیتای آرتیفکت تعارض دارند
//
// مرزهای سخت:
//   - صرف وجود داده در دیتابیس یا JSON هرگز «تأیید صحت اقتصادی» نیست؛ فقط
//     ردیابی ورودی است
//   - تاریخ انتشار واقعی، تاریخ مؤثر سهام و PIT حدس زده نمی‌شود؛ هر چه در
//     منبع نیست «موجود نیست» اعلام می‌شود
//   - هیچ امتیاز Q/V/T، لایه پارتو، درصد اطمینان یا پیشنهاد خریدی ساخته
//     نمی‌شود — خروجی این فایل صرفاً توصیف شواهد است
//   - ثابت‌های موتور (STALE_DAYS، JUMP_BAND، پنجره‌ها) عیناً از
//     score_v2_t_raw.py / score_v2_value_raw.py نقل می‌شوند؛ هیچ سیاستی
//     تغییر یا اختراع نمی‌شود
//
// منبع DB همان جلسه فقط‌خواندنی pricecheck.go است
// (default_transaction_read_only=on)؛ جداول خوانده‌شده عیناً همان‌هایی هستند
// که موتور در compute_metrics.py می‌خواند: fundamentals.financial_facts +
// financial_statements + ingestion.report_versions + ingestion.reports برای
// Q و بنیادی V؛ market.tsetmc_current_shares و core.share_structure برای
// سهام؛ market.price_observations برای تاریخچه T؛ market.corporate_actions و
// core.share_events فقط به‌عنوان شواهد اقدامات شرکتی (موتور V/T از آنها
// استفاده نمی‌کند — این موضوع صریحاً در خروجی اعلام می‌شود).

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// ─────────────────────────────────────────────────────────────────────────────
// قرارداد وضعیت و انواع
// ─────────────────────────────────────────────────────────────────────────────

const (
	evVerified    = "verified_from_source"
	evPartial     = "partially_verified"
	evUnverified  = "unverified"
	evConflicting = "conflicting"
)

// evSeverity برای جمع‌بندی وضعیت محور: تعارض بدترین حالت است، سپس نبود
// شواهد، سپس تأیید نیمه‌کاره، و verified بهترین.
var evSeverity = map[string]int{
	evVerified: 0, evPartial: 1, evUnverified: 2, evConflicting: 3,
}

var evStatusLabels = map[string]string{
	evVerified:    "تأییدشده از منبع",
	evPartial:     "نیمه‌تأییدشده — محدودیت مشخص",
	evUnverified:  "بدون شواهد کافی (≠ داده نامعتبر)",
	evConflicting: "تعارض شواهد با محاسبه/متادیتا",
}

// evWorst وضعیت بدبینانه یک مجموعه آیتم را برمی‌گرداند.
func evWorst(statuses []string) string {
	worst := evVerified
	for _, s := range statuses {
		if evSeverity[s] > evSeverity[worst] {
			worst = s
		}
	}
	return worst
}

type evidenceField struct {
	K string `json:"k"`
	V string `json:"v"`
}

type evidenceItem struct {
	Key         string `json:"key"`
	Label       string `json:"label"`
	Status      string `json:"status"`
	StatusLabel string `json:"status_label"`
	Checked     bool   `json:"checked"` // false = منبع در دسترس نبود/کنترل اجرا نشد — جدا از «داده نبود»
	// Structural یافته ساختاری درباره خود آرتیفکت است (نه ورودی این شرکت)
	// و در جمع‌بندی وضعیت محور لحاظ نمی‌شود.
	Structural  bool            `json:"structural,omitempty"`
	Source      string          `json:"source,omitempty"`
	Summary     string          `json:"summary,omitempty"`
	Fields      []evidenceField `json:"fields,omitempty"`
	Limitations []string        `json:"limitations,omitempty"`
	Conflicts   []string        `json:"conflicts,omitempty"`
}

func evItem(key, label, status string) *evidenceItem {
	return &evidenceItem{Key: key, Label: label, Status: status, StatusLabel: evStatusLabels[status], Checked: true}
}

type axisEvidence struct {
	Axis        string         `json:"axis"`
	AxisLabel   string         `json:"axis_label"`
	Status      string         `json:"status"`
	StatusLabel string         `json:"status_label"`
	Items       []evidenceItem `json:"items"`
}

type evidenceChain struct {
	CompanyID    string         `json:"company_id"`
	Overall      string         `json:"overall"`
	OverallLabel string         `json:"overall_label"`
	StatusCounts map[string]int `json:"status_counts"`
	Axes         []axisEvidence `json:"axes"`
	Notes        []string       `json:"notes"`
}

// ─────────────────────────────────────────────────────────────────────────────
// ثابت‌های موتور — عیناً از کد تولیدکننده نقل می‌شوند، نه اختراع جدید
// ─────────────────────────────────────────────────────────────────────────────

const (
	// score_v2_t_raw.py:126-135
	tStaleDays       = 14    // STALE_DAYS
	tJumpBand        = 0.21  // JUMP_BAND — «یک‌روزه |بازده| که هیچ جلسه TSE تولید نمی‌کند»
	tLiqWindowObs    = 30    // LIQ_WINDOW_OBS
	tLiqMinObs       = 10    // LIQ_MIN_OBS
	tVolWindowCloses = 31    // VOL_WINDOW_CLOSES
	tVolMinReturns   = 10    // VOL_MIN_RETURNS
	tWindowMaxSpan   = 60    // WINDOW_MAX_SPAN_DAYS
	tPriceFloor      = 100.0 // PRICE_FLOOR (ریال)
	// score_v2_value_raw.py:118
	vBalanceSheetStaleDays = 366 // BALANCE_SHEET_STALE_DAYS — یک سال مالی
)

const (
	qSourceTables = "fundamentals.financial_facts ⨝ financial_statements ⨝ ingestion.report_versions ⨝ ingestion.reports — همان SQL موتور (compute_metrics.py:318-329)"
	qPitRule      = "دیده‌شدن: (published_at IS NULL AND period_end_date <= as_of) OR (published_at <= cutoff)؛ گزارش‌های جایگزین‌شده (supersedes_report_id) حذف می‌شوند"
)

// ─────────────────────────────────────────────────────────────────────────────
// قواعد منتشرشده برای UI
// ─────────────────────────────────────────────────────────────────────────────

var qvtEvidenceRules = gin.H{
	"status_contract": gin.H{
		"verified_from_source": "مقدار، منبع و تاریخ‌های لازم با قرارداد محاسبه موتور از منبع واقعی تطبیق داده شد",
		"partially_verified":   "بخشی از زنجیره اثبات شد ولی محدودیت مشخصی باقی است",
		"unverified":           "شواهد لازم موجود نیست یا قابل تطبیق نیست — «نبود داده» از «خطای کنترل» با فیلد checked جدا می‌شود",
		"conflicting":          "شواهد واقعی با محاسبه یا متادیتای گزارش تعارض دارند",
	},
	"not_verification_of_economics": "صرف وجود داده در دیتابیس یا JSON به معنی تأیید صحت اقتصادی نیست؛ این لایه فقط ردیابی ورودی است و هیچ امتیاز یا رتبه‌ای نمی‌سازد",
	"date_kinds": gin.H{
		"تاریخ داده":    "trade_date قیمت یا period_end_date صورت مالی — لحظه واقعی رویداد",
		"تاریخ گردآوری": "collected_at — زمان ثبت ردیف در canonical store",
		"تاریخ انتشار":  "published_at گزارش Codal — فقط اگر واقعاً در منبع باشد؛ هرگز با period_end جایگزین/حدس زده نمی‌شود",
		"تاریخ مؤثر":    "as_of_date snapshot سهام یا effective_date اقدام شرکتی — تاریخ اعتبار مقدار",
	},
	"sources": gin.H{
		"q_financials":      qSourceTables,
		"q_pit_rule":        qPitRule,
		"v_price":           "market.price_observations — همان قرارداد pricecheck.go (گام ۲-ط-۱)",
		"v_shares":          "PRIMARY: market.tsetmc_current_shares (collected_at واقعی)؛ FALLBACK: core.share_structure (as_of_date) — قرارداد compute_metrics.select_current_shares؛ هیچ شمارشی از سرمایه/اسمی استنباط نمی‌شود",
		"v_fundamentals":    "همان جداول Q — TTM سود/فروش با resolve_ttm و حقوق مالکانه سلول order-1 آخرین گزارش",
		"t_history":         "market.price_observations — همه تاریخ‌ها با collected_at ≤ cutoff و trade_date ≤ as_of، dedup آخرین collected_at برای هر trade_date؛ قیمت بسته vendor-adjusted (ادعای صریح آرتیفکت T)",
		"corporate_actions": "market.corporate_actions و core.share_events فقط به‌عنوان شواهد ثبت‌شده؛ موتور V از آنها استفاده نمی‌کند و این موضوع در خود هشدار موتور (share_snapshot_older_than_price) صریح است",
	},
	"engine_constants_quoted": gin.H{
		"t_stale_days": tStaleDays, "t_jump_band": tJumpBand,
		"t_liq_window_obs": tLiqWindowObs, "t_liq_min_obs": tLiqMinObs,
		"t_vol_window_closes": tVolWindowCloses, "t_vol_min_returns": tVolMinReturns,
		"t_window_max_span_days": tWindowMaxSpan, "t_price_floor_rial": tPriceFloor,
		"v_balance_sheet_stale_days": vBalanceSheetStaleDays,
		"note":                       "ثابت‌های اعلام‌شده score_v2_t_raw.py:126-135 و score_v2_value_raw.py:115-118 — این سرویس هیچ سیاستی را تغییر نمی‌دهد",
	},
	"no_score_change": "Data Confidence و Risk Gate و این لایه هیچ‌کدام حق تغییر امتیازها یا لایه‌های Pareto را ندارند",
}

// ─────────────────────────────────────────────────────────────────────────────
// زنجیره اثر Q→V→T روی دیسک (بدون DB)
// ─────────────────────────────────────────────────────────────────────────────

type linkCheck gin.H

func linkStatus(l linkCheck) string {
	s, _ := l["status"].(string)
	return s
}

func checkLink(b *qvtBundle, fromDoc map[string]any, fromLabel, pointerKey, wantFile string, wantAsOf string, nEligible *float64) linkCheck {
	ptr, ok := fromDoc[pointerKey].(map[string]any)
	if !ok {
		return linkCheck{"from": fromLabel, "pointer": pointerKey, "status": evUnverified,
			"note": "آرتیفکت مقصد پوینتر upstream ندارد — پیوند اجرا روی دیسک ثبت نشده"}
	}
	path, _ := ptr["path"].(string)
	asOf, _ := ptr["as_of"].(string)
	var problems []string
	if base(path) != wantFile {
		problems = append(problems, fmt.Sprintf("پوینتر به فایل %q اشاره می‌کند نه %q", base(path), wantFile))
	}
	if asOf != wantAsOf {
		problems = append(problems, fmt.Sprintf("as_of پوینتر (%q) با آرتیفکت مقصد (%q) یکی نیست", asOf, wantAsOf))
	}
	if nEligible != nil {
		if pn, ok := ptr["n_pilot_eligible"].(float64); !ok || pn != *nEligible {
			problems = append(problems, "n_pilot_eligible پوینتر با شمار آرتیفکت مقصد یکی نیست")
		}
	}
	st := evVerified
	if len(problems) > 0 {
		st = evConflicting
	}
	return linkCheck{"from": fromLabel, "pointer": pointerKey, "status": st,
		"points_to": base(path), "as_of": asOf, "problems": problems,
		"note": "پوینتر {path, as_of, n_pilot_eligible} تنها نشانه هم‌اجرایی ثبت‌شده روی دیسک است — run_id واقعی در آرتیفکت‌ها منتشر نمی‌شود"}
}

func base(p string) string {
	for i := len(p) - 1; i >= 0; i-- {
		if p[i] == '\\' || p[i] == '/' {
			return p[i+1:]
		}
	}
	return p
}

func qEligibleCount(doc map[string]any) *float64 {
	s, ok := doc["summary"].(map[string]any)
	if !ok {
		return nil
	}
	if f, ok := s["n_pilot_eligible"].(float64); ok {
		return &f
	}
	return nil
}

func vEligibleCount(doc map[string]any) *float64 {
	s, ok := doc["coverage_summary"].(map[string]any)
	if !ok {
		return nil
	}
	if f, ok := s["n_v_pilot_eligible"].(float64); ok {
		return &f
	}
	return nil
}

// bundleIntegrityOf یکپارچگی سطح snapshot: هش و اندازه فایل‌ها، پیوند
// زنجیره Q→V→T از پوینترهای upstream، و محدودیت‌های ساختاری انتشار.
func bundleIntegrityOf(b *qvtBundle) gin.H {
	qAsOf := qvtStr(b.Q, "as_of")
	vAsOf := qvtStr(b.V, "as_of")

	lqv := checkLink(b, b.V, "v2_value_pilot.json", "q_axis_artifact", "v2_q_observed_report.json", qAsOf, qEligibleCount(b.Q))
	lqt := checkLink(b, b.T, "v2_t_pilot.json", "q_axis_artifact", "v2_q_observed_report.json", qAsOf, qEligibleCount(b.Q))
	lvt := checkLink(b, b.T, "v2_t_pilot.json", "v_axis_artifact", "v2_value_pilot.json", vAsOf, vEligibleCount(b.V))

	links := []linkCheck{lqv, lqt, lvt}
	statuses := make([]string, 0, len(links))
	for _, l := range links {
		statuses = append(statuses, linkStatus(l))
	}

	files := gin.H{}
	for _, f := range []struct {
		key, name, sha string
		size           int64
		mod            time.Time
	}{{"q", "v2_q_observed_report.json", b.qSHA, b.qSize, b.qMod},
		{"v", "v2_value_pilot.json", b.vSHA, b.vSize, b.vMod},
		{"t", "v2_t_pilot.json", b.tSHA, b.tSize, b.tMod}} {
		files[f.key] = gin.H{"file": f.name, "sha256": f.sha, "size_bytes": f.size,
			"modified_at": f.mod.Format(time.RFC3339)}
	}

	out := gin.H{
		"artifact_files": files,
		"chain_linkage": gin.H{
			"q_to_v": lqv, "q_to_t": lqt, "v_to_t": lvt,
			"status": evWorst(statuses), "status_label": evStatusLabels[evWorst(statuses)],
			"note": "خوانش مجدد پوینترهای upstream که هر اجرا در آرتیفکت بعدی ثبت می‌کند — تنها نشانه هم‌اجرایی روی دیسک؛ run_id/generated_at/code_version در هیچ آرتیفکتی منتشر نمی‌شود",
		},
		"run_identity": gin.H{
			"status":     "not_published",
			"limitation": "هیچ‌کدام از سه آرتیفکت run_id یا generated_at یا code_version منتشر نمی‌کنند و فایل manifest مشترکی وجود ندارد؛ هم‌اجرایی سه فایل فقط از هم‌خوانی as_of/cutoff و پوینترهای upstream استنتاج می‌شود. این محدودیت صریح است و با هیچ داده‌ای پر نمی‌شود.",
			"fix_plan":   "پیاده‌سازی شد (opt-in): publisher مستقل analytics_canonical_v1/publish_bundle.py سه فایل کامل را اعتبارسنجی و در پوشه نسخه‌دار immutable با manifest.json (sha256 سه فایل + اعتبارسنجی زنجیره) منتشر می‌کند و LATEST.json را اتمیک عوض می‌کند؛ خواننده با QVT_MANIFEST_DIR همان بسته را hash-به-hash مصرف می‌کند. تغییر خودِ نویسنده‌ها (manifest-last در تولیدکننده) همچنان به قواعد «عدم تغییر فایل‌های تولید Q/V» گره خورده و انجام نشد.",
		},
		"publication_atomicity": gin.H{
			"writer":            "هر سه فایل با Path.write_text درجا (truncate+write) نوشته می‌شوند — بدون tmp+rename، بدون fsync، بدون قفل (pilot_v2_qvt.py:2253، pilot_v2_value.py:792، pilot_v2_t.py:675)",
			"reader_mitigation": "این سرویس در پایان هر خواندن اندازه/زمان تغییر سه فایل را دوباره کنترل می‌کند؛ اگر فایلی در میانه خواندن عوض شده باشد، بارگذاری حداکثر دو بار تکرار و در نهایت با خطای صریح رد می‌شود — هیچ ترکیب نیمه‌کهنه سرو نمی‌شود",
			"residual_risk":     "پنجره بین سه rename جداگانه هنوز می‌تواند Q کهنه + V تازه بدهد؛ گیت as_of/cutoff در endpoint بیشتر حالت‌ها را رد می‌کند، اما حالت هم‌تاریخ دودویی کامل قابل تشخیص نیست — راه قطعی فعال‌سازی مصرف manifest است (QVT_MANIFEST_DIR)",
		},
		"load_verified_stable": b.loadStable,
	}
	if b.manifest != nil {
		out["publication"] = gin.H{
			"mode":             "manifest_bundle",
			"run_id":           b.manifest.RunID,
			"published_at":     b.manifest.PublishedAt,
			"manifest_sha256":  b.manifest.ManifestSHA256,
			"sidecars":         b.manifest.Sidecars,
			"chain_validation": b.manifest.ChainValidation,
			"note":             "خواندن از بسته نسخه‌دار opt-in (QVT_MANIFEST_DIR): هر سه فایل در برابر manifest تأیید hash شدند؛ run_id شناسه «انتشار بسته» از محتواست، نه شناسه اجرای producer؛ published_at زمان انتشار بسته است نه تاریخ تولید داده",
			"rollback":         "بازگرداندن LATEST.json به run_id قبلی (پوشه هر بسته immutable است) یا خالی کردن QVT_MANIFEST_DIR — امتیازها در هر دو حالت بایت‌به‌بایت یکسان‌اند",
		}
	} else {
		out["publication"] = gin.H{
			"mode": "direct_files",
			"note": "QVT_MANIFEST_DIR تنظیم نشده — خواندن مستقیم سه فایل با محافظ تغییرِ میانه خواندن؛ مسیر انتشار اتمیک opt-in در analytics_canonical_v1/publish_bundle.py ساخته شده و فعال نیست",
		}
	}
	return out
}

// ─────────────────────────────────────────────────────────────────────────────
// کوئری‌های فقط‌خواندنی DB
// ─────────────────────────────────────────────────────────────────────────────

type fundOriginRow struct {
	CompanyID      string
	MetricCode     string
	PeriodEnd      string // YYYY-MM-DD
	FiscalYear     sql.NullInt64
	FiscalMonth    sql.NullInt64
	PublishedAt    sql.NullString
	CollectedAt    sql.NullString
	NReports       int
	NRows          int
	CanonicalValue sql.NullFloat64
	PeriodOrder    sql.NullInt64
}

// fundOriginFor منشأ مالی هر شرکت را با عین predicate موتور برمی‌گرداند:
// برای هر metric_code آخرین سلول مجاز (max period_end_date, version_no,
// period_order) به‌همراه متادیتای گزارش آن.
func fundOriginFor(db *sql.DB, cid, asOfDate string, cutoff any) ([]fundOriginRow, bool, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `
WITH elig AS (
    SELECT st.company_id::text AS company_id, f.metric_code, f.period_order,
           f.canonical_value, st.period_end_date, st.fiscal_year, st.fiscal_month,
           rv.version_no, rv.collected_at, r.published_at, r.id::text AS report_id
    FROM fundamentals.financial_facts f
    JOIN fundamentals.financial_statements st ON st.id = f.statement_id
    JOIN ingestion.report_versions rv ON rv.id = st.report_version_id
    JOIN ingestion.reports r ON r.id = st.report_id
    WHERE st.company_id::text = $1
      AND ((r.published_at IS NULL AND st.period_end_date <= $2::date)
        OR (r.published_at IS NOT NULL AND r.published_at <= $3))
      AND r.id::text NOT IN (SELECT supersedes_report_id::text FROM ingestion.reports WHERE supersedes_report_id IS NOT NULL)
),
agg AS (
    SELECT company_id, metric_code, count(DISTINCT report_id) AS n_reports, count(*) AS n_rows
    FROM elig GROUP BY company_id, metric_code
),
topcell AS (
    SELECT DISTINCT ON (company_id, metric_code)
           company_id, metric_code, period_end_date, fiscal_year, fiscal_month,
           version_no, collected_at, published_at, canonical_value, period_order
    FROM elig
    ORDER BY company_id, metric_code, period_end_date DESC, version_no DESC, period_order DESC
)
SELECT t.company_id, t.metric_code, t.period_end_date, t.fiscal_year, t.fiscal_month,
       t.published_at, t.collected_at, a.n_reports, a.n_rows, t.canonical_value, t.period_order
FROM topcell t JOIN agg a ON a.company_id = t.company_id AND a.metric_code = t.metric_code
ORDER BY t.metric_code`, cid, asOfDate, cutoff)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	out := []fundOriginRow{}
	for rows.Next() {
		var r fundOriginRow
		var pe sql.NullString
		if err := rows.Scan(&r.CompanyID, &r.MetricCode, &pe, &r.FiscalYear, &r.FiscalMonth,
			&r.PublishedAt, &r.CollectedAt, &r.NReports, &r.NRows, &r.CanonicalValue, &r.PeriodOrder); err != nil {
			continue
		}
		r.PeriodEnd = normDate(pe.String)
		out = append(out, r)
	}
	return out, true, rows.Err()
}

type sharesRow struct {
	SecurityID    string
	TsetmcShares  sql.NullFloat64
	TsetmcCollect sql.NullString
	TsetmcSource  sql.NullString
	BrsShares     sql.NullFloat64
	BrsAsOf       sql.NullString
	BrsCollect    sql.NullString
	BrsSource     sql.NullString
}

// vSharesItem منشأ شمارش سهام را می‌خواند و تصمیم وضعیت را به تابع خالص
// sharesItemDecide می‌سپارد (تست‌پذیر بدون DB).
func vSharesItem(db *sql.DB, dbErr error, cid, asOfDate string, cutoff any, px *priceCheck, vcm map[string]any) *evidenceItem {
	it := evItem("v_shares_input", "شمارش سهام و تاریخ مؤثر آن", evUnverified)
	it.Source = "PRIMARY: market.tsetmc_current_shares؛ FALLBACK: core.share_structure — قرارداد compute_metrics.select_current_shares"
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return it
	}
	srows, ok, err := sharesOriginFor(db, []string{cid}, cutoff, asOfDate)
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return it
	}
	sr := srows[cid]
	if sr == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: security فعال شرکت یافت نشد"}
		return it
	}
	var ev *sharesEventSummary
	if px != nil && px.RowFound && px.LastTradeDate != "" && sr.SecurityID != "" {
		shareDate0 := normDate(sr.TsetmcCollect.String)
		if shareDate0 == "" {
			shareDate0 = sr.BrsAsOf.String
		}
		if shareDate0 != "" {
			if e, err := sharesIntervalEvents(db, cid, sr.SecurityID, shareDate0, px.LastTradeDate); err == nil {
				ev = e
			}
		}
	}
	return sharesItemDecide(it, sr, px, vcm, cutoff, ev)
}

// sharesEventSummary خلاصه رویدادهای تغییر سرمایه/اقدامات شرکتی در بازه
// حساس بین snapshot سهام و تاریخ معامله قیمت — ممیزی گام ۲-ک-۱.
type sharesEventSummary struct {
	Confirmed []gin.H `json:"confirmed"`
	Possible  []gin.H `json:"possible"`
}

// sharesIntervalEvents رویدادهای معتبر یا ممکن در [dateA, dateB] را
// فقط‌خواندنی می‌خواند. نبود ردیف، اثبات نبود تغییر نیست و همین‌طور گزارش
// می‌شود (قید قرارداد).
func sharesIntervalEvents(db *sql.DB, cid, sid, dateA, dateB string) (*sharesEventSummary, error) {
	if db == nil || cid == "" || sid == "" || dateA == "" || dateB == "" {
		return nil, nil
	}
	lo, hi := dateA, dateB
	if hi < lo {
		lo, hi = hi, lo
	}
	out := &sharesEventSummary{Confirmed: []gin.H{}, Possible: []gin.H{}}
	rows, err := db.Query(`
		SELECT event_type, status,
		       COALESCE(effective_date::text, registered_at::date::text, announced_at::date::text)
		FROM core.share_events
		WHERE company_id = $1::uuid
		  AND COALESCE(effective_date, registered_at::date, announced_at::date)
		      BETWEEN $2::date AND $3::date`, cid, lo, hi)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	for rows.Next() {
		var et, st, d string
		if err := rows.Scan(&et, &st, &d); err == nil {
			item := gin.H{"kind": "share_events", "event_type": et, "date": d, "status": st}
			if st == "CONFIRMED" {
				out.Confirmed = append(out.Confirmed, item)
			} else {
				out.Possible = append(out.Possible, item)
			}
		}
	}
	rows2, err := db.Query(`
		SELECT action_type, action_date::text,
		       COALESCE(event_semantics_status, ''), COALESCE(adjustment_evidence_status, '')
		FROM market.corporate_actions
		WHERE security_id = $1::uuid AND action_date BETWEEN $2::date AND $3::date`, sid, lo, hi)
	if err != nil {
		return nil, err
	}
	defer rows2.Close()
	for rows2.Next() {
		var at, d, sem, ev string
		if err := rows2.Scan(&at, &d, &sem, &ev); err == nil {
			item := gin.H{"kind": "corporate_actions", "action_type": at,
				"date": d, "event_semantics_status": sem,
				"adjustment_evidence_status": ev}
			if sem == "CONFIRMED" && ev == "CONFIRMED" {
				out.Confirmed = append(out.Confirmed, item)
			} else {
				out.Possible = append(out.Possible, item)
			}
		}
	}
	return out, nil
}

// sharesItemDecide وضعیت آیتم سهام را از ردیف خوانده‌شده می‌سازد — تابع
// خالص برای تست.
func sharesItemDecide(it *evidenceItem, sr *sharesRow, px *priceCheck, vcm map[string]any, cutoff any, ev *sharesEventSummary) *evidenceItem {
	var shareDate, shareOrigin string
	switch {
	case sr.TsetmcShares.Valid:
		it.Status = evVerified
		shareOrigin = "TSETMC zTitad (PRIMARY)"
		shareDate = normDate(sr.TsetmcCollect.String)
		it.Fields = append(it.Fields,
			evidenceField{K: "تعداد سهام", V: trimFloat(sr.TsetmcShares.Float64)},
			evidenceField{K: "منبع", V: sr.TsetmcSource.String},
			evidenceField{K: "زمان گردآوری واقعی", V: sr.TsetmcCollect.String},
		)
	case sr.BrsShares.Valid:
		brsEligible := sr.BrsCollect.Valid && sr.BrsCollect.String != "" && cutoffBefore(cutoff, sr.BrsCollect.String)
		it.Status = evPartial
		shareOrigin = "core.share_structure (FALLBACK فروشنده BRS)"
		shareDate = sr.BrsAsOf.String
		it.Fields = append(it.Fields,
			evidenceField{K: "تعداد سهام", V: trimFloat(sr.BrsShares.Float64)},
			evidenceField{K: "تاریخ مؤثر snapshot", V: sr.BrsAsOf.String},
			evidenceField{K: "زمان گردآوری", V: sr.BrsCollect.String},
		)
		it.Limitations = []string{
			"PRIMARY (TSETMC) برای این security ردیفی در پنجره PIT ندارد؛ snapshot فروشنده روزانه است و قرارداد موتور آن را FALLBACK می‌داند",
		}
		if !brsEligible {
			it.Status = evUnverified
			it.Limitations = append(it.Limitations, "زمان گردآوری این snapshot بعد از cutoff آرتیفکت است — قرارداد pit_share_snapshot موتور آن را نامجاز می‌کند")
		}
	default:
		it.Status = evUnverified
		it.Summary = "هیچ snapshot سهام PIT (نه TSETMC نه BRS) برای این security یافت نشد"
		if vFactorsComputed(vcm) {
			it.Status = evConflicting
			it.Conflicts = []string{"آرتیفکت V نسبت‌های سر-سهام (P/E یا P/B) را با وضعیت valid محاسبه کرده اما کنترل مستقل هیچ snapshot سهام PIT نیافت — تعارض نیازمند بررسی"}
		}
		return it
	}

	// سازگاری زمانی سهام ↔ قیمت (همان share_price_gap_days موتور: ptd − ssd)
	if px != nil && px.RowFound && shareDate != "" {
		if pt, err := time.Parse("2006-01-02", px.LastTradeDate); err == nil {
			if st, err2 := time.Parse("2006-01-02", shareDate); err2 == nil {
				gap := int(pt.Sub(st).Hours() / 24)
				it.Fields = append(it.Fields,
					evidenceField{K: "تاریخ معامله قیمت", V: px.LastTradeDate},
					evidenceField{K: "فاصله (قیمت − سهام)", V: fmt.Sprintf("%d روز", gap)},
				)
				if gap > 0 {
					it.Fields = append(it.Fields,
						evidenceField{K: "تاریخ snapshot سهام", V: shareDate})
					if ev == nil {
						it.Limitations = append(it.Limitations, fmt.Sprintf("snapshot سهام %d روز قدیمی‌تر از تاریخ قیمت است — بدون شواهد اقدامات شرکتی، سازگاری تغییر سرمایه بین دو تاریخ اثبات‌ناپذیر است (هشدار موتور: share_snapshot_older_than_price)", gap))
					} else {
						it.Fields = append(it.Fields,
							evidenceField{K: "رویدادهای معتبر در بازه حساس", V: fmt.Sprintf("%d", len(ev.Confirmed))},
							evidenceField{K: "رویدادهای ممکن/دسته‌بندی‌نشده در بازه", V: fmt.Sprintf("%d", len(ev.Possible))})
						if len(ev.Confirmed) > 0 {
							it.Status = evConflicting
							it.Conflicts = append(it.Conflicts, fmt.Sprintf("%d رویداد معتبر (CONFIRMED) تغییر سرمایه/اقدام شرکتی دقیقاً در بازه بین snapshot سهام و تاریخ قیمت است — نسبت‌های سر-سهام این snapshot با مبنای سهام قبل از رویداد محاسبه شده‌اند و برای بازبینی ارزندگی علامت خوردند", len(ev.Confirmed)))
						} else {
							it.Limitations = append(it.Limitations, fmt.Sprintf("شکاف %d روزه ممیزی شد: %d رویداد معتبر و %d رویداد ممکن در share_events/corporate_actions برای این بازه ثبت نشده است — نبود ردیف، اثبات مطلق نبودِ تغییر نیست، اما تنها شواهد ثبت‌شده هم‌خوان‌اند", gap, len(ev.Confirmed), len(ev.Possible)))
						}
					}
					if it.Status == evVerified {
						it.Status = evPartial
					}
				} else if gap < 0 {
					it.Limitations = append(it.Limitations, "تاریخ مؤثر سهام جدیدتر از تاریخ معامله قیمت است — ترتیب زمانی نامعمول")
				}
			}
		}
	}
	if it.Summary == "" {
		it.Summary = "منشأ شمارش سهام: " + shareOrigin
	}
	return it
}

// sharesOriginFor منشأ شمارش سهام هر شرکت را با قرارداد
// compute_metrics.select_current_shares می‌خواند (PRIMARY tsetmc، FALLBACK BRS).
func sharesOriginFor(db *sql.DB, cids []string, cutoff any, asOfDate string) (map[string]*sharesRow, bool, error) {
	out := map[string]*sharesRow{}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `
WITH sec AS (
    SELECT DISTINCT ON (s.company_id::text)
        s.company_id::text AS company_id, s.id::text AS security_id
    FROM core.securities s
    WHERE s.company_id::text = ANY($1) AND s.is_active
    ORDER BY s.company_id::text, s.is_primary DESC,
             (SELECT count(*) FROM market.price_observations p0 WHERE p0.security_id = s.id) DESC,
             s.id::text DESC
),
t AS (
    SELECT DISTINCT ON (t.security_id::text) t.security_id::text AS sec, t.shares_count, t.collected_at, t.source
    FROM market.tsetmc_current_shares t
    WHERE t.collected_at <= $2
    ORDER BY t.security_id::text, t.collected_at DESC
),
b AS (
    SELECT DISTINCT ON (s.security_id::text) s.security_id::text AS sec, s.shares_count, s.as_of_date, s.collected_at, s.source
    FROM core.share_structure s
    WHERE s.as_of_date <= $3::date
    ORDER BY s.security_id::text, s.as_of_date DESC, s.collected_at DESC
)
SELECT sec.company_id, sec.security_id,
       t.shares_count, t.collected_at, t.source,
       b.shares_count, b.as_of_date, b.collected_at, b.source
FROM sec
LEFT JOIN t ON t.sec = sec.security_id
LEFT JOIN b ON b.sec = sec.security_id`, cids, cutoff, asOfDate)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid string
		var r sharesRow
		if err := rows.Scan(&cid, &r.SecurityID, &r.TsetmcShares, &r.TsetmcCollect, &r.TsetmcSource,
			&r.BrsShares, &r.BrsAsOf, &r.BrsCollect, &r.BrsSource); err != nil {
			continue
		}
		r.BrsAsOf.String = normDate(r.BrsAsOf.String)
		out[cid] = &r
	}
	return out, true, rows.Err()
}

type corpActionsRow struct {
	SecurityID       string
	CaN, CaConfirmed int
	CaEvidenceConf   int
	CaLastActionDate string
	SeN, SeConfirmed int
	SeLastEffective  string
}

// corpActionsFor شواهد ثبت‌شده اقدامات شرکتی را می‌خواند. موتور از این
// جداول استفاده نمی‌کند؛ خروجی فقط «وجود/نبود شواهد» را گزارش می‌کند.
func corpActionsFor(db *sql.DB, cids []string) (map[string]*corpActionsRow, bool, error) {
	out := map[string]*corpActionsRow{}
	ctx, cancel := context.WithTimeout(context.Background(), 6*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `
WITH sec AS (
    SELECT DISTINCT ON (s.company_id::text)
        s.company_id::text AS company_id, s.id::text AS security_id
    FROM core.securities s
    WHERE s.company_id::text = ANY($1) AND s.is_active
    ORDER BY s.company_id::text, s.is_primary DESC,
             (SELECT count(*) FROM market.price_observations p0 WHERE p0.security_id = s.id) DESC,
             s.id::text DESC
)
SELECT sec.company_id, sec.security_id,
    (SELECT count(*) FROM market.corporate_actions ca WHERE ca.security_id = sec.security_id::uuid),
    (SELECT count(*) FROM market.corporate_actions ca WHERE ca.security_id = sec.security_id::uuid AND ca.is_confirmed),
    (SELECT count(*) FROM market.corporate_actions ca WHERE ca.security_id = sec.security_id::uuid AND ca.adjustment_evidence_status = 'CONFIRMED'),
    (SELECT max(ca.action_date) FROM market.corporate_actions ca WHERE ca.security_id = sec.security_id::uuid),
    (SELECT count(*) FROM core.share_events se WHERE se.company_id::text = sec.company_id),
    (SELECT count(*) FROM core.share_events se WHERE se.company_id::text = sec.company_id AND se.status = 'CONFIRMED'),
    (SELECT max(se.effective_date) FROM core.share_events se WHERE se.company_id::text = sec.company_id)
FROM sec`, cids)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	for rows.Next() {
		var cid string
		var r corpActionsRow
		var caLast, seLast sql.NullString
		if err := rows.Scan(&cid, &r.SecurityID, &r.CaN, &r.CaConfirmed, &r.CaEvidenceConf,
			&caLast, &r.SeN, &r.SeConfirmed, &seLast); err != nil {
			continue
		}
		r.CaLastActionDate = normDate(caLast.String)
		r.SeLastEffective = normDate(seLast.String)
		out[cid] = &r
	}
	return out, true, rows.Err()
}

type tDailyRow struct {
	TradeDate string
	Close     sql.NullFloat64
	TV        sql.NullFloat64
	Series    sql.NullString
	Adjusted  sql.NullBool
	Method    sql.NullString
}

// tHistoryFor کل تاریخچه dedup‌شده یک security را در پنجره PIT آرتیفکت
// می‌خواند (همان قرارداد score_v2_t_raw.extract_daily_history).
func tHistoryFor(db *sql.DB, cid string, cutoff any, asOfDate string) ([]tDailyRow, bool, error) {
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	rows, err := db.QueryContext(ctx, `
WITH sec AS (
    SELECT DISTINCT ON (s.company_id::text)
        s.company_id::text AS company_id, s.id::text AS security_id
    FROM core.securities s
    WHERE s.company_id::text = $1 AND s.is_active
    ORDER BY s.company_id::text, s.is_primary DESC,
             (SELECT count(*) FROM market.price_observations p0 WHERE p0.security_id = s.id) DESC,
             s.id::text DESC
),
px AS (
    SELECT po.trade_date, po.collected_at, po.closing_price_rial, po.trade_value_rial,
           po.price_series, po.is_adjusted, po.adjustment_method
    FROM market.price_observations po
    JOIN sec ON po.security_id = sec.security_id::uuid
    WHERE po.collected_at <= $2 AND po.trade_date <= $3::date
),
dedup AS (
    SELECT DISTINCT ON (trade_date) trade_date, collected_at, closing_price_rial, trade_value_rial,
           price_series, is_adjusted, adjustment_method
    FROM px ORDER BY trade_date DESC, collected_at DESC
)
SELECT trade_date, closing_price_rial, trade_value_rial, price_series, is_adjusted, adjustment_method
FROM dedup ORDER BY trade_date ASC`, cid, cutoff, asOfDate)
	if err != nil {
		return nil, false, err
	}
	defer rows.Close()
	out := []tDailyRow{}
	for rows.Next() {
		var r tDailyRow
		var td sql.NullString
		if err := rows.Scan(&td, &r.Close, &r.TV, &r.Series, &r.Adjusted, &r.Method); err != nil {
			continue
		}
		r.TradeDate = normDate(td.String)
		out = append(out, r)
	}
	return out, true, rows.Err()
}

func normDate(s string) string {
	if len(s) >= 10 {
		return s[:10]
	}
	return s
}

// ─────────────────────────────────────────────────────────────────────────────
// محاسبات سری T — تابع خالص (تست‌پذیر بدون DB)
// ─────────────────────────────────────────────────────────────────────────────

type tWindowStats struct {
	NSessions       int
	NValidCloses    int
	LastValidDate   string
	LastValidAge    *int // (asOf − last valid close).days
	NJumpReturns    int
	JumpDates       []string // حداکثر ۳ نمونه (کل تاریخچه)
	NJumpMom6       int      // پرش‌ها در زنجیره momentum ۶ماهه از پایه تا آخرین بسته
	NJumpMom3       int      // پرش‌ها در زنجیره momentum ۳ماهه
	MaxGapDays      *int     // بیشترین فاصله تقویمی بین دو جلسه متوالی
	MomentumBase6m  bool     // آخرین بسته معتبر ≤ as_of−۶ ماه وجود دارد
	MomentumBase3m  bool
	LiqSpanDays     *int // فاصله تقویمی ۳۰ جلسه آخر
	LiqNValidTV     int  // تعداد مقادیر معتبر trade_value در پنجره (پیش‌نیاز موتور)
	LiqNMissingTV   int
	LiqNZeroTV      int
	VolSpanDays     *int // فاصله تقویمی ۳۱ بسته آخر
	VolNReturns     *int
	VolJumpInWindow bool
	SeriesValues    []string // مقادیر متمایز price_series
	AdjustedFalse   int      // ردیف‌هایی با is_adjusted=false
	Methods         []string // مقادیر متمایز adjustment_method
}

// tComputeStats آمار پنجره‌ها را از سری صعودی روزانه می‌سازد — عین ثابت‌های
// score_v2_t_raw.py (STALE_DAYS=14، JUMP_BAND=0.21، LIQ_WINDOW_OBS=30،
// WINDOW_MAX_SPAN_DAYS=60، VOL_WINDOW_CLOSES=31، PRICE_FLOOR=100).
func tComputeStats(rows []tDailyRow, asOf time.Time) *tWindowStats {
	st := &tWindowStats{SeriesValues: []string{}, Methods: []string{}, JumpDates: []string{}}
	if len(rows) == 0 {
		return st
	}
	st.NSessions = len(rows)
	seriesSet := map[string]bool{}
	methodSet := map[string]bool{}
	type sess struct {
		date  time.Time
		valid bool
		tv    *float64
	}
	sessions := make([]sess, 0, len(rows))
	for _, r := range rows {
		if r.Series.Valid && !seriesSet[r.Series.String] {
			seriesSet[r.Series.String] = true
			st.SeriesValues = append(st.SeriesValues, r.Series.String)
		}
		if r.Method.Valid && !methodSet[r.Method.String] {
			methodSet[r.Method.String] = true
			st.Methods = append(st.Methods, r.Method.String)
		}
		if r.Adjusted.Valid && !r.Adjusted.Bool {
			st.AdjustedFalse++
		}
		valid := r.Close.Valid && r.Close.Float64 >= tPriceFloor
		var tv *float64
		if r.TV.Valid {
			v := r.TV.Float64
			tv = &v
		}
		td, err := time.Parse("2006-01-02", r.TradeDate)
		if err != nil {
			continue
		}
		sessions = append(sessions, sess{date: td, valid: valid, tv: tv})
	}

	validIdx := []int{}
	for i, s := range sessions {
		if s.valid {
			validIdx = append(validIdx, i)
		}
	}
	st.NValidCloses = len(validIdx)
	if len(validIdx) > 0 {
		last := sessions[validIdx[len(validIdx)-1]]
		age := int(asOf.Sub(last.date).Hours() / 24)
		st.LastValidDate = last.date.Format("2006-01-02")
		st.LastValidAge = &age
	}

	// بیشترین فاصله تقویمی بین جلسات متوالی (همه جلسات، نه فقط بسته معتبر)
	for k := 1; k < len(sessions); k++ {
		gap := int(sessions[k].date.Sub(sessions[k-1].date).Hours() / 24)
		if st.MaxGapDays == nil || gap > *st.MaxGapDays {
			g := gap
			st.MaxGapDays = &g
		}
	}
	// بازده‌های متوالی بین بسته‌های معتبر — آشکارساز شکاف همان موتور: |r| > 0.21
	for k := 1; k < len(validIdx); k++ {
		pa := rows[validIdx[k-1]].Close.Float64
		pb := rows[validIdx[k]].Close.Float64
		if pa > 0 {
			r := pb/pa - 1
			if math.Abs(r) >= tJumpBand {
				st.NJumpReturns++
				if len(st.JumpDates) < 3 {
					st.JumpDates = append(st.JumpDates, rows[validIdx[k]].TradeDate)
				}
			}
		}
	}

	// پایه momentum: آخرین بسته معتبر ≤ مرجع (as_of − ۶/۳ ماه تقویمی، month-clamped).
	// آشکارساز پرش موتور فقط داخل زنجیره بازده از پایه تا آخرین بسته است
	// (score_v2_t_raw.py: پرش در زنجیره momentum → invalid)، نه کل تاریخچه.
	ref6 := subMonthsClamped(asOf, 6)
	ref3 := subMonthsClamped(asOf, 3)
	base6Idx, base3Idx := -1, -1
	for _, i := range validIdx {
		d := sessions[i].date
		if !d.After(ref6) {
			st.MomentumBase6m = true
			base6Idx = i
		}
		if !d.After(ref3) {
			st.MomentumBase3m = true
			base3Idx = i
		}
	}
	countChainJumps := func(from int) int {
		n := 0
		if from < 0 {
			return 0
		}
		for k := from + 1; k < len(validIdx); k++ {
			pa := rows[validIdx[k-1]].Close.Float64
			pb := rows[validIdx[k]].Close.Float64
			if pa > 0 && math.Abs(pb/pa-1) >= tJumpBand {
				n++
			}
		}
		return n
	}
	st.NJumpMom6 = countChainJumps(base6Idx)
	st.NJumpMom3 = countChainJumps(base3Idx)

	// پنجره نقدشوندگی: ۳۰ جلسه آخر (همه جلسات dedup‌شده، حتی بی‌معامله)
	nLiq := tLiqWindowObs
	if len(sessions) < nLiq {
		nLiq = len(sessions)
	}
	if nLiq > 0 {
		first := sessions[len(sessions)-nLiq].date
		lastD := sessions[len(sessions)-1].date
		span := int(lastD.Sub(first).Hours() / 24)
		st.LiqSpanDays = &span
		for _, s := range sessions[len(sessions)-nLiq:] {
			if s.tv == nil {
				st.LiqNMissingTV++
			} else {
				if *s.tv >= 0 {
					st.LiqNValidTV++
				}
				if *s.tv == 0 {
					st.LiqNZeroTV++
				}
			}
		}
	}

	// پنجره نوسان: ۳۱ بسته معتبر آخر → حداکثر ۳۰ بازده
	nVol := tVolWindowCloses
	if len(validIdx) < nVol {
		nVol = len(validIdx)
	}
	if nVol >= 2 {
		first := sessions[validIdx[len(validIdx)-nVol]].date
		lastD := sessions[validIdx[len(validIdx)-1]].date
		span := int(lastD.Sub(first).Hours() / 24)
		st.VolSpanDays = &span
		nr := nVol - 1
		st.VolNReturns = &nr
		for k := len(validIdx) - nVol + 1; k < len(validIdx); k++ {
			pa := rows[validIdx[k-1]].Close.Float64
			pb := rows[validIdx[k]].Close.Float64
			if pa > 0 && math.Abs(pb/pa-1) >= tJumpBand {
				st.VolJumpInWindow = true
				break
			}
		}
	}
	return st
}

func subMonthsClamped(t time.Time, m int) time.Time {
	y, mo, d := t.Date()
	newMo := int(mo) - m
	newY := y
	for newMo <= 0 {
		newMo += 12
		newY--
	}
	lastDay := time.Date(newY, time.Month(newMo)+1, 0, 0, 0, 0, 0, t.Location()).Day()
	if d > lastDay {
		d = lastDay
	}
	return time.Date(newY, time.Month(newMo), d, 0, 0, 0, 0, t.Location())
}

// ─────────────────────────────────────────────────────────────────────────────
// مونتاژ زنجیره شواهد یک شرکت
// ─────────────────────────────────────────────────────────────────────────────

// evidenceChainFor برای یک شرکت، شواهد سه محور را می‌سازد. px نتیجه
// priceChecksFor برای همین شرکت است (قبلاً در detail محاسبه می‌شود) تا
// کوئری قیمت تکرار نشود.
func evidenceChainFor(cid string, qcm, vcm, tcm map[string]any, b *qvtBundle, px *priceCheck) *evidenceChain {
	db, dbErr := qvtPriceDB()
	return evidenceChainForDB(cid, qcm, vcm, tcm, b, px, db, dbErr)
}

// evidenceChainForDB نسخه تزریق‌شده — نسبت به اتصال DB خالص است تا تست‌ها
// بدون دیتابیس مسیر تخریب محترمانه را پوشش دهند.
func evidenceChainForDB(cid string, qcm, vcm, tcm map[string]any, b *qvtBundle, px *priceCheck, db *sql.DB, dbErr error) *evidenceChain {
	chain := &evidenceChain{
		CompanyID:    cid,
		StatusCounts: map[string]int{},
		Notes: []string{
			"این لایه فقط ردیابی ورودی است — هیچ امتیاز، رتبه یا درصد اطمینانی نمی‌سازد و صرف وجود داده را تأیید صحت اقتصادی نمی‌داند",
			"«تاریخ داده» و «تاریخ گردآوری» و «تاریخ انتشار» و «تاریخ مؤثر» جدا نگه داشته می‌شوند؛ حدس زدن هیچ‌کدام مجاز نیست",
		},
	}

	cutoffRaw := qvtStr(b.V, "cutoff")
	asOfDate := qvtStr(b.V, "as_of")
	var cutoff any
	if t, err := qvtParseInstant(cutoffRaw); err == nil {
		cutoff = t
	} else {
		cutoff = cutoffRaw
	}

	// ── محور Q ──
	qAxis := axisEvidence{Axis: "q", AxisLabel: "Q — بنیادی (کیفیت)"}
	if qcm == nil {
		qAxis.Items = append(qAxis.Items, *evNoArtifact("q_axis_absent", "آرتیفکت Q", "آرتیفکت Q برای این شرکت ردیفی ندارد"))
	} else {
		qAxis.Items = append(qAxis.Items, *qOriginItem(db, dbErr, cid, asOfDate, cutoff))
		qAxis.Items = append(qAxis.Items, *qRawPublicationItem())
	}
	finalizeAxis(&qAxis)
	chain.Axes = append(chain.Axes, qAxis)

	// ── محور V ──
	vAxis := axisEvidence{Axis: "v", AxisLabel: "V — ارزندگی"}
	if vcm == nil {
		vAxis.Items = append(vAxis.Items, *evNoArtifact("v_axis_absent", "آرتیفکت V", "آرتیفکت V برای این شرکت ردیفی ندارد"))
	} else {
		vAxis.Items = append(vAxis.Items, *vPriceItem(px))
		vAxis.Items = append(vAxis.Items, *vSharesItem(db, dbErr, cid, asOfDate, cutoff, px, vcm))
		vAxis.Items = append(vAxis.Items, *vCorpActionsItem(db, dbErr, cid))
		vAxis.Items = append(vAxis.Items, *vFundamentalsItem(db, dbErr, cid, asOfDate, cutoff))
	}
	finalizeAxis(&vAxis)
	chain.Axes = append(chain.Axes, vAxis)

	// ── محور T ──
	tAxis := axisEvidence{Axis: "t", AxisLabel: "T — زمان‌بندی بازار"}
	if tcm == nil {
		tAxis.Items = append(tAxis.Items, *evNoArtifact("t_axis_absent", "آرتیفکت T", "آرتیفکت T برای این شرکت ردیفی ندارد"))
	} else {
		for _, it := range tHistoryItems(db, dbErr, cid, asOfDate, cutoff, tcm) {
			tAxis.Items = append(tAxis.Items, *it)
		}
		tAxis.Items = append(tAxis.Items, *tAdjustmentItem(db, dbErr, cid, asOfDate, cutoff))
	}
	finalizeAxis(&tAxis)
	chain.Axes = append(chain.Axes, tAxis)

	for _, ax := range chain.Axes {
		for _, it := range ax.Items {
			if it.Structural {
				continue
			}
			chain.StatusCounts[it.Status]++
		}
	}
	statuses := make([]string, 0, len(chain.Axes))
	for _, ax := range chain.Axes {
		statuses = append(statuses, ax.Status)
	}
	chain.Overall = evWorst(statuses)
	chain.OverallLabel = evStatusLabels[chain.Overall]
	return chain
}

func finalizeAxis(ax *axisEvidence) {
	statuses := make([]string, 0, len(ax.Items))
	for _, it := range ax.Items {
		if it.Structural {
			continue
		}
		statuses = append(statuses, it.Status)
	}
	ax.Status = evWorst(statuses)
	ax.StatusLabel = evStatusLabels[ax.Status]
}

func evNoArtifact(key, label, note string) *evidenceItem {
	it := &evidenceItem{Key: key, Label: label, Status: evUnverified, StatusLabel: evStatusLabels[evUnverified], Checked: true}
	it.Limitations = []string{note}
	return it
}

// qOriginItem منشأ صورت‌های مالی Q را با عین predicate موتور کنترل می‌کند.
func qOriginItem(db *sql.DB, dbErr error, cid, asOfDate string, cutoff any) *evidenceItem {
	it := evItem("q_financial_origin", "منشأ صورت‌های مالی (پایه همه فاکتورهای Q)", evUnverified)
	it.Source = qSourceTables
	it.Fields = []evidenceField{{K: "قاعده دیده‌شدن (PIT)", V: qPitRule}}
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return it
	}
	rows, ok, err := fundOriginFor(db, cid, asOfDate, cutoff)
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return it
	}
	if len(rows) == 0 {
		it.Summary = "هیچ ردیف مالی مجازی در پنجره PIT برای این شرکت یافت نشد"
		it.Limitations = []string{"نبود ردیف مالی به‌معنی صفر فرض کردن مقادیر نیست؛ فاکتورهای Q باید نامضمول باشند"}
		return it
	}
	var withPub, withoutPub int
	var latestPeriod, latestMetric string
	for _, r := range rows {
		if r.PublishedAt.Valid && r.PublishedAt.String != "" {
			withPub++
		} else {
			withoutPub++
		}
		if r.PeriodEnd > latestPeriod {
			latestPeriod = r.PeriodEnd
			latestMetric = r.MetricCode
		}
	}
	rawVals := []string{}
	for _, r := range rows {
		if r.CanonicalValue.Valid {
			rawVals = append(rawVals, r.MetricCode+"="+trimFloat(r.CanonicalValue.Float64))
		}
	}
	sort.Strings(rawVals)
	it.Fields = append(it.Fields,
		evidenceField{K: "جدول‌های خوانده‌شده", V: "financial_facts / financial_statements / report_versions / reports"},
		evidenceField{K: "metric_codeهای دارای ردیف مجاز", V: fmt.Sprintf("%d", len(rows))},
		evidenceField{K: "آخرین دوره مالی مجاز", V: latestPeriod + " (" + latestMetric + ")"},
		evidenceField{K: "گزارش‌های دارای published_at واقعی", V: fmt.Sprintf("%d از %d", withPub, len(rows))},
	)
	if len(rawVals) > 0 {
		it.Fields = append(it.Fields,
			evidenceField{K: "مقادیر خام سلول برنده (همان داده‌ای که موتور مصرف کرده — بدون تغییر فرمول)", V: strings.Join(rawVals, "، ")},
			evidenceField{K: "معنای period_order", V: "1=دوره جاری، 2=مقایسه‌ای سال قبل، 3=سال مالی قبل"})
	}
	if withoutPub == 0 {
		it.Status = evVerified
		it.Summary = "همه گزارش‌های تغذیه‌کننده published_at واقعی دارند و با cutoff هم‌خوان‌اند (لایه provenance خود آرتیفکت همچنان بدون source_ref است و PIT-unverified می‌ماند)"
	} else {
		it.Status = evPartial
		it.Summary = fmt.Sprintf("%d از %d metric بدون published_at واقعی‌اند — دیده‌شدن آنها با period_end ≤ as_of جایگزین شده (قرارداد موتور برای گزارش‌های مهاجرت‌شده)", withoutPub, len(rows))
		it.Limitations = []string{
			"تاریخ انتشار واقعی این گزارش‌ها در منبع ثبت نشده و حدس زده نمی‌شود؛ همان محدودیتی که لایه provenance آرتیفکت را unverified_no_publication_date کرده",
		}
	}
	return it
}

// qRawPublicationItem یافته ساختاری: آرتیفکت Q مقدار خام فاکتورها را
// منتشر نمی‌کند — فقط امتیاز نرمال‌شده و پوشش.
func qRawPublicationItem() *evidenceItem {
	it := evItem("q_raw_values_publication", "انتشار مقدار خام فاکتورهای Q در آرتیفکت", evUnverified)
	it.Structural = true
	it.Source = "v2_q_observed_report.json (ساختار از score_v2_q_observed.py:397-431)"
	it.Summary = "آرتیفکت Q هیچ مقدار خامی (حاشیه سود، ROE، …) منتشر نمی‌کند — فقط امتیاز نرمال‌شده و contribution_points؛ مقایسه مستقل نسبت‌ها با منبع از طریق این سرویس ممکن نیست"
	it.Limitations = []string{
		"مقدارهای خام Q فقط در companion آزمایشی v2_qvt_pilot.json همان اجرا هستند که این سرویس نمایش نمی‌دهد",
		"این یافته ساختاری است و نبود خطا؛ به تفاوت checked=true (ساختار بررسی شد) و نبود شواهد اشاره دارد",
	}
	return it
}

func vPriceItem(px *priceCheck) *evidenceItem {
	it := evItem("v_price_input", "قیمت استفاده‌شده و تاریخ معامله آن", evUnverified)
	if px == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل قیمت برای این درخواست اجرا نشد"}
		return it
	}
	if !px.Available {
		it.Checked = false
		it.Limitations = []string{px.Note}
		return it
	}
	it.Source = px.Source
	it.Fields = append(it.Fields,
		evidenceField{K: "تاریخ معامله آخرین قیمت", V: px.LastTradeDate},
		evidenceField{K: "زمان گردآوری", V: px.CollectedAt},
		evidenceField{K: "سن تقویمی نسبت به as_of", V: fmt.Sprintf("%d روز", derefInt(px.AgeDays))},
		evidenceField{K: "سیاست تازگی آرتیفکت", V: fmt.Sprintf("%d روز (روز تقویمی)", derefInt(px.PolicyDays))},
	)
	if px.Violation != nil && *px.Violation {
		it.Status = evPartial
		it.Summary = "ردیف قیمت در منبع ردیابی شد اما سن آن سیاست تازگی آرتیفکت را نقض می‌کند (همان یافته‌ای که Risk Gate با قاعده B1 ارزیابی می‌کند)"
		it.Limitations = []string{px.Note}
	} else {
		it.Status = evVerified
		it.Summary = "ردیف قیمت در پنجره PIT آرتیفکت از market.price_observations ردیابی شد و با قرارداد موتور هم‌خوان است"
	}
	return it
}

func vCorpActionsItem(db *sql.DB, dbErr error, cid string) *evidenceItem {
	it := evItem("v_corporate_actions", "شواهد اقدامات شرکتی (تغییر سرمایه/تعدیل)", evUnverified)
	it.Source = "market.corporate_actions + core.share_events — فقط شواهد ثبت‌شده؛ موتور V این جداول را مصرف نمی‌کند"
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return it
	}
	caRows, ok, err := corpActionsFor(db, []string{cid})
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return it
	}
	r := caRows[cid]
	if r == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: security فعال شرکت یافت نشد"}
		return it
	}
	it.Fields = append(it.Fields,
		evidenceField{K: "ردیف‌های market.corporate_actions", V: fmt.Sprintf("%d (تأییدشده: %d، با شواهد مکانیکی CONFIRMED: %d)", r.CaN, r.CaConfirmed, r.CaEvidenceConf)},
		evidenceField{K: "آخرین action_date", V: orDash(r.CaLastActionDate)},
		evidenceField{K: "ردیف‌های core.share_events", V: fmt.Sprintf("%d (CONFIRMED: %d)", r.SeN, r.SeConfirmed)},
		evidenceField{K: "آخرین effective_date", V: orDash(r.SeLastEffective)},
	)
	if r.CaN == 0 && r.SeN == 0 {
		it.Summary = "هیچ سابقه اقدامات شرکتی ثبت نشده — همان خلأیی که هشدار موتور (share_snapshot_older_than_price) صریح می‌گوید: سازگاری تغییر سرمایه اثبات‌ناپذیر است"
		it.Limitations = append(it.Limitations, "نبود سابقه نباید «نبود اقدام شرکتی» تفسیر شود — ثبت‌نشده است، نه ثبت‌شده-به-عدم-وقوع")
		return it
	}
	it.Status = evPartial
	it.Summary = "شواهد اقدامات شرکتی ثبت‌شده وجود دارد؛ اما موتور V از این جداول استفاده نمی‌کند و تطبیق آنها با پنجره سهام↔قیمت نیازمند اعتبارسنجی semantics است"
	if r.CaEvidenceConf == 0 && r.SeConfirmed == 0 {
		it.Limitations = append(it.Limitations, "هیچ ردیفی وضعیت تأیید (CONFIRMED) ندارد")
	}
	return it
}

func vFundamentalsItem(db *sql.DB, dbErr error, cid, asOfDate string, cutoff any) *evidenceItem {
	it := evItem("v_fundamentals_origin", "منشأ TTM سود/فروش و حقوق مالکانه", evUnverified)
	it.Source = "همان جداول Q؛ TTM با resolve_ttm و equity سلول order-1 آخرین گزارش"
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return it
	}
	rows, ok, err := fundOriginFor(db, cid, asOfDate, cutoff)
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return it
	}
	want := map[string]string{
		"net_profit":   "سود خالص (مخرج P/E)",
		"revenue":      "فروش (مخرج P/S)",
		"total_equity": "حقوق مالکانه (مخرج P/B)",
	}
	var found []string
	var missing []string
	for code, label := range want {
		hit := false
		for _, r := range rows {
			if r.MetricCode == code {
				hit = true
				found = append(found, fmt.Sprintf("%s: آخرین دوره %s (از %d گزارش)", label, r.PeriodEnd, r.NReports))
				if r.PeriodEnd != "" {
					if pe, err := time.Parse("2006-01-02", r.PeriodEnd); err == nil {
						if ao, err2 := time.Parse("2006-01-02", asOfDate); err2 == nil {
							age := int(ao.Sub(pe).Hours() / 24)
							if code == "total_equity" && age > vBalanceSheetStaleDays {
								it.Limitations = append(it.Limitations, fmt.Sprintf("حقوق مالکانه %d روز قدیمی است — بیش از سیاست BALANCE_SHEET_STALE_DAYS=%d موتور (هشدار-فقط)", age, vBalanceSheetStaleDays))
							}
						}
					}
				}
				if r.PublishedAt.Valid && r.PublishedAt.String != "" {
					it.Fields = append(it.Fields, evidenceField{K: "published_at گزارش " + code, V: r.PublishedAt.String})
				} else {
					it.Limitations = append(it.Limitations, "گزارش "+code+" published_at واقعی ندارد — دیده‌شدن با period_end جایگزین شده")
				}
				if r.CollectedAt.Valid {
					it.Fields = append(it.Fields, evidenceField{K: "collected_at نسخه " + code, V: r.CollectedAt.String})
				}
			}
		}
		if !hit {
			missing = append(missing, label)
		}
	}
	sort.Strings(found)
	it.Fields = append(it.Fields, evidenceField{K: "ردیف‌های یافت‌شده", V: fmt.Sprintf("%d", len(found))})
	if len(missing) == len(want) {
		it.Summary = "هیچ‌کدام از سه ورودی بنیادی V در پنجره PIT یافت نشد"
		it.Limitations = append(it.Limitations, "نبود ردیف نباید صفر فرض شود؛ فاکتورهای مربوط باید refusal باشند")
		return it
	}
	it.Status = evVerified
	it.Summary = fmt.Sprintf("منشأ بنیادی‌ها ردیابی شد (%s)", joinShort(found, 3))
	if len(missing) > 0 {
		it.Status = evPartial
		it.Limitations = append(it.Limitations, "یافت نشد: "+joinShort(missing, 3)+" — فاکتور وابسته باید نامضمول باشد")
	}
	for _, l := range it.Limitations {
		if strings.Contains(l, "published_at واقعی ندارد") {
			it.Status = evPartial
			break
		}
	}
	return it
}

func tHistoryItems(db *sql.DB, dbErr error, cid, asOfDate string, cutoff any, tcm map[string]any) []*evidenceItem {
	it := evItem("t_price_window", "پنجره تاریخچه قیمت، پوشش جلسات و شکاف‌ها", evUnverified)
	it.Source = "market.price_observations — dedup آخرین collected_at برای هر trade_date؛ قیمت بسته vendor-adjusted"
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return []*evidenceItem{it, tWindowsPendingItem()}
	}
	hist, ok, err := tHistoryFor(db, cid, cutoff, asOfDate)
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return []*evidenceItem{it, tWindowsPendingItem()}
	}
	asOf, _ := time.Parse("2006-01-02", asOfDate)
	st := tComputeStats(hist, asOf)
	if st.NSessions == 0 {
		it.Summary = "هیچ جلسه قیمتی در پنجره PIT یافت نشد"
		if tAnyFactorIncluded(tcm) {
			it.Status = evConflicting
			it.Conflicts = []string{"آرتیفکت T فاکتورِ نامضمول‌نشده برای این شرکت دارد اما کنترل مستقل هیچ تاریخچه قیمتی نیافت"}
		}
		return []*evidenceItem{it, tWindowsPendingItem()}
	}
	it.Fields = append(it.Fields,
		evidenceField{K: "تعداد جلسات dedup‌شده", V: fmt.Sprintf("%d", st.NSessions)},
		evidenceField{K: "اولین جلسه", V: hist[0].TradeDate},
		evidenceField{K: "آخرین بسته معتبر (≥۱۰۰ ریال)", V: orDash(st.LastValidDate)},
		evidenceField{K: "سن آخرین بسته معتبر", V: fmt.Sprintf("%d روز (سیاست STALE_DAYS=%d)", derefInt(st.LastValidAge), tStaleDays)},
		evidenceField{K: "بیشترین فاصله جلسات متوالی", V: fmt.Sprintf("%d روز", derefInt(st.MaxGapDays))},
		evidenceField{K: "بازده‌های یک‌روزه فراتر از JUMP_BAND", V: fmt.Sprintf("%d (آستانه ±%.0f%% موتور)", st.NJumpReturns, tJumpBand*100)},
	)
	status := evVerified
	lims := []string{}
	if st.LastValidAge != nil && *st.LastValidAge > tStaleDays {
		status = evPartial
		lims = append(lims, fmt.Sprintf("آخرین بسته معتبر %d روز قبل است — بیش از سیاست STALE_DAYS=%d (موتور همه پنج فاکتور T را invalid می‌کند)", *st.LastValidAge, tStaleDays))
	}
	if st.NJumpMom6 > 0 || st.NJumpMom3 > 0 {
		if status == evVerified {
			status = evPartial
		}
		lims = append(lims, fmt.Sprintf("بازده مشکوک به شکاف/تعدیل‌نشدگی داخل زنجیره momentum (۶ماهه: %d، ۳ماهه: %d) — همان آشکارساز suspected_unadjusted_gap موتور", st.NJumpMom6, st.NJumpMom3))
	}
	it.Status = status
	it.Limitations = append(it.Limitations, lims...)
	it.Summary = fmt.Sprintf("تاریخچه در پنجره PIT ردیابی شد (%d جلسه)؛ ثابت‌های موتور عیناً به‌کار رفتند", st.NSessions)

	// اعتبار پنجره‌ها در برابر وضعیت فاکتورهای آرتیفکت
	windows := evItem("t_windows_validity", "اعتبار پنجره‌های momentum/نقدشوندگی/نوسان در برابر آرتیفکت", evUnverified)
	windows.Source = "ثابت‌های score_v2_t_raw.py:126-135 در برابر وضعیت فاکتورهای آرتیفکت T"
	windows.Fields = []evidenceField{
		{K: "پایه momentum ۶ماهه", V: yesNo(st.MomentumBase6m)},
		{K: "پایه momentum ۳ماهه", V: yesNo(st.MomentumBase3m)},
		{K: "پنجره نقدشوندگی (۳۰ جلسه)", V: fmt.Sprintf("فاصله %d روز — سقف %d؛ مقدارهای معتبر: %d (حداقل %d) (بی‌معامله: %d، بدون مقدار: %d)", derefInt(st.LiqSpanDays), tWindowMaxSpan, st.LiqNValidTV, tLiqMinObs, st.LiqNZeroTV, st.LiqNMissingTV)},
		{K: "پنجره نوسان (۳۱ بسته)", V: fmt.Sprintf("بازده‌ها: %s، فاصله %d روز", orDash(intPtrStr(st.VolNReturns)), derefInt(st.VolSpanDays))},
	}
	conflicts := tWindowConflicts(tcm, st)
	prereqOK := tWindowsPrereqOK(st)
	switch {
	case len(conflicts) > 0:
		windows.Status = evConflicting
		windows.Conflicts = conflicts
		windows.Summary = "وضعیت فاکتورهای آرتیفکت T با پنجره‌های بازمحاسبه‌شده تعارض دارد"
	case prereqOK:
		windows.Status = evVerified
		windows.Summary = "پنجره‌ها با ثابت‌های موتور بازمحاسبه شد و با وضعیت فاکتورهای آرتیفکت هم‌خوان است"
	default:
		windows.Status = evVerified
		windows.Summary = "پیش‌نیازهای داده پنجره‌ها کفایت نمی‌کند و آرتیفکت هم فاکتورهای مربوط را نامضمول کرده — هم‌خوان"
	}
	return []*evidenceItem{it, windows}
}

// tWindowsPendingItem حالت تخریب محترمانه آیتم پنجره‌ها وقتی تاریخچه
// خوانده نشد.
func tWindowsPendingItem() *evidenceItem {
	w := evItem("t_windows_validity", "اعتبار پنجره‌های momentum/نقدشوندگی/نوسان در برابر آرتیفکت", evUnverified)
	w.Checked = false
	w.Source = "ثابت‌های score_v2_t_raw.py:126-135 در برابر وضعیت فاکتورهای آرتیفکت T"
	w.Limitations = []string{"بدون تاریخچه قیمت، اعتبارسنجی پنجره‌ها ممکن نشد — خطا از نبود داده جدا می‌ماند"}
	return w
}

// tWindowConflicts تنها جهت واقعی تعارض را گزارش می‌کند: فاکتورِ
// included=valid آرتیفکت که پیش‌نیاز داده‌ای‌اش در بازمحاسبه برقرار نیست.
func tWindowConflicts(tcm map[string]any, st *tWindowStats) []string {
	var conflicts []string
	check := func(fid string, ok bool, why string) {
		f, _ := tcm["factors"].(map[string]any)
		fe, _ := f[fid].(map[string]any)
		if fe == nil {
			return
		}
		rawStatus, _ := fe["raw_status"].(string)
		included, _ := fe["included"].(bool)
		if (included && rawStatus == "valid") && !ok {
			conflicts = append(conflicts, fmt.Sprintf("فاکتور %s در آرتیفکت valid است اما %s", fid, why))
		}
	}
	check("momentum_6m_rel", st.MomentumBase6m && st.LastValidAge != nil && *st.LastValidAge <= tStaleDays && st.NJumpMom6 == 0, "پایه ۶ماهه/سلامت زنجیره بازده آن در بازمحاسبه برقرار نیست")
	check("relative_strength_6m_sector", st.MomentumBase6m && st.LastValidAge != nil && *st.LastValidAge <= tStaleDays && st.NJumpMom6 == 0, "پایه ۶ماهه/سلامت زنجیره بازده آن در بازمحاسبه برقرار نیست")
	check("momentum_3m_rel", st.MomentumBase3m && st.LastValidAge != nil && *st.LastValidAge <= tStaleDays && st.NJumpMom3 == 0, "پایه ۳ماهه/سلامت زنجیره بازده آن در بازمحاسبه برقرار نیست")
	check("liquidity", st.LiqSpanDays != nil && *st.LiqSpanDays <= tWindowMaxSpan && (st.LiqNValidTV >= tLiqMinObs) && st.LastValidAge != nil && *st.LastValidAge <= tStaleDays, "پنجره ۳۰ جلسه‌اش کفایت مقدار معامله/فاصله مجاز را ندارد")
	check("low_volatility", st.VolNReturns != nil && *st.VolNReturns >= tVolMinReturns && st.VolSpanDays != nil && *st.VolSpanDays <= tWindowMaxSpan && !st.VolJumpInWindow && st.LastValidAge != nil && *st.LastValidAge <= tStaleDays, "پنجره ۳۱ بسته‌اش کفایت/فاصله/سلامت را ندارد")
	return conflicts
}

func tWindowsPrereqOK(st *tWindowStats) bool {
	ok := st.MomentumBase6m && st.MomentumBase3m &&
		st.LiqSpanDays != nil && *st.LiqSpanDays <= tWindowMaxSpan && st.LiqNValidTV >= tLiqMinObs &&
		st.VolNReturns != nil && *st.VolNReturns >= tVolMinReturns && st.VolSpanDays != nil && *st.VolSpanDays <= tWindowMaxSpan &&
		st.LastValidAge != nil && *st.LastValidAge <= tStaleDays && st.NJumpMom6 == 0 && st.NJumpMom3 == 0
	return ok
}

func tAdjustmentItem(db *sql.DB, dbErr error, cid, asOfDate string, cutoff any) *evidenceItem {
	it := evItem("t_adjustment_basis", "وضعیت تعدیل قیمت (ادعای سری vendor-adjusted)", evUnverified)
	it.Source = "market.price_observations.price_series / is_adjusted / adjustment_method"
	it.Summary = "آرتیفکت T ادعا می‌کند کل سری vendor-adjusted است (construction.price_basis)؛ این کنترل همان ادعا را با پرچم‌های ذخیره‌ساز می‌سنجد"
	if dbErr != nil || db == nil {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد: " + errText(dbErr)}
		return it
	}
	hist, ok, err := tHistoryFor(db, cid, cutoff, asOfDate)
	if err != nil || !ok {
		it.Checked = false
		it.Limitations = []string{"کنترل ممکن نشد (کوئری منبع): " + errText(err)}
		return it
	}
	if len(hist) == 0 {
		it.Status = evUnverified
		it.Limitations = append(it.Limitations, "تاریخچه‌ای برای سنجش پرچم تعدیل نیست")
		return it
	}
	st := tComputeStats(hist, time.Time{})
	it.Fields = append(it.Fields,
		evidenceField{K: "مقادیر price_series", V: joinShort(st.SeriesValues, 3)},
		evidenceField{K: "ردیف‌های is_adjusted=false", V: fmt.Sprintf("%d", st.AdjustedFalse)},
		evidenceField{K: "adjustment_methodها", V: joinShort(st.Methods, 3)},
	)
	if st.AdjustedFalse > 0 || containsNonAdjusted(st.SeriesValues) {
		it.Status = evConflicting
		it.Conflicts = []string{"ذخیره‌ساز ردیف‌های تعدیل‌نشده دارد در حالی که آرتیفکت T کل سری را vendor-adjusted فرض کرده — تعارض نیازمند اصلاح داده"}
		return it
	}
	it.Status = evVerified
	it.Summary = "پرچم‌های ذخیره‌ساز ادعای آرتیفکت (سری تعدیل‌شده فروشنده) را تأیید می‌کنند"
	return it
}

// ─────────────────────────────────────────────────────────────────────────────
// کمک‌تابع‌ها
// ─────────────────────────────────────────────────────────────────────────────

func vFactorsComputed(vcm map[string]any) bool {
	fs, _ := vcm["factors"].(map[string]any)
	for _, fv := range fs {
		fe, _ := fv.(map[string]any)
		if fe == nil {
			continue
		}
		rawStatus, _ := fe["raw_status"].(string)
		included, _ := fe["included"].(bool)
		if included && rawStatus == "valid" {
			return true
		}
	}
	return false
}

func tAnyFactorIncluded(tcm map[string]any) bool {
	return vFactorsComputed(tcm)
}

func containsNonAdjusted(vals []string) bool {
	for _, v := range vals {
		if v != "" && v != "adjusted" {
			return true
		}
	}
	return false
}

func cutoffBefore(cutoff any, collected string) bool {
	ct, ok := cutoff.(time.Time)
	if !ok {
		return true
	}
	cc, err := time.Parse(time.RFC3339, collected)
	if err != nil {
		return true
	}
	return !cc.After(ct)
}

func errText(err error) string {
	if err == nil {
		return "نامشخص"
	}
	return err.Error()
}

func derefInt(p *int) int {
	if p == nil {
		return 0
	}
	return *p
}

func intPtrStr(p *int) string {
	if p == nil {
		return ""
	}
	return fmt.Sprintf("%d", *p)
}

func yesNo(b bool) string {
	if b {
		return "دارد"
	}
	return "ندارد"
}

func orDash(s string) string {
	if s == "" {
		return "—"
	}
	return s
}

func trimFloat(f float64) string {
	if f == float64(int64(f)) {
		return fmt.Sprintf("%d", int64(f))
	}
	return fmt.Sprintf("%.4f", f)
}

func joinShort(arr []string, n int) string {
	if len(arr) == 0 {
		return "—"
	}
	out := ""
	for i, s := range arr {
		if i == n {
			out += fmt.Sprintf(" و %d مورد دیگر", len(arr)-n)
			break
		}
		if i > 0 {
			out += "، "
		}
		out += s
	}
	return out
}
