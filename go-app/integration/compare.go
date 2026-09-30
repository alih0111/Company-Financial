package integration

import (
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
	"unicode"
)

// ValueKind identifies the semantic type of a compared value.
type ValueKind int

const (
	KindNull ValueKind = iota
	KindNumber
	KindText
	KindBool
	KindDate
)

// Value is a normalized comparison value. It distinguishes NULL from zero/empty
// so that NULL semantics can be classified explicitly.
type Value struct {
	Kind ValueKind
	Num  float64
	Text string
	Bool bool
}

// NumValue builds a numeric value.
func NumValue(f float64) Value { return Value{Kind: KindNumber, Num: f} }

// TextValue builds a text value (already expected to be normalized).
func TextValue(s string) Value { return Value{Kind: KindText, Text: NormalizeText(s)} }

// BoolValue builds a boolean value.
func BoolValue(b bool) Value { return Value{Kind: KindBool, Bool: b} }

// DateValue builds a date value from a canonical YYYY-MM-DD string.
func DateValue(s string) Value { return Value{Kind: KindDate, Text: NormalizeDate(s)} }

// NullValue builds a NULL value.
func NullValue() Value { return Value{Kind: KindNull} }

// String renders a value for diagnostics without leaking anything sensitive.
func (v Value) String() string {
	switch v.Kind {
	case KindNumber:
		return trimFloat(v.Num)
	case KindText:
		return v.Text
	case KindBool:
		if v.Bool {
			return "true"
		}
		return "false"
	case KindDate:
		return v.Text
	default:
		return "<null>"
	}
}

// ASCIIString renders a value with non-ASCII characters escaped so that CSV and
// log output remains stable across terminals.
func (v Value) ASCIIString() string {
	return asciiSafe(v.String())
}

// Record is a normalized row keyed by field name.
type Record map[string]Value

// FieldSpec describes how one field participates in comparison.
type FieldSpec struct {
	Name                     string
	Kind                     ValueKind
	Money                    bool
	Tolerance                float64
	ExpectedSemanticChange   bool
	ExpectedUnitPresentation bool
	Identity                 bool
}

// CompareSpec describes how two record sets are compared.
type CompareSpec struct {
	KeyField        string
	Fields          []FieldSpec
	AllowLegacyOnly bool
	AllowCanonOnly  bool
	// MaxMissingDetail caps how many per-key missing rows are recorded.
	MaxMissingDetail int
}

// Difference classifications. Every mismatch must be classified; none may
// silently disappear.
const (
	ClassExactMatch           = "EXACT_MATCH"
	ClassExpectedUnit         = "EXPECTED_UNIT_PRESENTATION"
	ClassExpectedSemantic     = "EXPECTED_CANONICAL_SEMANTIC_CHANGE"
	ClassLegacyOnly           = "LEGACY_ONLY"
	ClassCanonicalOnly        = "CANONICAL_ONLY"
	ClassNameNullSemantics    = "NULL_SEMANTICS_DIFFERENCE"
	ClassOrderOnly            = "ORDER_ONLY_DIFFERENCE"
	ClassNameNumericMismatch  = "NUMERIC_MISMATCH"
	ClassNameIdentityMismatch = "IDENTITY_MISMATCH"
	ClassQueryError           = "QUERY_ERROR"
	ClassNameUnclassified     = "UNCLASSIFIED_MISMATCH"
)

// DiffRecord is a single classified difference.
type DiffRecord struct {
	Endpoint  string
	Key       string
	Field     string
	Class     string
	Legacy    string
	Canonical string
	Detail    string
}

// EndpointResult aggregates a single shadow comparison.
type EndpointResult struct {
	Endpoint        string
	KeyField        string
	LegacyRows      int
	CanonicalRows   int
	Matched         int
	ExpectedDiffs   int
	Unexpected      int
	Errors          int
	OrderChanged    bool
	Classifications map[string]int
	Diffs           []DiffRecord
	CanonicalErr    error

	LatencyLegacy    time.Duration
	LatencyCanonical time.Duration
	LatencyTotal     time.Duration

	specValue CompareSpec
}

// IsHealthy reports whether the comparison had no unexpected differences/errors.
func (r EndpointResult) IsHealthy() bool {
	return r.Unexpected == 0 && r.Errors == 0
}

// expectedDiff reports whether a classification is an accepted difference.
func expectedDiff(class string, spec CompareSpec) bool {
	switch class {
	case ClassExactMatch:
		return true
	case ClassExpectedUnit, ClassExpectedSemantic, ClassOrderOnly:
		return true
	case ClassLegacyOnly:
		return spec.AllowLegacyOnly
	case ClassCanonicalOnly:
		return spec.AllowCanonOnly
	default:
		return false
	}
}

