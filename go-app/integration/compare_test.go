package integration

import (
	"reflect"
	"testing"
	"time"
)

func specScores() CompareSpec {
	return CompareSpec{
		KeyField:        "legacy_company_id",
		AllowLegacyOnly: true,
		Fields: []FieldSpec{
			{Name: "symbol", Kind: KindText, Identity: true},
			{Name: "quant_score", Kind: KindNumber, ExpectedSemanticChange: true, Tolerance: 1e-4},
		},
	}
}

func TestCompareRecordsExactMatch(t *testing.T) {
	legacy := []Record{{"legacy_company_id": TextValue("abc"), "symbol": TextValue("فولاد"), "quant_score": NumValue(10)}}
	canon := []Record{{"legacy_company_id": TextValue("abc"), "symbol": TextValue("فولاد"), "quant_score": NumValue(10)}}
	res := CompareRecords("ep", legacy, canon, specScores())
	if res.Classifications[ClassExactMatch] != 2 {
		t.Fatalf("want 2 exact matches, got %v", res.Classifications)
	}
	if res.Unexpected != 0 || res.Errors != 0 {
		t.Fatalf("expected clean result, got unexpected=%d errors=%d", res.Unexpected, res.Errors)
	}
}

func TestCompareRecordsNumericMismatch(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber, Tolerance: 1e-6}}}
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(10)}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(11)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassNameNumericMismatch] != 1 {
		t.Fatalf("want numeric mismatch, got %v", res.Classifications)
	}
	if res.Unexpected != 1 {
		t.Fatalf("want 1 unexpected, got %d", res.Unexpected)
	}
}

func TestCompareRecordsUnitPresentation(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{
		{Name: "v", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true, Tolerance: 1e-6},
	}}
	// legacy million-IRR 1, canonical IRR 1,000,000 -> expected unit difference
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1)}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(1_000_000)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassExpectedUnit] != 1 {
		t.Fatalf("want expected unit presentation, got %v", res.Classifications)
	}
	if res.Unexpected != 0 {
		t.Fatalf("unit presentation must be expected, got unexpected=%d", res.Unexpected)
	}
}

func TestCompareRecordsNullSemantics(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber}}}
	legacy := []Record{{"k": TextValue("a"), "v": NullValue()}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(0)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassNameNullSemantics] != 1 {
		t.Fatalf("want null semantics difference, got %v", res.Classifications)
	}
	// both null -> exact
	both := CompareRecords("ep",
		[]Record{{"k": TextValue("a"), "v": NullValue()}},
		[]Record{{"k": TextValue("a"), "v": NullValue()}}, spec)
	if both.Classifications[ClassExactMatch] != 1 {
		t.Fatalf("both null should match, got %v", both.Classifications)
	}
}

func TestCompareRecordsIdentityMismatch(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "sym", Kind: KindText, Identity: true}}}
	legacy := []Record{{"k": TextValue("a"), "sym": TextValue("فولاد")}}
	canon := []Record{{"k": TextValue("a"), "sym": TextValue("فولاد2")}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassNameIdentityMismatch] != 1 {
		t.Fatalf("want identity mismatch, got %v", res.Classifications)
	}
}

func TestCompareRecordsExpectedSemanticChange(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber, ExpectedSemanticChange: true}}}
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1)}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(2)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassExpectedSemantic] != 1 {
		t.Fatalf("want expected semantic change, got %v", res.Classifications)
	}
	if res.Unexpected != 0 {
		t.Fatalf("expected semantic change must not be unexpected, got %d", res.Unexpected)
	}
}

