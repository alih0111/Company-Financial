package handlers

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"time"

	"github.com/gin-gonic/gin"
)

const (
	codalJobsRoot      = ".runtime/codal-jobs"
	codalJobMaxAge     = 6 * time.Hour
	codalJobCancelWait = 3 * time.Second
)

var codalJobIDPattern = regexp.MustCompile(`^[a-f0-9]{32}$`)

type codalJob struct {
	mu               sync.RWMutex
	ID               string           `json:"job_id"`
	Source           string           `json:"source"`
	Parameters       SyncCodalRequest `json:"parameters"`
	State            string           `json:"state"`
	Stage            string           `json:"stage,omitempty"`
	CreatedAt        time.Time        `json:"created_at"`
	StartedAt        time.Time        `json:"started_at,omitempty"`
	UpdatedAt        time.Time        `json:"updated_at"`
	Heartbeat        time.Time        `json:"heartbeat"`
	Progress         map[string]any   `json:"progress,omitempty"`
	CurrentPage      int              `json:"current_page,omitempty"`
	CurrentReport    string           `json:"current_report_id,omitempty"`
	Counters         map[string]any   `json:"counters,omitempty"`
	Message          string           `json:"message,omitempty"`
	Challenge        map[string]any   `json:"challenge,omitempty"`
	RetryAt          any              `json:"retry_at,omitempty"`
	Summary          map[string]any   `json:"summary,omitempty"`
	Error            map[string]any   `json:"error,omitempty"`
	FinishedAt       *time.Time       `json:"finished_at,omitempty"`
	Revision         int64            `json:"revision"`
	AnswerConsumed   bool             `json:"-"`
	CommandPending   bool             `json:"-"`
	cancelRequested  bool             `json:"-"`
	terminalOverride string           `json:"-"`
	ctxCancel        context.CancelFunc
	cmd              *exec.Cmd
	done             chan struct{}
	root             string
}

var codalJobs = struct {
	sync.RWMutex
	items  map[string]*codalJob
	active string
	once   sync.Once
}{items: map[string]*codalJob{}}

func codalJobID() (string, error) {
	b := make([]byte, 16)
	if _, err := rand.Read(b); err != nil {
		return "", err
	}
	return hex.EncodeToString(b), nil
}

func codalJobTerminal(state string) bool {
	switch state {
	case "completed", "completed_with_errors", "failed", "cancelled", "expired", "interrupted":
		return true
	default:
		return false
	}
}

func (j *codalJob) snapshot() map[string]any {
	j.mu.RLock()
	defer j.mu.RUnlock()
	out := map[string]any{
		"job_id": j.ID, "source": j.Source, "parameters": j.Parameters, "state": j.State,
		"created_at": j.CreatedAt, "updated_at": j.UpdatedAt, "heartbeat": j.Heartbeat, "revision": j.Revision,
	}
	if j.Stage != "" {
		out["stage"] = j.Stage
	}
	if !j.StartedAt.IsZero() {
		out["started_at"] = j.StartedAt
	}
	if j.Progress != nil {
		out["progress"] = j.Progress
	}
	if j.CurrentPage > 0 {
		out["current_page"] = j.CurrentPage
	}
	if j.CurrentReport != "" {
		out["current_report_id"] = j.CurrentReport
	}
	if j.Counters != nil {
		out["counters"] = j.Counters
	}
	if j.Message != "" {
		out["message"] = j.Message
	}
	if j.Challenge != nil {
		out["challenge"] = j.Challenge
	}
	if j.RetryAt != nil {
		out["retry_at"] = j.RetryAt
	}
	if j.Summary != nil {
		out["summary"] = j.Summary
	}
	if j.Error != nil {
		out["error"] = j.Error
	}
	if j.FinishedAt != nil {
		out["finished_at"] = j.FinishedAt
	}
	return out
}