func (r *EndpointResult) add(class string, d DiffRecord) {
	if r.Classifications == nil {
		r.Classifications = map[string]int{}
	}
	r.Classifications[class]++
	if class == ClassExactMatch {
		return
	}
	r.Diffs = append(r.Diffs, d)
	if expectedDiff(class, r.specValue) {
		r.ExpectedDiffs++
	} else {
		r.Unexpected++
	}
}

// CompareRecords aligns two record sets by a stable key and classifies every
// difference. Row ordering never produces a false mismatch.
func CompareRecords(endpoint string, legacy, canonical []Record, spec CompareSpec) EndpointResult {
	res := EndpointResult{
		Endpoint:        endpoint,
		KeyField:        spec.KeyField,
		LegacyRows:      len(legacy),
		CanonicalRows:   len(canonical),
		Classifications: map[string]int{},
		specValue:       spec,
	}

	legacyIndex := indexRecords(legacy, spec.KeyField)
	canonIndex := indexRecords(canonical, spec.KeyField)

	// Keys present on both sides.
	common := make([]string, 0)
	for k := range legacyIndex {
		if _, ok := canonIndex[k]; ok {
			common = append(common, k)
		}
	}
	sort.Strings(common)
	res.Matched = len(common)

	missingDetail := spec.MaxMissingDetail
	if missingDetail <= 0 {
		missingDetail = 25
	}

	// Legacy-only keys.
	legacyOnly := keysOnlyIn(legacyIndex, canonIndex)
	for _, k := range legacyOnly {
		res.add(ClassLegacyOnly, DiffRecord{Endpoint: endpoint, Key: k, Field: spec.KeyField,
			Class: ClassLegacyOnly, Legacy: k, Canonical: "", Detail: "row absent from canonical"})
	}
	// Canonical-only keys.
	canonOnly := keysOnlyIn(canonIndex, legacyIndex)
	for _, k := range canonOnly {
		res.add(ClassCanonicalOnly, DiffRecord{Endpoint: endpoint, Key: k, Field: spec.KeyField,
			Class: ClassCanonicalOnly, Legacy: "", Canonical: k, Detail: "row absent from legacy"})
	}

	// Order-only difference: only meaningful when the key sets are identical.
	if len(legacyOnly) == 0 && len(canonOnly) == 0 {
		legacyOrder := keyOrder(legacy, spec.KeyField)
		canonOrder := keyOrder(canonical, spec.KeyField)
		if len(legacyOrder) == len(canonOrder) {
			for i := range legacyOrder {
				if legacyOrder[i] != canonOrder[i] {
					res.OrderChanged = true
					break
				}
			}
		}
	}
	_ = missingDetail

	// Common keys: compare each spec field.
	for _, k := range common {
		lrec := legacyIndex[k]
		crec := canonIndex[k]
		for _, f := range spec.Fields {
			lv, lok := lrec[f.Name]
			cv, cok := crec[f.Name]
			class, detail := classifyField(f, lok, lv, cok, cv)
			res.add(class, DiffRecord{
				Endpoint:  endpoint,
				Key:       k,
				Field:     f.Name,
				Class:     class,
				Legacy:    valueOrDash(lok, lv),
				Canonical: valueOrDash(cok, cv),
				Detail:    detail,
			})
		}
	}

	if res.OrderChanged {
		res.add(ClassOrderOnly, DiffRecord{Endpoint: endpoint, Field: spec.KeyField,
			Class: ClassOrderOnly, Detail: "row order differs; sets compared"})
	}

	return res
}