func TestCompareRecordsMissingRows(t *testing.T) {
	spec := CompareSpec{KeyField: "k", AllowLegacyOnly: true, AllowCanonOnly: false,
		Fields: []FieldSpec{{Name: "v", Kind: KindNumber}}}
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1)}, {"k": TextValue("b"), "v": NumValue(2)}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(1)}, {"k": TextValue("c"), "v": NumValue(3)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassLegacyOnly] != 1 {
		t.Fatalf("want 1 legacy-only, got %v", res.Classifications)
	}
	if res.Classifications[ClassCanonicalOnly] != 1 {
		t.Fatalf("want 1 canonical-only, got %v", res.Classifications)
	}
	// legacy-only allowed => expected, canonical-only not allowed => unexpected
	if res.ExpectedDiffs != 1 || res.Unexpected != 1 {
		t.Fatalf("want expected=1 unexpected=1, got expected=%d unexpected=%d", res.ExpectedDiffs, res.Unexpected)
	}
}

func TestCompareRecordsOrderOnlyNoFalseMismatch(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber}}}
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1)}, {"k": TextValue("b"), "v": NumValue(2)}}
	canon := []Record{{"k": TextValue("b"), "v": NumValue(2)}, {"k": TextValue("a"), "v": NumValue(1)}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Unexpected != 0 {
		t.Fatalf("reordering must not cause unexpected diffs, got %d (%v)", res.Unexpected, res.Classifications)
	}
	if res.Classifications[ClassOrderOnly] != 1 {
		t.Fatalf("want order-only classification, got %v", res.Classifications)
	}
	if res.Classifications[ClassExactMatch] != 2 {
		t.Fatalf("want 2 exact matches, got %v", res.Classifications)
	}
}

func TestCompareRecordsDeterministic(t *testing.T) {
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1)}, {"k": TextValue("b"), "v": NumValue(2)}}
	canon := []Record{{"k": TextValue("b"), "v": NumValue(3)}, {"k": TextValue("a"), "v": NumValue(1)}}
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber}}}
	a := CompareRecords("ep", legacy, canon, spec)
	b := CompareRecords("ep", legacy, canon, spec)
	if !reflect.DeepEqual(a.Diffs, b.Diffs) || !reflect.DeepEqual(a.Classifications, b.Classifications) {
		t.Fatalf("comparison must be deterministic:\n%v\n%v", a, b)
	}
}

func TestNormalizeTextAndDate(t *testing.T) {
	if got := NormalizeText("  زگلدشت   کشت "); got != "زگلدشت کشت" {
		t.Fatalf("normalize text: %q", got)
	}
	if got := NormalizeText("۱۲۳"); got != "123" {
		t.Fatalf("persian digits: %q", got)
	}
	if got := NormalizeDate("2026-09-24T12:00:00Z"); got != "2026-09-24" {
		t.Fatalf("normalize date: %q", got)
	}
}

func TestRatioIsMillionNotHidingSemantics(t *testing.T) {
	// A genuine small difference must never be treated as a unit swap.
	legacy := []Record{{"k": TextValue("a"), "v": NumValue(1000)}}
	canon := []Record{{"k": TextValue("a"), "v": NumValue(1100)}}
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{
		{Name: "v", Kind: KindNumber, Money: true, ExpectedUnitPresentation: true},
	}}
	res := CompareRecords("ep", legacy, canon, spec)
	if res.Classifications[ClassExpectedUnit] != 0 {
		t.Fatalf("10%% difference must not be classified as unit presentation: %v", res.Classifications)
	}
	if res.Classifications[ClassNameNumericMismatch] != 1 {
		t.Fatalf("want numeric mismatch, got %v", res.Classifications)
	}
}

func TestLatencyFieldsCarried(t *testing.T) {
	spec := CompareSpec{KeyField: "k", Fields: []FieldSpec{{Name: "v", Kind: KindNumber}}}
	res := CompareRecords("ep", []Record{{"k": TextValue("a"), "v": NumValue(1)}},
		[]Record{{"k": TextValue("a"), "v": NumValue(1)}}, spec)
	// CompareRecords is pure; latency is added by the orchestrator.
	if res.LatencyTotal != time.Duration(0) {
		t.Fatalf("CompareRecords must not set latency")
	}
}
