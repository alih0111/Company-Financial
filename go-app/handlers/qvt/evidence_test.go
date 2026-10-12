package qvt

// تست‌های زنجیره شواهد (گام ۲-ی-۱) — همگی بدون دیتابیس: منطق خالص وضعیت‌ها
// با fixture آزمون می‌شود و مسیرهای DB-دار فقط تخریب محترمانه‌شان پوشش
// داده می‌شود (qvt هرگز config را import نمی‌کند تا go test به DSN وابسته
// نباشد). اعتبارسنجی زنده DB در اوراکل مستقل پایتون انجام می‌شود.

import (
	"database/sql"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func TestEvWorstOrdering(t *testing.T) {
	cases := []struct {
		in   []string
		want string
	}{
		{[]string{evVerified, evVerified}, evVerified},
		{[]string{evVerified, evPartial}, evPartial},
		{[]string{evPartial, evUnverified}, evUnverified},
		{[]string{evUnverified, evConflicting}, evConflicting},
		{[]string{evVerified, evConflicting, evPartial}, evConflicting},
	}
	for _, c := range cases {
		if got := evWorst(c.in); got != c.want {
			t.Fatalf("evWorst(%v) = %q، انتظار %q", c.in, got, c.want)
		}
	}
}

// mkSeries یک سری صعودی روزانه می‌سازد که n روز قبل از asOf تمام می‌شود.
func mkSeries(n int, end time.Time, closeAt func(i, n int) float64) []tDailyRow {
	out := make([]tDailyRow, 0, n)
	for i := 0; i < n; i++ {
		d := end.AddDate(0, 0, -(n - 1 - i))
		out = append(out, tDailyRow{
			TradeDate: d.Format("2006-01-02"),
			Close:     sql.NullFloat64{Valid: true, Float64: closeAt(i, n)},
			TV:        sql.NullFloat64{Valid: true, Float64: 1e9},
			Series:    sql.NullString{Valid: true, String: "adjusted"},
			Adjusted:  sql.NullBool{Valid: true, Bool: true},
			Method:    sql.NullString{Valid: true, String: "vendor_adjusted"},
		})
	}
	return out
}

func TestTComputeStatsHealthy(t *testing.T) {
	asOf := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	end := asOf.AddDate(0, 0, -2)
	rows := mkSeries(200, end, func(i, n int) float64 { return 1000 + float64((i*7)%40) })
	st := tComputeStats(rows, asOf)
	if st.NSessions != 200 || st.NValidCloses != 200 {
		t.Fatalf("sessions/valid = %d/%d، انتظار 200/200", st.NSessions, st.NValidCloses)
	}
	if st.LastValidAge == nil || *st.LastValidAge != 2 {
		t.Fatalf("age = %v، انتظار 2", st.LastValidAge)
	}
	if !st.MomentumBase6m || !st.MomentumBase3m {
		t.Fatal("پایه momentum ۶/۳ ماهه باید موجود باشد")
	}
	if st.LiqSpanDays == nil || *st.LiqSpanDays != 29 {
		t.Fatalf("liq span = %v، انتظار 29", st.LiqSpanDays)
	}
	if st.VolNReturns == nil || *st.VolNReturns != 30 {
		t.Fatalf("vol returns = %v، انتظار 30", st.VolNReturns)
	}
	if st.NJumpReturns != 0 {
		t.Fatalf("jumps = %d، انتظار 0", st.NJumpReturns)
	}
	if st.AdjustedFalse != 0 || strings.Join(st.SeriesValues, ",") != "adjusted" {
		t.Fatalf("adjustment flags ناسازگار: %v %v", st.AdjustedFalse, st.SeriesValues)
	}
	if !tWindowsPrereqOK(st) {
		t.Fatal("پیش‌نیاز پنجره‌ها باید برقرار باشد")
	}
}

func TestTComputeStatsJumpAndStale(t *testing.T) {
	asOf := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	// پرش +۵۰٪ در آخرین بسته
	rows := mkSeries(60, asOf.AddDate(0, 0, -1), func(i, n int) float64 {
		if i == n-1 {
			return 1500
		}
		return 1000
	})
	st := tComputeStats(rows, asOf)
	if st.NJumpReturns != 1 || len(st.JumpDates) == 0 {
		t.Fatalf("jump detection شکست خورد: %d %v", st.NJumpReturns, st.JumpDates)
	}
	// آخرین بسته معتبر ۲۵ روز قبل از as_of → فراتر از STALE_DAYS=14
	rows2 := mkSeries(60, asOf.AddDate(0, 0, -25), func(i, n int) float64 { return 1000 })
	st2 := tComputeStats(rows2, asOf)
	if st2.LastValidAge == nil || *st2.LastValidAge != 25 {
		t.Fatalf("stale age = %v، انتظار 25", st2.LastValidAge)
	}
	if tWindowsPrereqOK(st2) {
		t.Fatal("با stale شدن، پیش‌نیاز پنجره‌ها باید رد شود")
	}
	// بسته زیر کف PRICE_FLOOR=100 معتبر نیست
	rows3 := mkSeries(60, asOf.AddDate(0, 0, -1), func(i, n int) float64 { return 50 })
	st3 := tComputeStats(rows3, asOf)
	if st3.NValidCloses != 0 || st3.LastValidAge != nil {
		t.Fatal("بسته زیر کف باید نامعتبر باشد")
	}
}

func TestTComputeStatsAdjustmentConflictInput(t *testing.T) {
	asOf := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	rows := mkSeries(40, asOf.AddDate(0, 0, -1), func(i, n int) float64 { return 1000 })
	rows[5].Adjusted = sql.NullBool{Valid: true, Bool: false}
	rows[7].Series = sql.NullString{Valid: true, String: "unadjusted"}
	st := tComputeStats(rows, asOf)
	if st.AdjustedFalse != 1 {
		t.Fatalf("AdjustedFalse = %d، انتظار 1", st.AdjustedFalse)
	}
	if !containsNonAdjusted(st.SeriesValues) {
		t.Fatal("سری unadjusted باید آشکار شود")
	}
}

func TestSharesItemDecide(t *testing.T) {
	cutoff := time.Date(2026, 10, 8, 23, 59, 0, 0, time.UTC)
	pxSame := &priceCheck{RowFound: true, LastTradeDate: "2026-10-05"}
	pxLater := &priceCheck{RowFound: true, LastTradeDate: "2026-10-08"}
	validFactor := func() map[string]any {
		return map[string]any{"factors": map[string]any{
			"pe": map[string]any{"raw_status": "valid", "included": true},
		}}
	}

	// TSETMC هم‌تاریخ قیمت → verified
	it := evItem("v_shares_input", "شمارش سهام", evUnverified)
	sr := &sharesRow{
		TsetmcShares:  sql.NullFloat64{Valid: true, Float64: 1.2e9},
		TsetmcCollect: sql.NullString{Valid: true, String: "2026-10-05T10:00:00Z"},
		TsetmcSource:  sql.NullString{Valid: true, String: "TSETMC_ZTITAD_CURRENT"},
	}
	it = sharesItemDecide(it, sr, pxSame, validFactor(), cutoff, nil)
	if it.Status != evVerified {
		t.Fatalf("TSETMC هم‌تاریخ باید verified باشد، got %s (%v)", it.Status, it.Limitations)
	}

	// TSETMC سه روز قدیمی‌تر از قیمت → partial با محدودیت صریح
	it2 := sharesItemDecide(evItem("k", "l", evUnverified), sr, pxLater, validFactor(), cutoff, nil)
	if it2.Status != evPartial {
		t.Fatalf("گپ مثبت باید partial بدهد، got %s", it2.Status)
	}
	found := false
	for _, l := range it2.Limitations {
		if strings.Contains(l, "share_snapshot_older_than_price") {
			found = true
		}
	}
	if !found {
		t.Fatal("محدودیت سازگاری سهام↔قیمت باید به نام هشدار موتور ذکر شود")
	}

	// FALLBACK BRS → partial؛ جمع‌آوری بعد از cutoff → unverified
	brs := &sharesRow{
		BrsShares:  sql.NullFloat64{Valid: true, Float64: 1.2e9},
		BrsAsOf:    sql.NullString{Valid: true, String: "2026-09-29"},
		BrsCollect: sql.NullString{Valid: true, String: "2026-09-29T12:00:00Z"},
	}
	it3 := sharesItemDecide(evItem("k", "l", evUnverified), brs, pxSame, validFactor(), cutoff, nil)
	if it3.Status != evPartial {
		t.Fatalf("BRS باید partial بدهد، got %s", it3.Status)
	}
	brsLate := &sharesRow{
		BrsShares:  sql.NullFloat64{Valid: true, Float64: 1.2e9},
		BrsAsOf:    sql.NullString{Valid: true, String: "2026-10-09"},
		BrsCollect: sql.NullString{Valid: true, String: "2026-10-09T12:00:00Z"},
	}
	it4 := sharesItemDecide(evItem("k", "l", evUnverified), brsLate, pxSame, validFactor(), cutoff, nil)
	if it4.Status != evUnverified {
		t.Fatalf("BRS بعد از cutoff باید unverified بدهد، got %s", it4.Status)
	}

	// هیچ snapshot + فاکتور valid آرتیفکت → conflicting
	it5 := sharesItemDecide(evItem("k", "l", evUnverified), &sharesRow{}, pxSame, validFactor(), cutoff, nil)
	if it5.Status != evConflicting || len(it5.Conflicts) == 0 {
		t.Fatal("نبود snapshot همراه فاکتور valid باید conflicting بدهد")
	}
	// هیچ snapshot + فاکتور ناموجود → unverified (هم‌خوان با refusal موتور)
	it6 := sharesItemDecide(evItem("k", "l", evUnverified), &sharesRow{}, pxSame, map[string]any{"factors": map[string]any{}}, cutoff, nil)
	if it6.Status != evUnverified {
		t.Fatalf("نبود snapshot بدون فاکتور باید unverified بدهد، got %s", it6.Status)
	}
}

func TestTWindowConflicts(t *testing.T) {
	tcmValid := func(fid string) map[string]any {
		return map[string]any{"factors": map[string]any{
			fid: map[string]any{"raw_status": "valid", "included": true},
		}}
	}
	asOf := time.Date(2026, 10, 8, 0, 0, 0, 0, time.UTC)
	good := tComputeStats(mkSeries(200, asOf.AddDate(0, 0, -2), func(i, n int) float64 { return 1000 }), asOf)

	// هم‌خوان: همه فاکتورهای valid با پیش‌نیاز برقرار → بدون تعارض
	if got := tWindowConflicts(tcmValid("liquidity"), good); len(got) != 0 {
		t.Fatalf("پنجره سالم نباید تعارض بدهد: %v", got)
	}
	// تعارض: آرتیفکت momentum_6m را valid کرده اما پایه ۶ماهه وجود ندارد
	stale := tComputeStats(mkSeries(20, asOf.AddDate(0, 0, -2), func(i, n int) float64 { return 1000 }), asOf)
	if !stale.MomentumBase6m {
		// سری ۲۰ روزه پایه ۶ماهه ندارد
		if got := tWindowConflicts(tcmValid("momentum_6m_rel"), stale); len(got) == 0 {
			t.Fatal("momentum valid بدون پایه ۶ماهه باید تعارض بدهد")
		}
	} else {
		t.Fatal("سری ۲۰ روزه نباید پایه ۶ماهه داشته باشد")
	}
	// فاکتورِ included=false → هرگز تعارض نمی‌شمارد (دلیل حذف کار آرتیفکت است)
	tcmExcluded := map[string]any{"factors": map[string]any{
		"momentum_6m_rel": map[string]any{"raw_status": "no_history", "included": false},
	}}
	if got := tWindowConflicts(tcmExcluded, stale); len(got) != 0 {
		t.Fatalf("فاکتور حذف‌شده نباید تعارض بدهد: %v", got)
	}
}

func mkFixtureBundle() *qvtBundle {
	return &qvtBundle{
		qPath: "out/v2_q_observed_report.json", vPath: "out/v2_value_pilot.json", t: "out/v2_t_pilot.json",
		qSHA: "aa", vSHA: "bb", tSHA: "cc",
		qSize: 1, vSize: 2, tSize: 3,
		loadStable: true,
		Q: map[string]any{
			"as_of":   "2026-10-08 23:59:00+00:00",
			"summary": map[string]any{"n_pilot_eligible": 98.0},
		},
		V: map[string]any{
			"as_of":            "2026-10-08",
			"coverage_summary": map[string]any{"n_v_pilot_eligible": 95.0},
			"q_axis_artifact": map[string]any{
				"path":  `D:\x\output\v2_q_observed_report.json`,
				"as_of": "2026-10-08 23:59:00+00:00", "n_pilot_eligible": 98.0,
			},
		},
		T: map[string]any{
			"as_of": "2026-10-08",
			"q_axis_artifact": map[string]any{
				"path":  "output/v2_q_observed_report.json",
				"as_of": "2026-10-08 23:59:00+00:00", "n_pilot_eligible": 98.0,
			},
			"v_axis_artifact": map[string]any{
				"path":  "output/v2_value_pilot.json",
				"as_of": "2026-10-08", "n_pilot_eligible": 95.0,
			},
		},
	}
}

func TestBundleIntegrityChainLinkage(t *testing.T) {
	b := mkFixtureBundle()
	integ := bundleIntegrityOf(b)
	cl, _ := integ["chain_linkage"].(gin.H)
	if cl == nil {
		t.Fatal("chain_linkage باید موجود باشد")
	}
	for _, k := range []string{"q_to_v", "q_to_t", "v_to_t"} {
		l, _ := cl[k].(linkCheck)
		if linkStatus(l) != evVerified {
			t.Fatalf("پیوند %s باید verified باشد، got %v", k, l)
		}
	}
	files, _ := integ["artifact_files"].(gin.H)
	if files["q"].(gin.H)["sha256"] != "aa" {
		t.Fatal("sha256 فایل‌ها باید منتشر شود")
	}
	// تعارض: n_pilot_eligible پوینتر با آرتیفکت یکی نیست
	b2 := mkFixtureBundle()
	b2.V["q_axis_artifact"].(map[string]any)["n_pilot_eligible"] = 90.0
	cl2 := bundleIntegrityOf(b2)["chain_linkage"].(gin.H)
	if linkStatus(cl2["q_to_v"].(linkCheck)) != evConflicting {
		t.Fatal("پوینتر ناسازگار باید conflicting بدهد")
	}
	// نبود پوینتر → unverified
	b3 := mkFixtureBundle()
	delete(b3.T, "v_axis_artifact")
	cl3 := bundleIntegrityOf(b3)["chain_linkage"].(gin.H)
	if linkStatus(cl3["v_to_t"].(linkCheck)) != evUnverified {
		t.Fatal("نبود پوینتر باید unverified بدهد")
	}
	if integ["load_verified_stable"] != true {
		t.Fatal("load_verified_stable باید منتشر شود")
	}
}

func TestEvidenceChainDegradeWithoutDB(t *testing.T) {
	b := mkFixtureBundle()
	ax := func() map[string]any {
		return map[string]any{"factors": map[string]any{}}
	}
	chain := evidenceChainForDB("cid-1", ax(), ax(), ax(), b, nil, nil, errPriceNoDSN)
	if len(chain.Axes) != 3 {
		t.Fatalf("سه محور لازم است، got %d", len(chain.Axes))
	}
	for _, ax := range chain.Axes {
		for _, it := range ax.Items {
			if it.Key == "q_raw_values_publication" {
				continue // یافته ساختاری خود آرتیفکت است — به DB وابسته نیست
			}
			if it.Checked {
				t.Fatalf("آیتم %s بدون DB نباید checked=true باشد", it.Key)
			}
			if it.Status != evUnverified {
				t.Fatalf("تخریب محترمانه باید unverified بدهد، got %s برای %s", it.Status, it.Key)
			}
		}
	}
	if chain.Overall != evUnverified {
		t.Fatalf("overall باید unverified باشد، got %s", chain.Overall)
	}
	// محور Q بدون DB: یک آیتم تخریب + یک یافته ساختاری انتشار مقدار خام
	for _, ax := range chain.Axes {
		if ax.Axis == "q" && len(ax.Items) != 2 {
			t.Fatalf("محور Q بدون DB باید دو آیتم داشته باشد (تخریب + ساختاری)، got %d", len(ax.Items))
		}
	}
}

func TestEvidenceChainWithPriceOnly(t *testing.T) {
	b := mkFixtureBundle()
	px := &priceCheck{
		Requested: true, Available: true, RowFound: true,
		LastTradeDate: "2026-10-05", CollectedAt: "2026-10-05T12:00:00Z",
		AgeDays: intPtr(3), PolicyDays: intPtr(7), Violation: boolPtr(false),
		Source: priceCheckSource,
	}
	vcm := map[string]any{"factors": map[string]any{}}
	chain := evidenceChainForDB("cid-1", nil, vcm, nil, b, px, nil, errPriceNoDSN)
	// محور V با vcm موجود: آیتم قیمت با px تأیید می‌شود؛ بقیه آیتم‌های
	// DB-دار تخریب محترمانه می‌شوند
	var vAxis *axisEvidence
	for i := range chain.Axes {
		if chain.Axes[i].Axis == "v" {
			vAxis = &chain.Axes[i]
		}
	}
	if vAxis == nil {
		t.Fatal("محور V باید موجود باشد")
	}
	var priceItem *evidenceItem
	for i := range vAxis.Items {
		if vAxis.Items[i].Key == "v_price_input" {
			priceItem = &vAxis.Items[i]
		}
	}
	if priceItem == nil || priceItem.Status != evVerified {
		t.Fatalf("آیتم قیمت با ردیف تأییدشده باید verified باشد، got %+v", priceItem)
	}
	for i := range vAxis.Items {
		it := &vAxis.Items[i]
		if it.Key != "v_price_input" && (it.Checked || it.Status != evUnverified) {
			t.Fatalf("آیتم DB-دار %s باید تخریب محترمانه باشد", it.Key)
		}
	}
	if chain.Axes[0].Items[0].Key != "q_axis_absent" {
		t.Fatalf("محور Q absent باید آیتم absent بدهد، got %s", chain.Axes[0].Items[0].Key)
	}
}

func TestEvidenceRulesContract(t *testing.T) {
	sc, _ := qvtEvidenceRules["status_contract"].(gin.H)
	for _, s := range []string{evVerified, evPartial, evUnverified, evConflicting} {
		if sc[s] == nil || sc[s] == "" {
			t.Fatalf("وضعیت %s باید در قرارداد منتشر شود", s)
		}
		if evStatusLabels[s] == "" {
			t.Fatalf("برچسب فارسی %s لازم است", s)
		}
	}
	if qvtEvidenceRules["no_score_change"] == nil {
		t.Fatal("قاعده عدم تغییر امتیاز باید منتشر شود")
	}
}

func intPtr(i int) *int    { return &i }
func boolPtr(b bool) *bool { return &b }

func TestSharesItemDecideWithIntervalEvents(t *testing.T) {
	cutoff := time.Date(2026, 10, 8, 23, 59, 0, 0, time.UTC)
	validFactor := func() map[string]any {
		return map[string]any{"factors": map[string]any{
			"pe": map[string]any{"included": true, "raw_status": "valid"}}}
	}
	sr := &sharesRow{TsetmcShares: sql.NullFloat64{Float64: 728789000, Valid: true},
		TsetmcCollect: sql.NullString{String: "2026-10-05T08:00:00+00:00", Valid: true},
		TsetmcSource:  sql.NullString{String: "tsetmc_ztitad", Valid: true}}
	pxLater := &priceCheck{RowFound: true, LastTradeDate: "2026-10-08"}

	// gap>0 + صفر رویداد → partial اما با ممیزی بازه ثبت‌شده
	evZero := &sharesEventSummary{Confirmed: []gin.H{}, Possible: []gin.H{}}
	it := sharesItemDecide(evItem("k", "l", evUnverified), sr, pxLater, validFactor(), cutoff, evZero)
	if it.Status != evPartial {
		t.Fatalf("gap با صفر رویداد باید partial بماند، got %s", it.Status)
	}
	joined := strings.Join(it.Limitations, " ")
	if !strings.Contains(joined, "ممیزی شد") || !strings.Contains(joined, "0 رویداد معتبر") {
		t.Fatalf("ممیزی بازه باید صریح باشد: %v", it.Limitations)
	}

	// gap>0 + رویداد معتبر → conflicting با متن بازبینی ارزندگی
	evConfirmed := &sharesEventSummary{
		Confirmed: []gin.H{{"kind": "corporate_actions", "action_type": "capital_increase", "date": "2026-10-07"}},
		Possible:  []gin.H{}}
	it2 := sharesItemDecide(evItem("k", "l", evUnverified), sr, pxLater, validFactor(), cutoff, evConfirmed)
	if it2.Status != evConflicting {
		t.Fatalf("رویداد معتبر در بازه حساس باید conflicting بدهد، got %s", it2.Status)
	}
	if len(it2.Conflicts) == 0 || !strings.Contains(it2.Conflicts[0], "بازبینی ارزندگی") {
		t.Fatalf("conflict باید بازبینی ارزندگی را بخواهد: %v", it2.Conflicts)
	}

	// gap=0 + رویداد → همان رویداد گزارش می‌شود ولی وضعیت verified می‌ماند
	pxSame := &priceCheck{RowFound: true, LastTradeDate: "2026-10-05"}
	it3 := sharesItemDecide(evItem("k", "l", evUnverified), sr, pxSame, validFactor(), cutoff, evConfirmed)
	if it3.Status != evVerified {
		t.Fatalf("gap=0 با رویداد خارج از بازه نباید downgrade شود، got %s", it3.Status)
	}
}