func classifyField(f FieldSpec, lok bool, lv Value, cok bool, cv Value) (string, string) {
	if !lok || !cok {
		return ClassNameUnclassified, "field missing on one side"
	}
	lnull := lv.Kind == KindNull
	cnull := cv.Kind == KindNull
	if lnull && cnull {
		return ClassExactMatch, ""
	}
	if lnull != cnull {
		return ClassNameNullSemantics, "NULL on one side only"
	}
	switch f.Kind {
	case KindNumber:
		if numbersEqual(lv.Num, cv.Num, f.Tolerance) {
			return ClassExactMatch, ""
		}
		if f.Money && f.ExpectedUnitPresentation && ratioIsMillion(lv.Num, cv.Num) {
			return ClassExpectedUnit, "million-IRR vs IRR presentation"
		}
		if f.ExpectedSemanticChange {
			return ClassExpectedSemantic, fmt.Sprintf("delta=%s", trimFloat(cv.Num-lv.Num))
		}
		return ClassNameNumericMismatch, fmt.Sprintf("legacy=%s canonical=%s", trimFloat(lv.Num), trimFloat(cv.Num))
	case KindText, KindDate:
		if lv.Text == cv.Text {
			return ClassExactMatch, ""
		}
		if f.Identity {
			return ClassNameIdentityMismatch, "identity value differs"
		}
		if f.ExpectedSemanticChange {
			return ClassExpectedSemantic, "expected canonical semantic change"
		}
		return ClassNameUnclassified, "text differs"
	case KindBool:
		if lv.Bool == cv.Bool {
			return ClassExactMatch, ""
		}
		if f.ExpectedSemanticChange {
			return ClassExpectedSemantic, "boolean semantics differ"
		}
		return ClassNameUnclassified, "boolean differs"
	default:
		return ClassNameUnclassified, "unhandled value kind"
	}
}

func indexRecords(rows []Record, keyField string) map[string]Record {
	idx := make(map[string]Record, len(rows))
	for _, r := range rows {
		k := keyOf(r, keyField)
		if k == "" {
			continue
		}
		idx[k] = r
	}
	return idx
}

func keyOrder(rows []Record, keyField string) []string {
	out := make([]string, 0, len(rows))
	for _, r := range rows {
		out = append(out, keyOf(r, keyField))
	}
	return out
}

func keyOf(r Record, keyField string) string {
	v, ok := r[keyField]
	if !ok {
		return ""
	}
	return strings.TrimSpace(v.String())
}

func keysOnlyIn(a, b map[string]Record) []string {
	out := make([]string, 0)
	for k := range a {
		if _, ok := b[k]; !ok {
			out = append(out, k)
		}
	}
	sort.Strings(out)
	return out
}

func valueOrDash(ok bool, v Value) string {
	if !ok {
		return "-"
	}
	return v.ASCIIString()
}

func numbersEqual(a, b, tol float64) bool {
	if tol <= 0 {
		tol = 1e-9
	}
	if a == b {
		return true
	}
	diff := math.Abs(a - b)
	scale := math.Max(math.Abs(a), math.Abs(b))
	if scale == 0 {
		return diff <= tol
	}
	return diff/scale <= tol
}

// ratioIsMillion reports whether the values differ by approximately a factor of
// one million, which is the documented canonical IRR vs legacy million-IRR
// presentation difference.
func ratioIsMillion(a, b float64) bool {
	if a == 0 || b == 0 {
		return false
	}
	ratio := math.Abs(a / b)
	if ratio < 1 {
		ratio = 1 / ratio
	}
	return ratio > 1e5 && ratio < 1e7
}

func trimFloat(f float64) string {
	if f == math.Trunc(f) && math.Abs(f) < 1e15 {
		return fmt.Sprintf("%.0f", f)
	}
	return fmt.Sprintf("%g", f)
}

var persianDigits = map[rune]rune{
	'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4',
	'۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
	'٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4',
	'٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9',
}

// NormalizeText trims, collapses whitespace, maps Arabic-Indic digits to ASCII
// and normalizes Persian ی/ک variants. It is deterministic and used only for
// comparison, never to mutate source data.
func NormalizeText(s string) string {
	s = strings.TrimSpace(s)
	var b strings.Builder
	b.Grow(len(s))
	lastSpace := false
	for _, r := range s {
		if d, ok := persianDigits[r]; ok {
			r = d
		}
		switch r {
		case 'ي':
			r = 'ی'
		case 'ك':
			r = 'ک'
		case '\u200c': // zero-width non-joiner: treat as separator
			r = ' '
		}
		if unicode.IsSpace(r) {
			if lastSpace {
				continue
			}
			lastSpace = true
			b.WriteRune(' ')
			continue
		}
		lastSpace = false
		b.WriteRune(r)
	}
	return strings.TrimSpace(b.String())
}

// NormalizeDate extracts a canonical YYYY-MM-DD prefix from common date strings.
func NormalizeDate(s string) string {
	s = strings.TrimSpace(s)
	if len(s) >= 10 && s[4] == '-' && s[7] == '-' {
		return s[:10]
	}
	return s
}

func asciiSafe(s string) string {
	var b strings.Builder
	for _, r := range s {
		if r < 128 {
			b.WriteRune(r)
		} else {
			b.WriteString(fmt.Sprintf("\\u%04x", r))
		}
	}
	return b.String()
}