func (j *codalJob) applyStatus(status map[string]any) {
	j.mu.Lock()
	defer j.mu.Unlock()
	if j.cancelRequested {
		j.Heartbeat = time.Now().UTC()
		j.UpdatedAt = j.Heartbeat
		return
	}
	if n, ok := status["revision"].(float64); ok && int64(n) <= j.Revision {
		return
	}
	if state, ok := status["state"].(string); ok && state != "" {
		j.State = state
	}
	if stage, ok := status["stage"].(string); ok {
		j.Stage = stage
	}
	if message, ok := status["message"].(string); ok {
		j.Message = message
	}
	if n, ok := status["revision"].(float64); ok {
		j.Revision = int64(n)
	}
	if n, ok := status["current_page"].(float64); ok {
		j.CurrentPage = int(n)
	}
	if s, ok := status["current_report_id"].(string); ok {
		j.CurrentReport = s
	}
	if p, ok := status["progress"].(map[string]any); ok {
		j.Progress = p
	}
	if p, ok := status["counters"].(map[string]any); ok {
		j.Counters = p
	}
	if value, exists := status["challenge"]; exists {
		if p, ok := value.(map[string]any); ok {
			oldID, _ := j.Challenge["challenge_id"].(string)
			newID, _ := p["challenge_id"].(string)
			if oldID != newID {
				j.AnswerConsumed = false
				j.CommandPending = false
			}
			j.Challenge = p
		} else {
			j.Challenge = nil
			j.AnswerConsumed = false
			j.CommandPending = false
		}
	}
	if p, ok := status["error"].(map[string]any); ok {
		j.Error = p
	}
	if v, ok := status["retry_at"]; ok {
		j.RetryAt = v
	}
	if value, ok := status["heartbeat"].(float64); ok {
		j.Heartbeat = time.Unix(0, int64(value*float64(time.Second))).UTC()
	} else {
		j.Heartbeat = time.Now().UTC()
	}
	j.UpdatedAt = j.Heartbeat
}

func codalSyncWorkDir() (string, string, error) {
	cwd, err := os.Getwd()
	if err != nil {
		return "", "", err
	}
	if _, err = os.Stat(filepath.Join(cwd, "py", "sync_codal.py")); err == nil {
		return cwd, filepath.Join(cwd, "py", "sync_codal.py"), nil
	}
	if _, err = os.Stat(filepath.Join(cwd, "go-app", "py", "sync_codal.py")); err == nil {
		root := filepath.Join(cwd, "go-app")
		return root, filepath.Join(root, "py", "sync_codal.py"), nil
	}
	return "", "", fmt.Errorf("py/sync_codal.py not found")
}

func codalRequestArgs(req SyncCodalRequest) []string {
	mode := req.Mode
	if mode != "financial" && mode != "monthly" {
		mode = "all"
	}
	args := []string{"--type", mode}
	if req.DryRun {
		args = append(args, "--dry-run")
	}
	if req.MaxPages > 0 {
		args = append(args, "--max-pages", strconv.Itoa(req.MaxPages))
	}
	if req.Limit > 0 {
		args = append(args, "--limit", strconv.Itoa(req.Limit))
	}
	if symbol := strings.TrimSpace(req.Symbol); symbol != "" {
		args = append(args, "--symbol", symbol)
	}
	return args
}

func initCodalJobs() {
	codalJobs.once.Do(func() {
		_ = os.MkdirAll(codalJobsRoot, 0o700)
		lockPath := filepath.Join(codalJobsRoot, "active.lock")
		if raw, err := os.ReadFile(lockPath); err == nil {
			var owner struct {
				PID       int    `json:"pid"`
				WorkerPID int    `json:"worker_pid"`
				JobID     string `json:"job_id"`
				Heartbeat string `json:"heartbeat"`
			}
			_ = json.Unmarshal(raw, &owner)
			heartbeat, _ := time.Parse(time.RFC3339Nano, owner.Heartbeat)
			if codalProcessAlive(owner.PID) && time.Since(heartbeat) < 2*time.Minute {
				return
			}
			if owner.WorkerPID > 0 && staleWorkerBelongsToJob(owner.WorkerPID, owner.JobID) {
				stopCodalProcessTree(owner.WorkerPID)
			}
			_ = os.Remove(lockPath)
		} else if info, statErr := os.Stat(lockPath); statErr == nil && time.Since(info.ModTime()) > time.Minute {
			_ = os.Remove(lockPath)
		}
		entries, _ := os.ReadDir(codalJobsRoot)
		cleanupOldCodalJobs(codalJobsRoot, entries)
		for _, entry := range entries {
			if !entry.IsDir() || !codalJobIDPattern.MatchString(entry.Name()) {
				continue
			}
			path := filepath.Join(codalJobsRoot, entry.Name(), "status.json")
			raw, err := os.ReadFile(path)
			if err != nil {
				continue
			}
			var snap map[string]any
			if json.Unmarshal(raw, &snap) != nil {
				continue
			}
			state, _ := snap["state"].(string)
			if state != "" && !codalJobTerminal(state) {
				snap["state"] = "interrupted"
				snap["stage"] = "restart"
				snap["message"] = "سرور راه‌اندازی مجدد شد؛ برای ادامه یک اجرای تازه لازم است."
				snap["challenge"] = nil
				snap["error"] = map[string]string{"code": "interrupted", "message": "worker زنده نیست؛ نشست مرورگر پس از restart قابل ادامه نیست."}
				now := time.Now().UTC().Format(time.RFC3339Nano)
				snap["heartbeat"], snap["updated_at"], snap["finished_at"] = now, now, now
				if b, e := json.Marshal(snap); e == nil {
					_ = writeAtomicFile(path, b, 0o600)
				}
			}
		}
	})
}

