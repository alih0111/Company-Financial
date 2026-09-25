package integration

import (
	"encoding/csv"
	"fmt"
	"os"
	"strings"
	"sync"
)

// Eligibility classifications for a legacy price-history symbol/name.
const (
	// EligibleSafe: resolves to exactly one canonical security and the legacy
	// lookup matches at most one legacy market identity. Only these may be
	// canonical-served.
	EligibleSafe = "CANONICAL_SAFE"
	// CollisionLegacy: the legacy name lookup matches more than one legacy market
	// identity (e.g. two distinct securities sharing a CompanyName).
	CollisionLegacy = "LEGACY_IDENTITY_COLLISION"
	// LegacyOnly: the name exists in the legacy universe but has no canonical
	// security and no legacy market rows.
	LegacyOnly = "LEGACY_ONLY"
	// CanonicalUnmapped: legacy has market rows but no canonical security matches.
	CanonicalUnmapped = "CANONICAL_UNMAPPED"
	// NoMarketData: no legacy market rows and no canonical security.
	NoMarketData = "NO_MARKET_DATA"
	// OtherUnsafe: canonical resolution is itself ambiguous (>1 security) or
	// another structural ambiguity was found.
	OtherUnsafe = "OTHER_UNSAFE"
	// LegacyCoverageDivergence: single identity on both sides, but the legacy
	// date coverage differs from the canonical date coverage. Canonical serving
	// would return a different row set (client-visible), so it must not be
	// canonical-served under the current contract.
	LegacyCoverageDivergence = "LEGACY_COVERAGE_DIVERGENCE"
)

// EligibilityEntry is one audited symbol in the eligibility registry.
type EligibilityEntry struct {
	Symbol              string
	Classification      string
	Reason              string
	LegacyIdentities    int
	CanonicalSecurities int
	CanonicalSecurityID string
	CanonicalCompanyID  string
	ObservationCount    int
}

// EligibilityRegistry is a deterministic, loadable set of per-symbol
// classifications. Only CANONICAL_SAFE symbols may be canonical-served.
type EligibilityRegistry struct {
	mu      sync.RWMutex
	entries map[string]EligibilityEntry
	loaded  bool
}

// NewEligibilityRegistry creates an empty registry.
func NewEligibilityRegistry() *EligibilityRegistry {
	return &EligibilityRegistry{entries: map[string]EligibilityEntry{}}
}

// Add inserts an entry keyed by its normalized symbol.
func (r *EligibilityRegistry) Add(e EligibilityEntry) {
	if r == nil {
		return
	}
	r.mu.Lock()
	defer r.mu.Unlock()
	key := NormalizeText(e.Symbol)
	r.entries[key] = e
	r.loaded = true
}

// Loaded reports whether any entries are present.
func (r *EligibilityRegistry) Loaded() bool {
	if r == nil {
		return false
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	return r.loaded
}

// Class returns the classification for a symbol (or "" if unknown).
func (r *EligibilityRegistry) Class(symbol string) (string, EligibilityEntry) {
	if r == nil {
		return "", EligibilityEntry{}
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	e, ok := r.entries[NormalizeText(symbol)]
	if !ok {
		return "", EligibilityEntry{}
	}
	return e.Classification, e
}

// IsSafe reports whether a symbol is CANONICAL_SAFE. Unknown symbols and a
// missing registry are not safe (default-deny).
func (r *EligibilityRegistry) IsSafe(symbol string) bool {
	class, _ := r.Class(symbol)
	return class == EligibleSafe
}

// Count returns the number of entries by classification.
func (r *EligibilityRegistry) Count() (total int, byClass map[string]int) {
	byClass = map[string]int{}
	if r == nil {
		return 0, byClass
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, e := range r.entries {
		byClass[e.Classification]++
		total++
	}
	return total, byClass
}

// Collisions returns all symbol names classified as a legacy identity collision.
func (r *EligibilityRegistry) Collisions() []string {
	out := []string{}
	if r == nil {
		return out
	}
	r.mu.RLock()
	defer r.mu.RUnlock()
	for _, e := range r.entries {
		if e.Classification == CollisionLegacy {
			out = append(out, e.Symbol)
		}
	}
	sortStrings(out)
	return out
}

// LoadEligibility reads a registry CSV. A missing file returns (nil, nil) so the
// guard can be treated as inactive (backward-compatible SHADOW behavior).
func LoadEligibility(path string) (*EligibilityRegistry, error) {
	if strings.TrimSpace(path) == "" {
		return nil, nil
	}
	f, err := os.Open(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil, nil
		}
		return nil, err
	}
	defer f.Close()

	rd := csv.NewReader(f)
	rd.FieldsPerRecord = -1
	rows, err := rd.ReadAll()
	if err != nil {
		return nil, err
	}
	reg := NewEligibilityRegistry()
	if len(rows) == 0 {
		return reg, nil
	}
	header := rows[0]
	idx := map[string]int{}
	for i, h := range header {
		idx[strings.TrimSpace(strings.ToLower(h))] = i
	}
	col := func(row []string, name string) string {
		i, ok := idx[name]
		if !ok || i >= len(row) {
			return ""
		}
		return strings.TrimSpace(row[i])
	}
	for _, row := range rows[1:] {
		if len(row) == 0 {
			continue
		}
		sym := col(row, "symbol")
		if sym == "" {
			continue
		}
		reg.Add(EligibilityEntry{
			Symbol:              sym,
			Classification:      col(row, "classification"),
			Reason:              col(row, "reason"),
			LegacyIdentities:    atoiSafe(col(row, "legacy_identities")),
			CanonicalSecurities: atoiSafe(col(row, "canonical_securities")),
			CanonicalSecurityID: col(row, "canonical_security_id"),
			CanonicalCompanyID:  col(row, "canonical_company_id"),
			ObservationCount:    atoiSafe(col(row, "observation_count")),
		})
	}
	return reg, nil
}

// ValidateEligibilityCSV checks that the classification column only contains
// known values. Used by the audit tooling.
func ValidateEligibilityCSV(path string) error {
	reg, err := LoadEligibility(path)
	if err != nil || reg == nil {
		return err
	}
	_, byClass := reg.Count()
	for c := range byClass {
		switch c {
		case EligibleSafe, CollisionLegacy, LegacyOnly, CanonicalUnmapped, NoMarketData, OtherUnsafe, LegacyCoverageDivergence:
		default:
			return fmt.Errorf("unknown eligibility classification %q", c)
		}
	}
	return nil
}

func atoiSafe(s string) int {
	n := 0
	for _, r := range s {
		if r < '0' || r > '9' {
			return n
		}
		n = n*10 + int(r-'0')
	}
	return n
}
