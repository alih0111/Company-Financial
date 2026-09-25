package integration

import (
	"os"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// These tests are lightweight static guards. They complement (and do not
// replace) type-aware review. They catch the specific Phase-1 safety
// regressions the integration layer must never introduce.

func integrationDir(t *testing.T) string {
	t.Helper()
	_, file, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("cannot locate package dir")
	}
	return filepath.Dir(file)
}

func goSourceFiles(t *testing.T) map[string]string {
	t.Helper()
	dir := integrationDir(t)
	entries, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	files := map[string]string{}
	for _, e := range entries {
		name := e.Name()
		if e.IsDir() || !strings.HasSuffix(name, ".go") || strings.HasSuffix(name, "_test.go") {
			continue
		}
		b, err := os.ReadFile(filepath.Join(dir, name))
		if err != nil {
			t.Fatal(err)
		}
		files[name] = string(b)
	}
	return files
}

func TestGuardNoCanonicalWrites(t *testing.T) {
	forbidden := []string{
		"insert into", "update ", "delete from", "merge into",
		"drop table", "truncate ", "alter table", "create table",
	}
	for name, src := range goSourceFiles(t) {
		low := strings.ToLower(src)
		for _, f := range forbidden {
			if strings.Contains(low, f) {
				t.Fatalf("%s contains forbidden canonical write/DDL token %q", name, f)
			}
		}
	}
}

func TestGuardNoLegacyHeuristics(t *testing.T) {
	forbidden := []string{"product1", "npunitratio", "opk", "opamt"}
	for name, src := range goSourceFiles(t) {
		low := strings.ToLower(src)
		for _, f := range forbidden {
			if strings.Contains(low, f) {
				t.Fatalf("%s contains legacy heuristic %q, which must not enter canonical paths", name, f)
			}
		}
	}
}

func TestGuardNoHardcodedCredentials(t *testing.T) {
	forbidden := []string{
		"password=", "pwd=", "user id=", "userid=",
		"postgres://postgres:", "trusted_connection=yes",
	}
	for name, src := range goSourceFiles(t) {
		low := strings.ToLower(src)
		for _, f := range forbidden {
			if strings.Contains(low, f) {
				t.Fatalf("%s contains hard-coded credential pattern %q", name, f)
			}
		}
	}
}

func TestGuardNoAnalyticsFormulaDuplication(t *testing.T) {
	// The integration layer must consume canonical analytics, never reimplement
	// factor formulas. TTM/weighting arithmetic in Go would be a red flag.
	for name, src := range goSourceFiles(t) {
		low := strings.ToLower(src)
		for _, f := range []string{"ttmnetprofit", "quant_score =", "weighted_score =", "0.3*", "normalize("} {
			if strings.Contains(low, f) {
				t.Fatalf("%s appears to duplicate analytics logic (%q)", name, f)
			}
		}
	}
}