func cleanupOldCodalJobs(root string, entries []os.DirEntry) {
	base, err := filepath.Abs(root)
	if err != nil {
		return
	}
	cutoff := time.Now().Add(-7 * 24 * time.Hour)
	for _, entry := range entries {
		if !entry.IsDir() || !codalJobIDPattern.MatchString(entry.Name()) {
			continue
		}
		candidate, err := filepath.Abs(filepath.Join(base, entry.Name()))
		if err != nil {
			continue
		}
		if filepath.Dir(candidate) != base || filepath.Base(candidate) != entry.Name() {
			continue
		}
		raw, err := os.ReadFile(filepath.Join(candidate, "status.json"))
		if err != nil {
			continue
		}
		var snapshot struct {
			State      string    `json:"state"`
			FinishedAt time.Time `json:"finished_at"`
		}
		if json.Unmarshal(raw, &snapshot) != nil || !codalJobTerminal(snapshot.State) || snapshot.FinishedAt.IsZero() || !snapshot.FinishedAt.Before(cutoff) {
			continue
		}
		_ = os.RemoveAll(candidate)
	}
}

func codalProcessAlive(pid int) bool {
	if pid <= 0 {
		return false
	}
	if runtime.GOOS == "windows" {
		out, err := exec.Command("tasklist", "/FI", fmt.Sprintf("PID eq %d", pid), "/FO", "CSV", "/NH").Output()
		return err == nil && strings.Contains(string(out), fmt.Sprintf("\"%d\"", pid))
	}
	return exec.Command("kill", "-0", strconv.Itoa(pid)).Run() == nil
}

func stopCodalProcessTree(pid int) {
	if pid <= 0 {
		return
	}
	if runtime.GOOS == "windows" {
		_ = exec.Command("taskkill", "/PID", strconv.Itoa(pid), "/T", "/F").Run()
		return
	}
	_ = exec.Command("kill", "-TERM", strconv.Itoa(pid)).Run()
}

func staleWorkerBelongsToJob(pid int, jobID string) bool {
	if pid <= 0 || !codalJobIDPattern.MatchString(jobID) {
		return false
	}
	needle := "--job-id " + jobID
	if runtime.GOOS == "windows" {
		script := fmt.Sprintf("$p=Get-CimInstance Win32_Process -Filter 'ProcessId=%d'; if($p -and $p.CommandLine.Contains('%s')){exit 0}else{exit 1}", pid, needle)
		return exec.Command("powershell", "-NoProfile", "-NonInteractive", "-Command", script).Run() == nil
	}
	out, err := exec.Command("ps", "-p", strconv.Itoa(pid), "-o", "args=").Output()
	return err == nil && strings.Contains(string(out), needle)
}

func writeAtomicFile(path string, data []byte, mode os.FileMode) error {
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return err
	}
	tmp := path + ".tmp"
	if err := os.WriteFile(tmp, data, mode); err != nil {
		return err
	}
	return os.Rename(tmp, path)
}

