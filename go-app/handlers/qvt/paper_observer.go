package qvt

import (
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"time"
)

func paperObserverEnabled() bool {
	return os.Getenv("QVT_PAPER_OBSERVER_ENABLED") == "1"
}

func paperObservationDue(now time.Time) bool {
	local := now.In(time.FixedZone("Tehran", 12600))
	return local.Weekday() != time.Thursday && local.Weekday() != time.Friday &&
		(local.Hour() > 12 || local.Hour() == 12 && local.Minute() >= 45)
}

// This app worker reads public market evidence and writes only the isolated
// hypothetical journal. It cannot send brokerage orders. No OS task is installed.
func StartQvtPaperObserver() {
	if !paperObserverEnabled() {
		return
	}
	go func() {
		for {
			paperObserverTick(time.Now())
			time.Sleep(5 * time.Minute)
		}
	}()
}

func paperObserverTick(now time.Time) {
	if !paperObservationDue(now) {
		return
	}
	zone := time.FixedZone("Tehran", 12600)
	today := now.In(zone).Format("2006-01-02")
	statePath := filepath.Join(".runtime", "qvt-paper-observer.json")
	state := map[string]any{}
	if raw, err := os.ReadFile(statePath); err == nil {
		_ = json.Unmarshal(raw, &state)
	}
	if state["last_attempt_date"] == today {
		return
	}
	// Atomic lock excludes overlapping workers from multiple app processes.
	_ = os.MkdirAll(".runtime", 0700)
	lockPath := filepath.Join(".runtime", "qvt-paper-observer.lock")
	if st, err := os.Stat(lockPath); err == nil && now.Sub(st.ModTime()) > 15*time.Minute {
		// An interrupted process cannot hold a lock forever; command deadline is 10m.
		_ = os.Remove(lockPath)
	}
	lock, err := os.OpenFile(lockPath, os.O_CREATE|os.O_EXCL|os.O_WRONLY, 0600)
	if err != nil {
		return
	}
	defer os.Remove(lockPath)
	_ = lock.Close()
	state["last_attempt_date"], state["status"] = today, "running"
	state["last_attempt_at"] = now.Format(time.RFC3339)
	writeState := func() {
		raw, _ := json.Marshal(state)
		_ = os.WriteFile(statePath+".tmp", raw, 0600)
		_ = os.Rename(statePath+".tmp", statePath)
	}
	writeState()
	root, err := filepath.Abs("..")
	if err != nil {
		state["status"] = "failed"
		writeState()
		return
	}
	python := filepath.Join(root, ".venv", "Scripts", "python.exe")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Minute)
	defer cancel()
	cmd := exec.CommandContext(ctx, python, filepath.Join(root, "qvt_paper", "forward.py"), "tick", "--fetch")
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8")
	// Keep diagnostics local; API exposes only a short, stable status.
	output, err := cmd.CombinedOutput()
	_ = os.WriteFile(filepath.Join(".runtime", "qvt-paper-observer.log"), output, 0600)
	if err != nil {
		state["status"] = "failed"
		state["message"] = "به‌روزرسانی آزمایش کامل نشد؛ نتیجهٔ قبلی حفظ شده است"
	} else {
		state["status"] = "completed"
		state["message"] = "آخرین بررسی روزانه انجام شد"
		state["last_success_at"] = time.Now().Format(time.RFC3339)
	}
	writeState()
}

func paperObserverStatus() map[string]any {
	state := map[string]any{"enabled": paperObserverEnabled()}
	if raw, err := os.ReadFile(filepath.Join(".runtime", "qvt-paper-observer.json")); err == nil {
		_ = json.Unmarshal(raw, &state)
	}
	state["enabled"] = paperObserverEnabled()
	state["schedule_label"] = "بررسی روزانه پس از پایان بازار، تا وقتی سرور روشن است"
	return state
}
