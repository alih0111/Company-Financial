package handlers

import (
	"encoding/json"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	codalAutoStatePath = ".runtime/codal-auto-sync.json"
	codalAutoLockPath  = ".runtime/codal-auto-sync.lock" // legacy path retained for status compatibility
	codalAutoLogPath   = ".runtime/codal-auto-sync.log"
	codalAutoTimeout   = 15 * time.Minute // legacy constant used by existing operational checks
	codalAutoLockStale = 20 * time.Minute
)

// Single-flight is now shared by manual and scheduled runs through codal_jobs.go.
var codalSyncBusy atomic.Bool

func codalAutoSyncEnabled() bool { return os.Getenv("CODAL_AUTO_SYNC_ENABLED") != "0" }

func codalAutoSyncInterval() time.Duration {
	minutes, err := strconv.Atoi(os.Getenv("CODAL_AUTO_SYNC_INTERVAL_MINUTES"))
	if err != nil || minutes <= 0 {
		return 30 * time.Minute
	}
	if minutes < 5 {
		minutes = 5
	}
	return time.Duration(minutes) * time.Minute
}

// codalSyncPython prefers the workspace virtual environment used by Playwright.
func codalSyncPython() string {
	if cwd, err := os.Getwd(); err == nil {
		for _, candidate := range []string{filepath.Join(cwd, "..", ".venv", "Scripts", "python.exe"), filepath.Join(cwd, "..", ".venv", "scripts", "python.exe"), filepath.Join(cwd, "..", ".venv", "bin", "python")} {
			if _, err := os.Stat(candidate); err == nil {
				return candidate
			}
		}
	}
	return "python"
}

func StartCodalAutoSync() {
	if !codalAutoSyncEnabled() {
		log.Println("codal auto sync disabled (CODAL_AUTO_SYNC_ENABLED=0)")
		return
	}
	interval := codalAutoSyncInterval()
	log.Printf("codal auto sync enabled: every %s (first pass in 2m)", interval)
	go func() {
		time.Sleep(2 * time.Minute)
		for {
			codalAutoSyncTick()
			time.Sleep(codalAutoSyncInterval())
		}
	}()
}

// Automatic and manual calls enter the same job manager and worker lifecycle.
func codalAutoSyncTick() {
	if !codalAutoSyncEnabled() {
		return
	}
	job, conflict, err := startCodalSyncJob(SyncCodalRequest{Mode: "all"}, "automatic")
	if err != nil {
		if !conflict {
			log.Printf("codal auto sync could not start: %v", err)
		}
		return
	}
	if conflict {
		if job != nil {
			log.Printf("codal auto sync skipped; active job %s", job.ID)
		} else {
			log.Printf("codal auto sync skipped; another process owns the active lock")
		}
		return
	}
	writeCodalAutoState(map[string]any{"running": true, "status": "running", "last_attempt_at": time.Now().UTC().Format(time.RFC3339), "active_job_id": job.ID})
	go func() {
		<-job.done
		snap := job.snapshot()
		state := map[string]any{"running": false, "status": snap["state"], "finished_at": time.Now().UTC().Format(time.RFC3339), "last_summary": snap["summary"], "active_job_id": "", "next_run_at": time.Now().Add(codalAutoSyncInterval()).UTC().Format(time.RFC3339)}
		if snap["state"] == "completed" {
			state["last_success_at"] = state["finished_at"]
		}
		writeCodalAutoState(state)
	}()
}

func writeCodalAutoState(state map[string]any) {
	state["enabled"] = codalAutoSyncEnabled()
	state["interval_minutes"] = int(codalAutoSyncInterval().Minutes())
	raw, err := json.Marshal(state)
	if err != nil {
		return
	}
	_ = writeAtomicFile(codalAutoStatePath, raw, 0o600)
}

// GetCodalSyncStatus preserves the existing status contract and surfaces a
// manual or automatic active job so the client can reconnect to it.
func GetCodalSyncStatus(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	state := map[string]any{"enabled": codalAutoSyncEnabled(), "interval_minutes": int(codalAutoSyncInterval().Minutes()), "running": codalSyncBusy.Load(), "schedule_label": "جمع‌آوری خودکار جدیدترین گزارش‌های کدال برای نمادهای شما"}
	if raw, err := os.ReadFile(codalAutoStatePath); err == nil {
		persisted := map[string]any{}
		if json.Unmarshal(raw, &persisted) == nil {
			for k, v := range persisted {
				if _, exists := state[k]; !exists {
					state[k] = v
				}
			}
		}
	}
	if id := activeCodalJobID(); id != "" {
		codalJobs.RLock()
		job := codalJobs.items[id]
		codalJobs.RUnlock()
		if job != nil {
			refreshCodalJob(job)
			state["active_job"] = job.snapshot()
			state["running"] = true
		}
	}
	c.JSON(200, state)
}