func claimCodalLock(lockPath, newJobID string, workDir string) (bool, string) {
	claim := func() bool {
		file, err := os.OpenFile(lockPath, os.O_WRONLY|os.O_CREATE|os.O_EXCL, 0o600)
		if err != nil {
			return false
		}
		_ = file.Close()
		data, _ := json.Marshal(map[string]any{"job_id": newJobID, "pid": os.Getpid(), "heartbeat": time.Now().UTC().Format(time.RFC3339Nano)})
		return writeAtomicFile(lockPath, data, 0o600) == nil
	}
	if claim() {
		return true, ""
	}
	raw, err := os.ReadFile(lockPath)
	if err != nil {
		if info, statErr := os.Stat(lockPath); statErr == nil && time.Since(info.ModTime()) > time.Minute {
			_ = os.Remove(lockPath)
			if claim() {
				return true, ""
			}
		}
		return false, ""
	}
	var owner struct {
		PID       int    `json:"pid"`
		WorkerPID int    `json:"worker_pid"`
		JobID     string `json:"job_id"`
		Heartbeat string `json:"heartbeat"`
	}
	_ = json.Unmarshal(raw, &owner)
	heartbeat, _ := time.Parse(time.RFC3339Nano, owner.Heartbeat)
	if codalProcessAlive(owner.PID) && time.Since(heartbeat) < 2*time.Minute {
		return false, owner.JobID
	}
	if owner.WorkerPID > 0 && staleWorkerBelongsToJob(owner.WorkerPID, owner.JobID) {
		stopCodalProcessTree(owner.WorkerPID)
	}
	if codalJobIDPattern.MatchString(owner.JobID) {
		path := filepath.Join(workDir, codalJobsRoot, owner.JobID, "status.json")
		if statusRaw, e := os.ReadFile(path); e == nil {
			var snapshot map[string]any
			if json.Unmarshal(statusRaw, &snapshot) == nil {
				now := time.Now().UTC().Format(time.RFC3339Nano)
				snapshot["state"], snapshot["stage"], snapshot["message"] = "interrupted", "restart", "اجرای قبلی worker زنده ندارد؛ نشست مرورگر ادامه‌پذیر نیست."
				snapshot["challenge"], snapshot["updated_at"], snapshot["finished_at"] = nil, now, now
				if encoded, e := json.Marshal(snapshot); e == nil {
					_ = writeAtomicFile(path, encoded, 0o600)
				}
			}
		}
	}
	_ = os.Remove(lockPath)
	if claim() {
		return true, owner.JobID
	}
	return false, owner.JobID
}

