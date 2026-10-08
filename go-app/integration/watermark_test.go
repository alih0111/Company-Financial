package integration

import "testing"

func rows(n int64) *int64 { return &n }

func TestStalenessRequiresWatermark(t *testing.T) {
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "2026-10-05 18:35:00+03:30", Rows: rows(100)},
	}}
	for _, runWM := range []string{"", "{}", `{"v":1,"domains":{}}`} {
		stale, reasons := stalenessFromWatermark(runWM, cur)
		if !stale {
			t.Fatalf("run watermark %q must read stale, got fresh", runWM)
		}
		if len(reasons) == 0 {
			t.Fatalf("run watermark %q must explain staleness", runWM)
		}
	}
}

func TestStalenessFreshWhenFingerprintMatches(t *testing.T) {
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "2026-10-05 18:35:00+03:30", Rows: rows(100)},
	}}
	runWM := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"2026-10-05 18:35:00+03:30","rows":100,"digest":"x"}}}`
	stale, reasons := stalenessFromWatermark(runWM, cur)
	if stale {
		t.Fatalf("identical fingerprint must be fresh, reasons=%v", reasons)
	}
}

func TestStalenessDetectsBackfilledOlderPeriod(t *testing.T) {
	// The data date did NOT advance past the run's as_of; only the row count and
	// arrival moved. The old date rule could not see this.
	runWM := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"2026-10-05 18:35:00+03:30","rows":100,"digest":"x"}}}`
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "2026-10-08 17:50:00+03:30", Rows: rows(103)},
	}}
	stale, reasons := stalenessFromWatermark(runWM, cur)
	if !stale {
		t.Fatal("a backfilled older period must read stale")
	}
	if len(reasons) < 2 {
		t.Fatalf("expected rows + arrival reasons, got %v", reasons)
	}
}

func TestStalenessIgnoresUnparseableTimes(t *testing.T) {
	// A parse failure must never fabricate staleness when counts and dates match.
	runWM := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"garbage","rows":100}}}`
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "also garbage", Rows: rows(100)},
	}}
	stale, reasons := stalenessFromWatermark(runWM, cur)
	if stale {
		t.Fatalf("unparseable times with equal counts/dates must be fresh, reasons=%v", reasons)
	}
}
