package integration

import "testing"

// With SQL Server declared offline_expected, no route may resolve to LEGACY,
// even for a legacy global mode or an unsafe/unknown identity. This is the
// invariant that prevents accidental localhost:1433 attempts from the website.
func TestOfflineExpectedForcesCanonicalMode(t *testing.T) {
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	cfg := Config{Mode: ModeLegacy, EndpointModes: map[string]ReadMode{}}
	if got := cfg.ModeFor(EndpointCompanyNames); got != ModeCanonical {
		t.Fatalf("offline_expected must force canonical, got %s", got)
	}
	if got := cfg.ModeFor(EndpointPriceHistory); got != ModeCanonical {
		t.Fatalf("offline_expected must force canonical for price-history, got %s", got)
	}
	if !cfg.AnyShadow() {
		t.Fatal("offline_expected must enable the canonical source")
	}
}

func TestOfflineExpectedRoutesNeverLegacy(t *testing.T) {
	t.Setenv("CDF_SQLSERVER_MODE", "offline_expected")
	sh := newShadowForTest(Config{Mode: ModeLegacy, EndpointModes: map[string]ReadMode{}}, &fakeSource{})
	if got := sh.SalesData2Route("__unsafe__"); got != RouteCanary {
		t.Fatalf("SalesData2Route offline must be canonical, got %v", got)
	}
	if got := sh.SalesDataRoute("__unsafe__"); got != RouteCanary {
		t.Fatalf("SalesDataRoute offline must be canonical, got %v", got)
	}
	if got := sh.CompanyScoresRoute("__unsafe__"); got != RouteCanary {
		t.Fatalf("CompanyScoresRoute offline must be canonical, got %v", got)
	}
	if got := sh.CompanyNamesRoute(); got != RouteCanary {
		t.Fatalf("CompanyNamesRoute offline must be canonical, got %v", got)
	}
	if got := sh.SummaryRoute(); got != RouteCanary {
		t.Fatalf("SummaryRoute offline must be canonical, got %v", got)
	}
	if got := sh.AllCompanyScoresRoute(); got != RouteCanary {
		t.Fatalf("AllCompanyScoresRoute offline must be canonical, got %v", got)
	}
	if got := sh.PriceHistoryRoute("__unsafe__"); got != RouteCanary {
		t.Fatalf("PriceHistoryRoute offline must be canonical, got %v", got)
	}
}
