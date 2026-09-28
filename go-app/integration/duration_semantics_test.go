package integration

import "testing"

// Duration must come from the report title, never from the calendar month.
// These non-Esfand cases have month != duration, which the old month-based
// inference got wrong.
func TestFiscalYearDurationFromTitle(t *testing.T) {
	cases := []struct {
		title   string
		wantFY  int
		wantDur int
		note    string
	}{
		{"اطلاعات و صورت‌های مالی میاندوره‌ای  دوره ۳ ماهه منتهی به  ۱۴۰۵/۰۳/۳۱ (حسابرسی نشده)", 1405, 3, "esfand Q1"},
		{"صورت‌های مالی  سال مالی منتهی به ۱۴۰۴/۱۲/۲۹ (حسابرسی شده)", 1404, 12, "esfand FY"},
		{"دوره ۶ ماهه منتهی به ۱۴۰۴/۱۲/۲۹", 1404, 6, "non-esfand 6M ends month 12 (month-based would say 12)"},
		{"دوره ۹ ماهه منتهی به ۱۴۰۵/۰۳/۳۱", 1405, 9, "non-esfand 9M ends month 3 (month-based would say 3)"},
		{"دوره ۳ ماهه منتهی به ۱۴۰۴/۰۹/۳۰", 1404, 3, "non-esfand 3M ends month 9"},
		{"", 0, 0, "empty"},
	}
	for _, c := range cases {
		fy, dur := fiscalYearDurationFromTitle(c.title)
		if fy != c.wantFY || dur != c.wantDur {
			t.Fatalf("%s: title=%q got (%d,%d) want (%d,%d)", c.note, c.title, fy, dur, c.wantFY, c.wantDur)
		}
	}
}
