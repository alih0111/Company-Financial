package handlers

import "testing"

func TestOverallHealth(t *testing.T) {
	for _, tc := range []struct{ connectivity, analytics, want string }{
		{"HEALTHY", "HEALTHY", "HEALTHY"},
		{"HEALTHY", "STALE", "DEGRADED"},
		{"HEALTHY", "NO_COMPLETED_RUN", "DEGRADED"},
		{"DEGRADED", "HEALTHY", "DEGRADED"},
		{"UNHEALTHY", "STALE", "UNHEALTHY"},
	} {
		if got := overallHealth(tc.connectivity, tc.analytics); got != tc.want {
			t.Errorf("overallHealth(%q, %q) = %q, want %q", tc.connectivity, tc.analytics, got, tc.want)
		}
	}
}