func startCodalSyncJob(req SyncCodalRequest, source string) (*codalJob, bool, error) {
	initCodalJobs()
	if !codalSyncBusy.CompareAndSwap(false, true) {
		codalJobs.RLock()
		active := codalJobs.items[codalJobs.active]
		codalJobs.RUnlock()
		if active == nil {
			active = &codalJob{ID: anyActiveCodalJobID()}
		}
		return active, true, nil
	}
	jobID, err := codalJobID()
	if err != nil {
		codalSyncBusy.Store(false)
		return nil, false, err
	}
	workDir, script, err := codalSyncWorkDir()
	if err != nil {
		codalSyncBusy.Store(false)
		return nil, false, err
	}
	root := filepath.Join(workDir, codalJobsRoot, jobID)
	if err = os.MkdirAll(filepath.Join(root, "commands"), 0o700); err != nil {
		codalSyncBusy.Store(false)
		return nil, false, err
	}
	now := time.Now().UTC()
	mode := req.Mode
	if mode != "financial" && mode != "monthly" {
		req.Mode = "all"
	} else {
		req.Mode = mode
	}
	job := &codalJob{ID: jobID, Source: source, Parameters: req, State: "queued", Stage: "queued", CreatedAt: now, UpdatedAt: now, Heartbeat: now, Message: "جمع‌آوری در صف اجراست", Revision: 0, root: root, done: make(chan struct{})}
	initial, _ := json.Marshal(job.snapshot())
	_ = writeAtomicFile(filepath.Join(root, "status.json"), initial, 0o600)
	codalJobs.Lock()
	if codalJobs.active != "" {
		codalJobs.Unlock()
		codalSyncBusy.Store(false)
		codalJobs.RLock()
		active := codalJobs.items[codalJobs.active]
		codalJobs.RUnlock()
		_ = os.RemoveAll(root)
		if active == nil {
			active = &codalJob{ID: anyActiveCodalJobID()}
		}
		return active, true, nil
	}
	codalJobs.items[jobID] = job
	codalJobs.active = jobID
	codalJobs.Unlock()

	lockPath := filepath.Join(workDir, codalJobsRoot, "active.lock")
	lockInfo, _ := json.Marshal(map[string]any{"job_id": jobID, "pid": os.Getpid(), "heartbeat": now.Format(time.RFC3339Nano)})
	claimed, ownerID := claimCodalLock(lockPath, jobID, workDir)
	if !claimed {
		_ = os.RemoveAll(root)
		codalJobs.Lock()
		delete(codalJobs.items, jobID)
		codalJobs.active = ""
		codalJobs.Unlock()
		codalSyncBusy.Store(false)
		return nil, true, fmt.Errorf("another Codal worker owns the cross-process lock: %s", ownerID)
	}

	py := codalSyncPython()
	ctx, cancel := context.WithCancel(context.Background())
	job.ctxCancel = cancel
	args := append([]string{script, "--job-id", jobID}, codalRequestArgs(req)...)
	command := exec.CommandContext(ctx, py, args...)
	command.Dir = workDir
	parameters, _ := json.Marshal(req)
	command.Env = append(os.Environ(), "PYTHONDONTWRITEBYTECODE=1", "PYTHONIOENCODING=utf-8", "CODAL_JOB_DIR="+root, "CODAL_JOB_ID="+jobID, "CODAL_JOB_SOURCE="+source, "CODAL_JOB_PARAMETERS="+string(parameters))
	stdout, err := os.OpenFile(filepath.Join(root, "stdout.json"), os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0o600)
	if err != nil {
		finishCodalJob(job, "failed", nil, map[string]any{"code": "worker_io", "message": err.Error()})
		return job, false, err
	}
	stderr, err := os.OpenFile(filepath.Join(root, "worker.log"), os.O_CREATE|os.O_WRONLY|os.O_APPEND, 0o600)
	if err != nil {
		stdout.Close()
		finishCodalJob(job, "failed", nil, map[string]any{"code": "worker_io", "message": err.Error()})
		return job, false, err
	}
	command.Stdout = stdout
	command.Stderr = stderr
	if err = command.Start(); err != nil {
		stdout.Close()
		stderr.Close()
		finishCodalJob(job, "failed", nil, map[string]any{"code": "worker_start", "message": err.Error()})
		return job, false, err
	}
	job.cmd = command
	command.Cancel = func() error { stopCodalProcessTree(command.Process.Pid); return nil }
	command.WaitDelay = 2 * time.Second
	lockInfo, _ = json.Marshal(map[string]any{"job_id": jobID, "pid": os.Getpid(), "worker_pid": command.Process.Pid, "heartbeat": time.Now().UTC().Format(time.RFC3339Nano)})
	go func() {
		defer stdout.Close()
		defer stderr.Close()
		poll := time.NewTicker(time.Second)
		defer poll.Stop()
		wait := make(chan error, 1)
		go func() { wait <- command.Wait() }()
		lockBeat := time.NewTicker(5 * time.Second)
		defer lockBeat.Stop()
		for {
			select {
			case err := <-wait:
				loadCodalWorkerResult(job, err)
				return
			case <-poll.C:
				refreshCodalJob(job)
				job.mu.RLock()
				expired := job.terminalOverride == "expired"
				job.mu.RUnlock()
				if time.Since(job.CreatedAt) > codalJobMaxAge && !expired {
					job.mu.Lock()
					job.terminalOverride = "expired"
					job.mu.Unlock()
					_ = putCodalCommand(job, map[string]any{"type": "cancel", "job_id": job.ID, "command_id": newCommandID()})
					time.AfterFunc(codalJobCancelWait, job.ctxCancel)
				}
			case <-lockBeat.C:
				lockInfo, _ = json.Marshal(map[string]any{"job_id": jobID, "pid": os.Getpid(), "worker_pid": command.Process.Pid, "heartbeat": time.Now().UTC().Format(time.RFC3339Nano)})
				_ = writeAtomicFile(lockPath, lockInfo, 0o600)
			}
		}
	}()
	return job, false, nil
}

