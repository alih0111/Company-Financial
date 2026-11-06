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

func TestStalenessDetectsSupersededFinancialDateRetreat(t *testing.T) {
	runWM := `{"v":1,"domains":{"financial":{"date":"2647-12-13","arrival":"2026-11-01T00:00:00Z","rows":100}}}`
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"financial": {Date: "2026-09-22", Arrival: "2026-11-01T00:00:00Z", Rows: rows(100)},
	}}
	stale, reasons := stalenessFromWatermark(runWM, cur)
	if !stale || len(reasons) == 0 {
		t.Fatal("a superseded financial maximum must invalidate the old watermark")
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

func TestUnparseableTimesAreUnknownRatherThanFreshOrProvenStale(t *testing.T) {
	// A malformed arrival cannot prove either freshness or a new arrival.
	runWM := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"garbage","rows":100}}}`
	cur := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "also garbage", Rows: rows(100)},
	}}
	status, reasons := assessWatermark(runWM, cur)
	stale, _ := stalenessFromWatermark(runWM, cur)
	if status != "UNKNOWN" || !stale || len(reasons) == 0 {
		t.Fatalf("unparseable times must be unknown and conservative, status=%s stale=%v reasons=%v", status, stale, reasons)
	}
}

func TestWatermarkAcceptsPostgresHourOnlyTimezone(t *testing.T) {
	previous := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"2026-10-05 15:05:00+00","rows":100}}}`
	current := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "2026-10-05 15:05:00+00", Rows: rows(100)},
	}}
	status, reasons := assessWatermark(previous, current)
	if status != "FRESH" {
		t.Fatalf("valid PostgreSQL UTC timestamps must be accepted, status=%s reasons=%v", status, reasons)
	}
}

func TestWatermarkMissingCountIsUnknown(t *testing.T) {
	previous := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"2026-10-05T15:05:00Z"}}}`
	current := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "2026-10-05T15:05:00Z", Rows: rows(100)},
	}}
	status, reasons := assessWatermark(previous, current)
	if status != "UNKNOWN" || len(reasons) == 0 {
		t.Fatalf("missing row count must be unknown, status=%s reasons=%v", status, reasons)
	}
}

func TestWatermarkMissingCurrentDomainIsUnknown(t *testing.T) {
	previous := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"2026-10-05T15:05:00Z","rows":100}}}`
	status, reasons := assessWatermark(previous, InputWatermark{V: 1, Domains: map[string]WatermarkDomain{}})
	if status != "UNKNOWN" || len(reasons) == 0 {
		t.Fatalf("missing current domain must be unknown, status=%s reasons=%v", status, reasons)
	}
}

func TestWatermarkEmptyDomainAndMixedEvidence(t *testing.T) {
	empty := `{"v":1,"domains":{"monthly":{"date":"","arrival":"","rows":0}}}`
	zero := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Rows: rows(0)},
	}}
	if status, reasons := assessWatermark(empty, zero); status != "FRESH" {
		t.Fatalf("unchanged empty domain should be comparable, status=%s reasons=%v", status, reasons)
	}
	previous := `{"v":1,"domains":{"monthly":{"date":"2026-09-22","arrival":"bad","rows":100}}}`
	current := InputWatermark{V: 1, Domains: map[string]WatermarkDomain{
		"monthly": {Date: "2026-09-22", Arrival: "bad", Rows: rows(101)},
	}}
	if status, reasons := assessWatermark(previous, current); status != "STALE" || len(reasons) < 2 {
		t.Fatalf("proven row change and unknown arrival must both be reported, status=%s reasons=%v", status, reasons)
	}
}
