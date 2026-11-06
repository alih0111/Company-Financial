package handlers

import "testing"

func TestOverallHealth(t *testing.T) {
	for _, tc := range []struct{ connectivity, analytics, want string }{
		{"HEALTHY", "HEALTHY", "HEALTHY"},
		{"HEALTHY", "STALE", "DEGRADED"},
		{"HEALTHY", "UNKNOWN", "DEGRADED"},
		{"HEALTHY", "NO_COMPLETED_RUN", "DEGRADED"},
		{"DEGRADED", "HEALTHY", "DEGRADED"},
		{"UNHEALTHY", "STALE", "UNHEALTHY"},
	} {
		if got := overallHealth(tc.connectivity, tc.analytics); got != tc.want {
			t.Errorf("overallHealth(%q, %q) = %q, want %q", tc.connectivity, tc.analytics, got, tc.want)
		}
	}
}

func TestAnalyticsStatusDistinguishesUnknownFromStale(t *testing.T) {
	if got := analyticsStatus("run", true, "UNKNOWN"); got != "UNKNOWN" {
		t.Fatalf("unknown freshness reported as %s", got)
	}
	if got := analyticsStatus("run", true, "STALE"); got != "STALE" {
		t.Fatalf("stale freshness reported as %s", got)
	}
	if got := analyticsStatus("run", false, "FRESH"); got != "HEALTHY" {
		t.Fatalf("fresh score reported as %s", got)
	}
}
