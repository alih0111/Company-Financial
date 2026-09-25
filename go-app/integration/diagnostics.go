package integration

import (
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

// EndpointSummary captures per-endpoint metrics required by the phase artifacts.
type EndpointSummary struct {
	Endpoint        string         `json:"endpoint"`
	ReadMode        string         `json:"read_mode"`
	LegacyRows      int            `json:"legacy_row_count"`
	CanonicalRows   int            `json:"canonical_row_count"`
	Matched         int            `json:"match_count"`
	ExactMatches    int            `json:"exact_match_count"`
	ExpectedDiffs   int            `json:"expected_diff_count"`
	UnexpectedDiffs int            `json:"unexpected_diff_count"`
	ErrorCount      int            `json:"error_count"`
	OrderChanged    bool           `json:"order_only_difference"`
	Classifications map[string]int `json:"classifications"`
	LatencyLegacyMs float64        `json:"latency_legacy_ms"`
	LatencyCanonMs  float64        `json:"latency_canonical_ms"`
	LatencyTotalMs  float64        `json:"latency_combined_ms"`
	CanonicalError  string         `json:"canonical_error,omitempty"`
	UpdatedAt       string         `json:"updated_at"`
}

// SummaryFile is the top-level shadow_summary.json document.
type SummaryFile struct {
	SchemaVersion   string            `json:"schema_version"`
	GeneratedAt     string            `json:"generated_at"`
	ComparisonRules string            `json:"comparison_rules_version"`
	Endpoints       []EndpointSummary `json:"endpoints"`
}

// ComparisonRulesVersion identifies the deterministic comparison rules.
const ComparisonRulesVersion = "shadow-compare-v1"

// Collector accumulates shadow diagnostics and can flush deterministic artifacts.
type Collector struct {
	mu        sync.Mutex
	outputDir string
	results   map[string]EndpointSummary
	order     []string
}

// NewCollector creates a collector writing to outputDir.
func NewCollector(outputDir string) *Collector {
	return &Collector{outputDir: outputDir, results: map[string]EndpointSummary{}}
}

// Record merges a single endpoint comparison into the collector. Repeated
// comparisons of the same endpoint aggregate counts (last-writer latency).
func (c *Collector) Record(mode string, r EndpointResult) EndpointSummary {
	c.mu.Lock()
	defer c.mu.Unlock()

	s, ok := c.results[r.Endpoint]
	if !ok {
		s = EndpointSummary{Endpoint: r.Endpoint, Classifications: map[string]int{}}
		c.order = append(c.order, r.Endpoint)
	}
	s.ReadMode = mode
	s.LegacyRows += r.LegacyRows
	s.CanonicalRows += r.CanonicalRows
	s.Matched += r.Matched
	s.ExactMatches += r.Classifications[ClassExactMatch]
	s.ExpectedDiffs += r.ExpectedDiffs
	s.UnexpectedDiffs += r.Unexpected
	s.ErrorCount += r.Errors
	s.OrderChanged = s.OrderChanged || r.OrderChanged
	for k, v := range r.Classifications {
		s.Classifications[k] += v
	}
	s.LatencyLegacyMs += float64(r.LatencyLegacy.Microseconds()) / 1000.0
	s.LatencyCanonMs += float64(r.LatencyCanonical.Microseconds()) / 1000.0
	s.LatencyTotalMs += float64(r.LatencyTotal.Microseconds()) / 1000.0
	if r.CanonicalErr != nil {
		s.CanonicalError = r.CanonicalErr.Error()
	}
	s.UpdatedAt = time.Now().UTC().Format(time.RFC3339)
	c.results[r.Endpoint] = s
	return s
}

// Snapshot returns the current endpoint summaries in stable endpoint order.
func (c *Collector) Snapshot() []EndpointSummary {
	c.mu.Lock()
	defer c.mu.Unlock()
	out := make([]EndpointSummary, 0, len(c.order))
	for _, ep := range c.order {
		out = append(out, c.results[ep])
	}
	return out
}

// Flush writes the three deterministic diagnostic artifacts.
func (c *Collector) Flush() error {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.outputDir == "" {
		return nil
	}
	if err := os.MkdirAll(c.outputDir, 0o755); err != nil {
		return err
	}
	eps := make([]EndpointSummary, 0, len(c.order))
	for _, ep := range c.order {
		eps = append(eps, c.results[ep])
	}
	summary := SummaryFile{
		SchemaVersion:   "1",
		GeneratedAt:     time.Now().UTC().Format(time.RFC3339),
		ComparisonRules: ComparisonRulesVersion,
		Endpoints:       eps,
	}
	if err := writeJSON(filepath.Join(c.outputDir, "shadow_summary.json"), summary); err != nil {
		return err
	}
	if err := writeEndpointCSV(filepath.Join(c.outputDir, "endpoint_summary.csv"), eps); err != nil {
		return err
	}
	return nil
}

func writeJSON(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	b = append(b, '\n')
	return os.WriteFile(path, b, 0o644)
}

func writeEndpointCSV(path string, eps []EndpointSummary) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{
		"endpoint", "read_mode", "legacy_row_count", "canonical_row_count",
		"match_count", "exact_match_count", "expected_diff_count",
		"unexpected_diff_count", "error_count", "latency_legacy_ms",
		"latency_canonical_ms", "latency_combined_ms", "canonical_error",
	})
	for _, e := range eps {
		_ = w.Write([]string{
			e.Endpoint, e.ReadMode,
			strconv.Itoa(e.LegacyRows), strconv.Itoa(e.CanonicalRows),
			strconv.Itoa(e.Matched), strconv.Itoa(e.ExactMatches),
			strconv.Itoa(e.ExpectedDiffs), strconv.Itoa(e.UnexpectedDiffs),
			strconv.Itoa(e.ErrorCount),
			fmt.Sprintf("%.3f", e.LatencyLegacyMs),
			fmt.Sprintf("%.3f", e.LatencyCanonMs),
			fmt.Sprintf("%.3f", e.LatencyTotalMs),
			asciiSafe(e.CanonicalError),
		})
	}
	return w.Error()
}

// WriteDifferences writes per-difference rows for one comparison run.
func WriteDifferences(path string, results []EndpointResult) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"endpoint", "key", "field", "class", "legacy", "canonical", "detail"})
	for _, r := range results {
		for _, d := range r.Diffs {
			_ = w.Write([]string{
				asciiSafe(d.Endpoint), asciiSafe(d.Key), asciiSafe(d.Field),
				d.Class, d.Legacy, d.Canonical, asciiSafe(d.Detail),
			})
		}
	}
	return w.Error()
}

// ClassificationTotals returns a stable sorted classification summary.
func ClassificationTotals(results []EndpointResult) map[string]int {
	out := map[string]int{}
	for _, r := range results {
		for k, v := range r.Classifications {
			out[k] += v
		}
	}
	return out
}

// SortedClassifications renders classification totals in stable order.
func SortedClassifications(totals map[string]int) []string {
	keys := make([]string, 0, len(totals))
	for k := range totals {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	out := make([]string, 0, len(keys))
	for _, k := range keys {
		out = append(out, fmt.Sprintf("%s=%d", k, totals[k]))
	}
	return out
}

// JoinClasses is a small helper for compact reports.
func JoinClasses(totals map[string]int) string {
	return strings.Join(SortedClassifications(totals), ", ")
}
