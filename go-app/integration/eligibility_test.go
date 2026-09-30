package integration

import (
	"os"
	"path/filepath"
	"testing"
)

func registryWith(classes map[string]string) *EligibilityRegistry {
	reg := NewEligibilityRegistry()
	for sym, cls := range classes {
		reg.Add(EligibilityEntry{Symbol: sym, Classification: cls, Reason: "test"})
	}
	return reg
}

func TestEligibilityClassification(t *testing.T) {
	reg := registryWith(map[string]string{
		"فولاد":   EligibleSafe,
		"خودرو":   EligibleSafe,
		"کسرا":    EligibleSafe,
		"جم پیلن": CollisionLegacy,
		"های وب":  CollisionLegacy,
		"خاهن":    LegacyOnly,
		"نامعلوم": CanonicalUnmapped,
		"های وب3": LegacyCoverageDivergence,
	})
	if !reg.IsSafe("فولاد") || !reg.IsSafe("کسرا") {
		t.Fatalf("expected safe symbols")
	}
	if reg.IsSafe("های وب3") {
		t.Fatalf("coverage-divergent symbol must not be safe")
	}
	if reg.IsSafe("جم پیلن") || reg.IsSafe("های وب") {
		t.Fatalf("collision symbols must not be safe")
	}
	if reg.IsSafe("ناموجود") {
		t.Fatalf("unknown symbol must not be safe (default-deny)")
	}
	if cls, _ := reg.Class("جم پیلن"); cls != CollisionLegacy {
		t.Fatalf("class mismatch: %s", cls)
	}
	if coll := reg.Collisions(); len(coll) != 2 {
		t.Fatalf("want 2 collisions, got %v", coll)
	}
}

func TestGuardBlocksAllowlist(t *testing.T) {
	cfg := testCfg(ModeLegacy)
	cfg.Canary = canaryCfg(true, "جم پیلن", "فولاد")
	sh := newShadowForTest(cfg, &fakeSource{})
	sh.SetEligibility(registryWith(map[string]string{
		"جم پیلن": CollisionLegacy,
		"فولاد":   EligibleSafe,
	}))
	if got := sh.PriceHistoryRoute("جم پیلن"); got != RouteLegacy {
		t.Fatalf("allowlisted collision must be forced to legacy, got %v", got)
	}
	if got := sh.PriceHistoryRoute("فولاد"); got != RouteCanary {
		t.Fatalf("allowlisted safe must be canary, got %v", got)
	}
	sh.RecordEligibility("جم پیلن")
	sum := sh.canary.counters
	if sum[CounterGuardForcedLegacy] != 1 || sum[CounterIdentityCollision] != 1 {
		t.Fatalf("guard counters wrong: %v", sum)
	}
}

func TestGuardBlocksPercentage(t *testing.T) {
	cfg := testCfg(ModeLegacy)
	cfg.Canary = CanaryConfig{Enabled: true, Symbols: map[string]bool{}, Percent: 100, Timeout: 1000000}
	sh := newShadowForTest(cfg, &fakeSource{})
	sh.SetEligibility(registryWith(map[string]string{
		"جم پیلن": CollisionLegacy,
		"های وب":  CollisionLegacy,
		"فولاد":   EligibleSafe,
	}))
	if got := sh.PriceHistoryRoute("جم پیلن"); got != RouteLegacy {
		t.Fatalf("percentage must not select collision into canonical, got %v", got)
	}
	if got := sh.PriceHistoryRoute("های وب"); got != RouteLegacy {
		t.Fatalf("percentage must not select collision into canonical, got %v", got)
	}
	if got := sh.PriceHistoryRoute("فولاد"); got != RouteCanary {
		t.Fatalf("safe symbol must be selected at 100%%, got %v", got)
	}
}

func TestSafeAliasRemainsEligible(t *testing.T) {
	// کسرا is an alias case (symbol == canonical codal_symbol, display name differs).
	sh := newShadowForTest(func() Config {
		c := testCfg(ModeLegacy)
		c.Canary = canaryCfg(true, "کسرا")
		return c
	}(), &fakeSource{})
	sh.SetEligibility(registryWith(map[string]string{"کسرا": EligibleSafe}))
	if got := sh.PriceHistoryRoute("کسرا"); got != RouteCanary {
		t.Fatalf("safe alias must remain canonical eligible, got %v", got)
	}
}