func readCrossProcessActiveID(workDir string) string {
	raw, err := os.ReadFile(filepath.Join(workDir, codalJobsRoot, "active.lock"))
	if err != nil {
		return ""
	}
	var lock struct {
		JobID string `json:"job_id"`
	}
	_ = json.Unmarshal(raw, &lock)
	return lock.JobID
}

func refreshCodalJob(job *codalJob) {
	raw, err := os.ReadFile(filepath.Join(job.root, "status.json"))
	if err != nil {
		return
	}
	var status map[string]any
	if json.Unmarshal(raw, &status) != nil {
		return
	}
	job.applyStatus(status)
}

func loadCodalWorkerResult(job *codalJob, runErr error) {
	statusRaw, _ := os.ReadFile(filepath.Join(job.root, "status.json"))
	var status map[string]any
	_ = json.Unmarshal(statusRaw, &status)
	job.mu.RLock()
	cancelRequested, override := job.cancelRequested, job.terminalOverride
	job.mu.RUnlock()
	if override != "" {
		finishCodalJob(job, override, nil, nil)
		return
	}
	if cancelRequested {
		finishCodalJob(job, "cancelled", nil, nil)
		return
	}
	if state, _ := status["state"].(string); state == "expired" || state == "interrupted" {
		finishCodalJob(job, state, nil, nil)
		return
	}
	raw, err := os.ReadFile(filepath.Join(job.root, "stdout.json"))
	var summary map[string]any
	if err == nil {
		_ = json.Unmarshal(raw, &summary)
	}
	if len(summary) == 0 {
		statusRaw, _ := os.ReadFile(filepath.Join(job.root, "status.json"))
		var snap map[string]any
		_ = json.Unmarshal(statusRaw, &snap)
		if state, _ := snap["state"].(string); state == "cancelled" || state == "expired" {
			finishCodalJob(job, state, nil, nil)
			return
		}
		message := "worker did not return a valid summary"
		if runErr != nil {
			message = runErr.Error()
		}
		finishCodalJob(job, "failed", nil, map[string]any{"code": "invalid_worker_result", "message": message})
		return
	}
	success, _ := summary["success"].(bool)
	state := "completed"
	if !success || runErr != nil {
		state = "completed_with_errors"
	}
	finishCodalJob(job, state, summary, nil)
}

func finishCodalJob(job *codalJob, state string, summary, errorInfo map[string]any) {
	now := time.Now().UTC()
	job.mu.Lock()
	job.State = state
	job.Stage = "finished"
	job.UpdatedAt = now
	job.Heartbeat = now
	job.FinishedAt = &now
	job.Summary = summary
	job.Error = errorInfo
	job.Challenge = nil
	job.Message = map[string]string{"completed": "جمع‌آوری کدال تمام شد", "completed_with_errors": "جمع‌آوری تمام شد و بخشی از گزارش‌ها خطا داشت", "failed": "جمع‌آوری با خطا متوقف شد", "cancelled": "جمع‌آوری لغو شد", "expired": "زمان مجاز جمع‌آوری تمام شد", "interrupted": "اجرای قبلی با راه‌اندازی مجدد سرور متوقف شد"}[state]
	job.mu.Unlock()
	status, _ := json.Marshal(job.snapshot())
	_ = writeAtomicFile(filepath.Join(job.root, "status.json"), status, 0o600)
	_ = os.Remove(filepath.Join(job.root, "challenge.png"))
	_ = os.Remove(filepath.Join(job.root, "challenge.json"))
	commandsDir := filepath.Join(job.root, "commands")
	if entries, err := os.ReadDir(commandsDir); err == nil {
		for _, entry := range entries {
			if !entry.IsDir() && strings.HasSuffix(entry.Name(), ".json") {
				_ = os.Remove(filepath.Join(commandsDir, entry.Name()))
			}
		}
	}
	if job.ctxCancel != nil {
		job.ctxCancel()
	}
	codalJobs.Lock()
	if codalJobs.active == job.ID {
		codalJobs.active = ""
	}
	codalJobs.Unlock()
	codalSyncBusy.Store(false)
	_ = os.Remove(filepath.Join(filepath.Dir(job.root), "active.lock"))
	close(job.done)
}

