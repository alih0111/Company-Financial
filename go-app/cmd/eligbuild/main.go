// Command eligbuild audits the legacy price-history symbol universe against the
// canonical identity model and writes a deterministic identity-eligibility
// registry plus a percentage-routing simulation. Read-only.
//
// Usage (from go-app/):
//
//	set CDF_CANONICAL_DB=company_financial_analytics_shadow_v121
//	go run ./cmd/eligbuild
package main

import (
	"context"
	"encoding/csv"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	"go-app/config"
	"go-app/integration"
)

const (
	legacyHead = `
		SELECT COALESCE(CompanyName,'') AS CompanyName, COALESCE(Symbol,'') AS Symbol,
		       COALESCE(InstrumentCode,'') AS InstrumentCode, COALESCE(CompanyID,'') AS CompanyID,
		       COUNT(*) AS c
		FROM dbo.MarketPriceHistory
		GROUP BY COALESCE(CompanyName,''), COALESCE(Symbol,''), COALESCE(InstrumentCode,''), COALESCE(CompanyID,'')`
)

type agg struct {
	identities map[string]bool
	obs        int
}

func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, "eligbuild error:", err)
		os.Exit(1)
	}
}

func run() error {
	ctx := context.Background()
	ssdb := config.GetDB()
	defer ssdb.Close()

	cfg := integration.LoadConfig()
	if cfg.CanonicalDSN == "" {
		return fmt.Errorf("canonical DSN not configured; set CDF_CANONICAL_DB")
	}
	pg, err := integration.OpenPG(cfg)
	if err != nil {
		return fmt.Errorf("open canonical: %w", err)
	}
	defer pg.Close()
	cDB := pg.DB()

	// --- legacy side: names -> set(identity), before/after normalization ---
	byName := map[string]*agg{}
	add := func(m map[string]*agg, key, identity string, count int) {
		if key == "" {
			return
		}
		a := m[key]
		if a == nil {
			a = &agg{identities: map[string]bool{}}
			m[key] = a
		}
		a.identities[identity] = true
		a.obs += count
	}
	rows, err := ssdb.Query(legacyHead)
	if err != nil {
		return err
	}
	for rows.Next() {
		var cname, sym, ins, cid string
		var c int
		if err := rows.Scan(&cname, &sym, &ins, &cid, &c); err != nil {
			rows.Close()
			return err
		}
		identity := strings.TrimSpace(ins)
		if identity == "" {
			identity = "s:" + sym + "|c:" + cid
		}
		if cname != "" {
			add(byName, integration.NormalizeText(cname), identity, c)
		}
		if sym != "" && integration.NormalizeText(sym) != integration.NormalizeText(cname) {
			add(byName, integration.NormalizeText(sym), identity, c)
		}
	}
	rows.Close()
	if err := rows.Err(); err != nil {
		return err
	}

	// Legacy date coverage per name (union over CompanyName and Symbol spelling).
	byNameDates := map[string]map[string]bool{}
	addDate := func(key, d string) {
		if key == "" || d == "" {
			return
		}
		m := byNameDates[key]
		if m == nil {
			m = map[string]bool{}
			byNameDates[key] = m
		}
		m[d] = true
	}
	drows, err := ssdb.Query(`SELECT COALESCE(CompanyName,''), COALESCE(Symbol,''), CONVERT(NVARCHAR(20), GregorianDate, 23) FROM dbo.MarketPriceHistory`)
	if err != nil {
		return err
	}
	for drows.Next() {
		var cname, sym, d string
		if err := drows.Scan(&cname, &sym, &d); err != nil {
			drows.Close()
			return err
		}
		nc, ns := integration.NormalizeText(cname), integration.NormalizeText(sym)
		addDate(nc, d)
		if ns != nc {
			addDate(ns, d)
		}
	}
	drows.Close()
	if err := drows.Err(); err != nil {
		return err
	}

	// Tracked tickers: additional names for LEGACY_ONLY detection.
	tracked := map[string]bool{}
	if tr, err := ssdb.Query("SELECT DISTINCT Symbol FROM dbo.TrackedTickers"); err == nil {
		for tr.Next() {
			var s string
			if tr.Scan(&s) == nil {
				tracked[integration.NormalizeText(s)] = true
			}
		}
		tr.Close()
	}

	// --- canonical side ---
	byCanon := map[string]map[string]bool{}
	secCompany := map[string]string{}
	secIns := map[string]string{}
	secSymbol := map[string]string{}
	addCanon := func(key, sec string) {
		if key == "" || sec == "" {
			return
		}
		m := byCanon[key]
		if m == nil {
			m = map[string]bool{}
			byCanon[key] = m
		}
		m[sec] = true
	}
	crows, err := cDB.QueryContext(ctx, `SELECT id::text, company_id::text, COALESCE(codal_symbol,''), COALESCE(brs_name,''), COALESCE(tsetmc_ins_code::text,'') FROM core.securities`)
	if err != nil {
		return err
	}
	for crows.Next() {
		var id, cid, cs, brs, ins string
		if err := crows.Scan(&id, &cid, &cs, &brs, &ins); err != nil {
			crows.Close()
			return err
		}
		secCompany[id] = cid
		secIns[id] = ins
		secSymbol[id] = cs
		addCanon(integration.NormalizeText(cs), id)
		addCanon(integration.NormalizeText(brs), id)
	}
	crows.Close()
	if err := crows.Err(); err != nil {
		return err
	}
	arows, err := cDB.QueryContext(ctx, `SELECT security_id::text, alias_value FROM core.security_aliases`)
	if err != nil {
		return err
	}
	for arows.Next() {
		var sid, av string
		if err := arows.Scan(&sid, &av); err != nil {
			arows.Close()
			return err
		}
		addCanon(integration.NormalizeText(av), sid)
	}
	arows.Close()
	if err := arows.Err(); err != nil {
		return err
	}

	// Canonical date coverage per security (latest adjusted observation set).
	secDates := map[string]map[string]bool{}
	cdrows, err := cDB.QueryContext(ctx, `SELECT security_id::text, trade_date::text FROM market.daily_prices`)
	if err != nil {
		return err
	}
	for cdrows.Next() {
		var sid, d string
		if err := cdrows.Scan(&sid, &d); err != nil {
			cdrows.Close()
			return err
		}
		m := secDates[sid]
		if m == nil {
			m = map[string]bool{}
			secDates[sid] = m
		}
		m[d] = true
	}
	cdrows.Close()
	if err := cdrows.Err(); err != nil {
		return err
	}

	// --- universe ---
	names := map[string]bool{}
	for n := range byName {
		names[n] = true
	}
	for n := range tracked {
		names[n] = true
	}

	entries := make([]integration.EligibilityEntry, 0, len(names))
	for name := range names {
		a := byName[name]
		legacyN := 0
		obs := 0
		if a != nil {
			legacyN = len(a.identities)
			obs = a.obs
		}
		canon := byCanon[name]
		canonN := len(canon)
		secID := ""
		if canonN == 1 {
			for s := range canon {
				secID = s
			}
		}
		class, reason := classify(legacyN, canonN, obs, tracked[name])
		// Coverage-safety: a single-identity symbol is only CANONICAL_SAFE when
		// the legacy and canonical date coverage match. Otherwise canonical
		// serving would return a different row set (client-visible).
		if class == integration.EligibleSafe && secID != "" {
			legSet := byNameDates[name]
			canSet := secDates[secID]
			if !sameDateSet(legSet, canSet) {
				class = integration.LegacyCoverageDivergence
				reason = fmt.Sprintf("legacy/canonical date coverage differs (legacy=%d canonical=%d)", len(legSet), len(canSet))
			}
		}
		e := integration.EligibilityEntry{
			Symbol:              name,
			Classification:      class,
			Reason:              reason,
			LegacyIdentities:    legacyN,
			CanonicalSecurities: canonN,
			CanonicalSecurityID: secID,
			ObservationCount:    obs,
		}
		if secID != "" {
			e.CanonicalCompanyID = secCompany[secID]
			if ins := secIns[secID]; ins != "" {
				e.Reason = strings.TrimSpace(e.Reason + " ins=" + ins)
			}
		}
		entries = append(entries, e)
	}
	sort.Slice(entries, func(i, j int) bool {
		if entries[i].Classification != entries[j].Classification {
			return entries[i].Classification < entries[j].Classification
		}
		return entries[i].Symbol < entries[j].Symbol
	})

	// --- write CSV ---
	outDir := cfg.OutputDir
	if err := os.MkdirAll(outDir, 0o755); err != nil {
		return err
	}
	csvPath := filepath.Join(outDir, "price_history_identity_eligibility.csv")
	if err := writeEligibilityCSV(csvPath, entries); err != nil {
		return err
	}

	// --- percentage simulation ---
	sim := simulate(entries)
	simPath := filepath.Join(outDir, "price_history_percent_simulation.json")
	if err := writeJSONFile(simPath, sim); err != nil {
		return err
	}

	// --- 5% cohort (exact selected set) ---
	cohortPath := filepath.Join(outDir, "price_history_percent5_cohort.csv")
	if err := writeCohortCSV(cohortPath, entries, 5); err != nil {
		return err
	}
	fmt.Printf("cohort: %s\n", cohortPath)

	// --- report ---
	total, byClass := countClasses(entries)
	collisions := collisionsOf(entries)
	fmt.Printf("registry: %s\n", csvPath)
	fmt.Printf("simulation: %s\n", simPath)
	fmt.Printf("total symbols audited: %d\n", total)
	for _, c := range []string{integration.EligibleSafe, integration.CollisionLegacy, integration.LegacyCoverageDivergence, integration.LegacyOnly, integration.CanonicalUnmapped, integration.NoMarketData, integration.OtherUnsafe} {
		fmt.Printf("  %s: %d\n", c, byClass[c])
	}
	fmt.Printf("collisions (%d): %s\n", len(collisions), strings.Join(collisions, ", "))
	return nil
}