func TestGuardDefaultDenyWithoutRegistry(t *testing.T) {
	cfg := testCfg(ModeLegacy)
	cfg.Canary = canaryCfg(true, "فولاد")
	sh := newShadowForTest(cfg, &fakeSource{})
	// No registry set.
	if sh.EligibilityGuardActive() {
		t.Fatalf("guard should be inactive without registry")
	}
	if got := sh.PriceHistoryRoute("فولاد"); got != RouteLegacy {
		t.Fatalf("serving must default-deny without registry, got %v", got)
	}
}

func TestShadowUnchangedWithoutRegistry(t *testing.T) {
	cfg := testCfg(ModeShadow)
	sh := newShadowForTest(cfg, &fakeSource{})
	if got := sh.PriceHistoryRoute("جم پیلن"); got != RouteShadow {
		t.Fatalf("shadow must be unchanged without registry, got %v", got)
	}
}

func TestRegistryForcesShadowLegacyForCollision(t *testing.T) {
	cfg := testCfg(ModeShadow)
	sh := newShadowForTest(cfg, &fakeSource{})
	sh.SetEligibility(registryWith(map[string]string{
		"جم پیلن": CollisionLegacy,
		"فولاد":   EligibleSafe,
	}))
	if got := sh.PriceHistoryRoute("جم پیلن"); got != RouteLegacy {
		t.Fatalf("registered collision must not shadow-compare, got %v", got)
	}
	if got := sh.PriceHistoryRoute("فولاد"); got != RouteShadow {
		t.Fatalf("safe symbol shadow unchanged, got %v", got)
	}
}

func TestEligibilityDeterministic(t *testing.T) {
	reg := registryWith(map[string]string{"فولاد": EligibleSafe, "جم پیلن": CollisionLegacy})
	for i := 0; i < 5; i++ {
		if !reg.IsSafe("فولاد") || reg.IsSafe("جم پیلن") {
			t.Fatalf("classification not deterministic")
		}
	}
	// Normalization: same symbol with whitespace maps to same entry.
	if !reg.IsSafe(" فولاد ") {
		t.Fatalf("normalized lookup failed")
	}
}

func TestLoadEligibilityCSV(t *testing.T) {
	dir := t.TempDir()
	path := filepath.Join(dir, "elig.csv")
	content := "symbol,classification,reason,legacy_identities,canonical_securities,canonical_security_id,canonical_company_id,observation_count\n" +
		"فولاد,CANONICAL_SAFE,single,1,1,sec-1,co-1,100\n" +
		"جم پیلن,LEGACY_IDENTITY_COLLISION,collision,3,1,sec-2,co-2,1618\n"
	if err := os.WriteFile(path, []byte(content), 0o644); err != nil {
		t.Fatal(err)
	}
	reg, err := LoadEligibility(path)
	if err != nil || reg == nil {
		t.Fatalf("load: %v reg=%v", err, reg)
	}
	if !reg.IsSafe("فولاد") {
		t.Fatalf("fولاد should be safe")
	}
	if reg.IsSafe("جم پیلن") {
		t.Fatalf("جم پیلن should not be safe")
	}
	total, byClass := reg.Count()
	if total != 2 || byClass[EligibleSafe] != 1 || byClass[CollisionLegacy] != 1 {
		t.Fatalf("counts wrong: %d %v", total, byClass)
	}
	// Missing file => nil registry, nil error (guard inactive).
	missing, err := LoadEligibility(filepath.Join(dir, "nope.csv"))
	if err != nil || missing != nil {
		t.Fatalf("missing file should yield nil,nil")
	}
}

func TestEligibilityCounters(t *testing.T) {
	sh := newShadowForTest(testCfg(ModeLegacy), &fakeSource{})
	sh.SetEligibility(registryWith(map[string]string{
		"فولاد":   EligibleSafe,
		"جم پیلن": CollisionLegacy,
		"خاهن":    LegacyOnly,
		"نامعلوم": CanonicalUnmapped,
	}))
	sh.RecordEligibility("فولاد")
	sh.RecordEligibility("جم پیلن")
	sh.RecordEligibility("خاهن")
	sh.RecordEligibility("نامعلوم")
	c := sh.canary.counters
	if c[CounterCanonicalSafe] != 1 || c[CounterCanonicalIneligible] != 3 {
		t.Fatalf("counters: %v", c)
	}
	if c[CounterIdentityCollision] != 1 || c[CounterEligLegacyOnly] != 1 || c[CounterEligCanonicalUnmapped] != 1 {
		t.Fatalf("class counters: %v", c)
	}
}
