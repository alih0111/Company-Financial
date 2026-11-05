package handlers

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestPaperTrialLastSuccessKeepsAccountsAndPartialRunsSeparate(t *testing.T) {
	root := t.TempDir()
	account := func(status string) json.RawMessage { return json.RawMessage(`{"status":"` + status + `"}`) }
	for _, item := range []paperTrialRefreshStatus{
		{RunID: "run-one", State: "Finished", FinishedAt: "2026-11-01T10:00:00Z", Accounts: map[string]json.RawMessage{"P1": account("MARK_APPLIED"), "P3": account("FILL_APPLIED")}},
		{RunID: "run-two", State: "Failed", FinishedAt: "2026-11-02T10:00:00Z", Accounts: map[string]json.RawMessage{"P1": account("ERROR"), "P3": account("MARK_APPLIED")}},
		{RunID: "run-three", State: "Finished", FinishedAt: "2026-11-03T10:00:00Z", Accounts: map[string]json.RawMessage{"P1": account("NO_NEW_MARK"), "P3": account("ERROR")}},
		{RunID: "run-four", State: "Running", FinishedAt: "2026-11-04T10:00:00Z", Accounts: map[string]json.RawMessage{"P1": account("FILL_APPLIED")}},
	} {
		if err := writePaperTrialStatus(root, item); err != nil {
			t.Fatal(err)
		}
	}
	got := paperTrialLastSuccess(root)
	if got["P1"].RunID != "run-one" || got["P3"].RunID != "run-two" || got["P3"].Outcome != "MARK_APPLIED" {
		t.Fatalf("incorrect per-account last success: %+v", got)
	}
	view := paperTrialStatusWithHistory(root, time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC))
	if !view.RecoveryRequired || view.LastSuccess["P1"].RunID != "run-one" || view.LastSuccessScope != "completed_manual_runs_with_explicit_applied_outcomes_only" {
		t.Fatalf("status view omitted recovery or per-account history: %+v", view)
	}
}

func TestPaperTrialOutcomeRequiresBothAccountResults(t *testing.T) {
	value := func(status string) json.RawMessage { return json.RawMessage(`{"status":"` + status + `"}`) }
	for _, tc := range []struct {
		name     string
		accounts map[string]json.RawMessage
		want     string
	}{
		{"absent", nil, "ACCOUNT_OUTCOMES_NOT_RECORDED"},
		{"missing P3", map[string]json.RawMessage{"P1": value("MARK_APPLIED")}, "ACCOUNT_OUTCOME_MISSING:P3"},
		{"P1 error", map[string]json.RawMessage{"P1": value("ERROR"), "P3": value("MARK_APPLIED")}, "ACCOUNT_ERROR:P1"},
		{"waiting is explicit", map[string]json.RawMessage{"P1": value("NO_NEW_MARK"), "P3": value("PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE")}, ""},
	} {
		t.Run(tc.name, func(t *testing.T) {
			if got := paperTrialOutcomeError(tc.accounts); got != tc.want {
				t.Fatalf("got %q, want %q", got, tc.want)
			}
		})
	}
}

func TestPaperTrialRunningNeverExpiresIntoAutomaticTakeover(t *testing.T) {
	now := time.Date(2026, 11, 5, 0, 0, 0, 0, time.UTC)
	for _, tc := range []struct {
		name             string
		status           paperTrialRefreshStatus
		running, inspect bool
	}{
		{"fresh", paperTrialRefreshStatus{State: "Running", StartedAt: now.Add(-time.Minute).Format(time.RFC3339)}, true, false},
		{"long running", paperTrialRefreshStatus{State: "Running", StartedAt: now.Add(-30 * time.Minute).Format(time.RFC3339)}, true, true},
		{"invalid timestamp", paperTrialRefreshStatus{State: "Running", StartedAt: "invalid"}, true, true},
		{"future timestamp", paperTrialRefreshStatus{State: "Running", StartedAt: now.Add(time.Minute).Format(time.RFC3339)}, true, true},
		{"finished", paperTrialRefreshStatus{State: "Finished"}, false, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			running, inspect := paperTrialRunningState(tc.status, now)
			if running != tc.running || inspect != tc.inspect {
				t.Fatalf("running=%v, inspection=%v", running, inspect)
			}
		})
	}
}

func TestPaperTrialStageLogsAndRunOwnership(t *testing.T) {
	root := t.TempDir()
	expLog := filepath.Join(root, "experimental.log")
	trialLog := filepath.Join(root, "trial.log")
	if err := os.WriteFile(expLog, []byte("{\"status\":\"BLOCKED_EXECUTION\",\"reason\":\"CALENDAR_NOT_READY\"}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(trialLog, []byte("{\"state\":\"DAILY_ERRORS\",\"accounts\":{\"P1\":{\"status\":\"ERROR\"},\"P3\":{\"status\":\"MARK_APPLIED\"}}}\n"), 0600); err != nil {
		t.Fatal(err)
	}
	if got := paperTrialLogTail(expLog); !strings.Contains(got, "CALENDAR_NOT_READY") {
		t.Fatalf("wrong experimental error: %s", got)
	}
	if got := paperTrialLogTail(trialLog); strings.Contains(got, "CALENDAR_NOT_READY") {
		t.Fatalf("stages mixed: %s", got)
	}
	accounts := paperTrialAccounts(trialLog)
	if !strings.Contains(string(accounts["P1"]), "ERROR") || !strings.Contains(string(accounts["P3"]), "MARK_APPLIED") {
		t.Fatalf("account outcomes missing or mixed: %v", accounts)
	}
	if err := writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Running", RunID: "run-new"}); err != nil {
		t.Fatal(err)
	}
	if paperTrialStatusIsMine(root, "run-old") || !paperTrialStatusIsMine(root, "run-new") {
		t.Fatal("run ownership is not isolated")
	}
	perRun := filepath.Join(root, filepath.FromSlash(paperTrialRunsPath), "run-new", "status.json")
	if raw, err := os.ReadFile(perRun); err != nil || !strings.Contains(string(raw), "run-new") {
		t.Fatalf("per-run status not persisted: %s %v", raw, err)
	}
	if err := writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Failed", RunID: "run-new"}); err != nil {
		t.Fatalf("atomic replacement failed: %v", err)
	}
	if err := writePaperTrialStatus(root, paperTrialRefreshStatus{State: "Running", RunID: "../escape"}); err == nil {
		t.Fatal("invalid run ID accepted")
	}
}