func classify(legacyN, canonN, obs int, isTracked bool) (string, string) {
	switch {
	case canonN == 0 && obs == 0:
		if isTracked {
			return integration.LegacyOnly, "tracked legacy name with no market rows and no canonical security"
		}
		return integration.NoMarketData, "no legacy market rows and no canonical security"
	case canonN == 0:
		return integration.CanonicalUnmapped, "legacy market rows exist but no canonical security resolves"
	case canonN > 1:
		return integration.OtherUnsafe, "canonical resolution is ambiguous (>1 security)"
	case legacyN > 1:
		return integration.CollisionLegacy, "legacy name lookup matches more than one legacy market identity"
	default:
		return integration.EligibleSafe, "single canonical security and single legacy market identity"
	}
}

func sameDateSet(a, b map[string]bool) bool {
	if len(a) != len(b) {
		return false
	}
	for k := range a {
		if !b[k] {
			return false
		}
	}
	return true
}

func writeEligibilityCSV(path string, entries []integration.EligibilityEntry) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"symbol", "classification", "reason", "legacy_identities", "canonical_securities", "canonical_security_id", "canonical_company_id", "observation_count"})
	for _, e := range entries {
		_ = w.Write([]string{
			e.Symbol, e.Classification, e.Reason,
			itoa(e.LegacyIdentities), itoa(e.CanonicalSecurities),
			e.CanonicalSecurityID, e.CanonicalCompanyID, itoa(e.ObservationCount),
		})
	}
	return w.Error()
}

