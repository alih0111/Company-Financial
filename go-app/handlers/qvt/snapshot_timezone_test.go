package qvt

import "testing"

func TestSnapshotTimezoneAtTehranMidnight(t *testing.T) {
	b := &qvtBundle{
		Q: map[string]any{"as_of": "2026-10-12T22:45:00+00:00", "as_of_timezone": "Asia/Tehran"},
		V: map[string]any{"as_of": "2026-10-13", "cutoff": "2026-10-12T22:45:00+00:00", "as_of_timezone": "Asia/Tehran"},
		T: map[string]any{"as_of": "2026-10-13", "cutoff": "2026-10-12T22:45:00+00:00", "as_of_timezone": "Asia/Tehran"},
	}
	if _, _, problems := qvtCheckConsistency(b); len(problems) != 0 {
		t.Fatalf("explicit Tehran day should match cutoff: %v", problems)
	}
	delete(b.T, "as_of_timezone")
	if _, _, problems := qvtCheckConsistency(b); len(problems) == 0 {
		t.Fatal("mismatched timezone declarations must be rejected")
	}
	delete(b.Q, "as_of_timezone")
	delete(b.V, "as_of_timezone")
	b.V["as_of"], b.T["as_of"] = "2026-10-12", "2026-10-12"
	if _, _, problems := qvtCheckConsistency(b); len(problems) != 0 {
		t.Fatalf("legacy UTC date contract must remain valid: %v", problems)
	}
}