func adminOnly(c *gin.Context) bool {
	if !c.GetBool("isAdmin") {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin only"})
		return false
	}
	return true
}

func StartCodalSyncJob(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	var req SyncCodalRequest
	if err := c.ShouldBindJSON(&req); err != nil && !errors.Is(err, context.Canceled) {
		c.JSON(400, gin.H{"error": "invalid request body"})
		return
	}
	job, conflict, err := startCodalSyncJob(req, "manual")
	if err != nil {
		if conflict {
			c.JSON(409, gin.H{"error": err.Error(), "active_job_id": anyActiveCodalJobID()})
			return
		}
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	if conflict {
		c.JSON(409, gin.H{"error": "یک جمع‌آوری کدال در حال اجراست", "active_job_id": job.ID, "job": job.snapshot()})
		return
	}
	c.JSON(http.StatusAccepted, job.snapshot())
}

func activeCodalJobID() string { codalJobs.RLock(); defer codalJobs.RUnlock(); return codalJobs.active }

func anyActiveCodalJobID() string {
	if id := activeCodalJobID(); id != "" {
		return id
	}
	workDir, _, err := codalSyncWorkDir()
	if err != nil {
		return ""
	}
	return readCrossProcessActiveID(workDir)
}

func GetActiveCodalJob(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	initCodalJobs()
	if id := activeCodalJobID(); id != "" {
		codalJobs.RLock()
		job := codalJobs.items[id]
		codalJobs.RUnlock()
		if job != nil {
			refreshCodalJob(job)
			c.JSON(200, job.snapshot())
			return
		}
	}
	if id := anyActiveCodalJobID(); id != "" && codalJobIDPattern.MatchString(id) {
		workDir, _, err := codalSyncWorkDir()
		if err == nil {
			raw, e := os.ReadFile(filepath.Join(workDir, codalJobsRoot, id, "status.json"))
			if e == nil {
				var snap map[string]any
				if json.Unmarshal(raw, &snap) == nil {
					c.JSON(200, snap)
					return
				}
			}
		}
	}
	c.JSON(200, gin.H{"job": nil})
}

func GetCodalJob(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	id := c.Param("job_id")
	if !codalJobIDPattern.MatchString(id) {
		c.JSON(400, gin.H{"error": "invalid job id"})
		return
	}
	codalJobs.RLock()
	job := codalJobs.items[id]
	codalJobs.RUnlock()
	if job == nil {
		path := filepath.Join(codalJobsRoot, id)
		raw, err := os.ReadFile(filepath.Join(path, "status.json"))
		if err != nil {
			c.JSON(404, gin.H{"error": "job not found"})
			return
		}
		var snap map[string]any
		_ = json.Unmarshal(raw, &snap)
		c.JSON(200, snap)
		return
	}
	refreshCodalJob(job)
	c.JSON(200, job.snapshot())
}

type codalCaptchaRequest struct {
	ChallengeID string `json:"challenge_id"`
	Answer      string `json:"answer"`
}

func ResumeCodalChallenge(c *gin.Context) { codalCommand(c, "resume") }

type codalRefreshRequest struct {
	ChallengeID string `json:"challenge_id"`
}

func codalCommand(c *gin.Context, kind string) {
	if !adminOnly(c) {
		return
	}
	id := c.Param("job_id")
	if !codalJobIDPattern.MatchString(id) {
		c.JSON(400, gin.H{"error": "invalid job id"})
		return
	}
	codalJobs.RLock()
	job := codalJobs.items[id]
	codalJobs.RUnlock()
	if job == nil {
		c.JSON(404, gin.H{"error": "job not found"})
		return
	}
	job.mu.Lock()
	defer job.mu.Unlock()
	if codalJobTerminal(job.State) {
		if kind == "cancel" {
			c.JSON(202, gin.H{"job_id": id, "state": job.State})
			return
		}
		c.JSON(409, gin.H{"error": "job is no longer active"})
		return
	}
	if kind == "cancel" {
		job.cancelRequested = true
		job.State = "cancelling"
		job.UpdatedAt = time.Now().UTC()
		_ = putCodalCommand(job, map[string]any{"type": "cancel", "job_id": id, "command_id": newCommandID()})
		go func() {
			select {
			case <-job.done:
				return
			case <-time.After(codalJobCancelWait):
				if job.ctxCancel != nil {
					job.ctxCancel()
				}
			}
		}()
		c.JSON(202, gin.H{"job_id": id, "state": "cancelling"})
		return
	}
	var challengeID, answer string
	if kind == "answer" {
		var body codalCaptchaRequest
		if c.ShouldBindJSON(&body) != nil {
			c.JSON(400, gin.H{"error": "invalid request body"})
			return
		}
		challengeID = strings.TrimSpace(body.ChallengeID)
		answer = strings.TrimSpace(body.Answer)
		if answer == "" || len(answer) > 64 {
			c.JSON(400, gin.H{"error": "invalid captcha answer"})
			return
		}
	}
	if kind == "refresh" || kind == "resume" {
		var body codalRefreshRequest
		if c.ShouldBindJSON(&body) != nil {
			c.JSON(400, gin.H{"error": "invalid request body"})
			return
		}
		challengeID = strings.TrimSpace(body.ChallengeID)
	}
	currentID, _ := job.Challenge["challenge_id"].(string)
	expires, _ := job.Challenge["expires_at"].(float64)
	if job.State != "waiting_captcha" || currentID == "" || challengeID != currentID || time.Now().Unix() > int64(expires) {
		c.JSON(409, gin.H{"error": "challenge expired or superseded"})
		return
	}
	if kind == "answer" && job.AnswerConsumed {
		c.JSON(409, gin.H{"error": "challenge answer already submitted"})
		return
	}
	if job.CommandPending {
		c.JSON(409, gin.H{"error": "a challenge command is already pending"})
		return
	}
	if kind == "refresh" {
		canRefresh, _ := job.Challenge["can_refresh"].(bool)
		if !canRefresh {
			c.JSON(409, gin.H{"error": "challenge refresh is not available"})
			return
		}
	}
	if kind == "resume" {
		canResume, _ := job.Challenge["can_manual_resume"].(bool)
		if !canResume {
			c.JSON(409, gin.H{"error": "manual browser resume is not available"})
			return
		}
	}
	command := map[string]any{"type": kind, "job_id": id, "challenge_id": challengeID, "command_id": newCommandID()}
	if kind == "answer" {
		command["answer"] = answer
		job.AnswerConsumed = true
	}
	job.CommandPending = true
	if err := putCodalCommand(job, command); err != nil {
		job.CommandPending = false
		if kind == "answer" {
			job.AnswerConsumed = false
		}
		c.JSON(500, gin.H{"error": "could not deliver command"})
		return
	}
	c.JSON(202, gin.H{"job_id": id, "challenge_id": challengeID, "accepted": true})
}

func newCommandID() string {
	id, err := codalJobID()
	if err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 10)
	}
	return id
}
func putCodalCommand(job *codalJob, command map[string]any) error {
	raw, err := json.Marshal(command)
	if err != nil {
		return err
	}
	dir := filepath.Join(job.root, "commands")
	name := fmt.Sprint(command["command_id"]) + ".json"
	return writeAtomicFile(filepath.Join(dir, name), raw, 0o600)
}
func SubmitCodalCaptcha(c *gin.Context)  { codalCommand(c, "answer") }
func RefreshCodalCaptcha(c *gin.Context) { codalCommand(c, "refresh") }
func CancelCodalJob(c *gin.Context)      { codalCommand(c, "cancel") }

// Used by the compatibility endpoint: wait only until completion or user action,
// independent of the lifetime of this HTTP request.
func waitLegacyCodalJob(job *codalJob) (map[string]any, bool) {
	ticker := time.NewTicker(250 * time.Millisecond)
	defer ticker.Stop()
	for {
		select {
		case <-job.done:
			return job.snapshot(), true
		case <-ticker.C:
			refreshCodalJob(job)
			s := job.snapshot()
			if s["state"] == "waiting_captcha" || s["state"] == "rate_limited" {
				return s, false
			}
		}
	}
}

func codalJobRuntime() string {
	if runtime.GOOS == "windows" {
		return "windows"
	}
	return "unix"
}