func simulate(entries []integration.EligibilityEntry) map[string]any {
	safe := []string{}
	for _, e := range entries {
		if e.Classification == integration.EligibleSafe {
			safe = append(safe, e.Symbol)
		}
	}
	out := map[string]any{
		"hash":        "fnv1a-32 mod 100",
		"safe_total":  len(safe),
		"unsafe_total": len(entries) - len(safe),
		"percents":    map[string]any{},
	}
	per := map[string]any{}
	for _, p := range []int{1, 5, 10, 25, 100} {
		cfg := integration.CanaryConfig{Enabled: true, Symbols: map[string]bool{}, Percent: p}
		safeSel := 0
		unsafeHashMatched := 0
		unsafeServed := 0 // after the eligibility guard: must always be 0
		rawFirst := 0
		rawSecond := 0
		for _, e := range entries {
			hashMatch := cfg.Selects(e.Symbol)
			safe := e.Classification == integration.EligibleSafe
			if hashMatch {
				rawFirst++
			}
			if hashMatch && safe {
				safeSel++
			}
			if hashMatch && !safe {
				unsafeHashMatched++
				// The eligibility guard forces legacy; canonical never serves it.
			}
		}
		// determinism: identical on a second pass
		for _, e := range entries {
			if cfg.Selects(e.Symbol) {
				rawSecond++
			}
		}
		per[fmt.Sprintf("%d", p)] = map[string]any{
			"percent":                    p,
			"safe_selected":              safeSel,
			"unsafe_hash_matched":        unsafeHashMatched,
			"unsafe_canonical_served":    unsafeServed,
			"guard_forced_legacy":        unsafeHashMatched,
			"safe_fraction":              fmt.Sprintf("%d/%d", safeSel, len(safe)),
			"raw_hash_matches_all_universe": rawFirst,
			"deterministic":              rawFirst == rawSecond,
		}
	}
	out["percents"] = per
	return out
}

func countClasses(entries []integration.EligibilityEntry) (int, map[string]int) {
	by := map[string]int{}
	for _, e := range entries {
		by[e.Classification]++
	}
	return len(entries), by
}

func collisionsOf(entries []integration.EligibilityEntry) []string {
	out := []string{}
	for _, e := range entries {
		if e.Classification == integration.CollisionLegacy {
			out = append(out, e.Symbol)
		}
	}
	return out
}

func writeCohortCSV(path string, entries []integration.EligibilityEntry, percent int) error {
	f, err := os.Create(path)
	if err != nil {
		return err
	}
	defer f.Close()
	w := csv.NewWriter(f)
	defer w.Flush()
	_ = w.Write([]string{"symbol", "normalized_symbol", "bucket", "classification", "safe", "selected"})
	for _, e := range entries {
		b := integration.Bucket(e.Symbol)
		safe := e.Classification == integration.EligibleSafe
		selected := safe && b < percent
		_ = w.Write([]string{
			e.Symbol, integration.NormalizeText(e.Symbol), itoa(b), e.Classification,
			fmt.Sprintf("%t", safe), fmt.Sprintf("%t", selected),
		})
	}
	return w.Error()
}

func writeJSONFile(path string, v any) error {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return err
	}
	b = append(b, '\n')
	return os.WriteFile(path, b, 0o644)
}

func itoa(n int) string { return fmt.Sprintf("%d", n) }
