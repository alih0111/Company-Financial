package handlers

import (
	"encoding/json"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/gin-gonic/gin"
)

func codalTestJob(t *testing.T) (*codalJob, func()) {
	t.Helper()
	root := t.TempDir()
	if err := os.MkdirAll(filepath.Join(root, "commands"), 0o700); err != nil {
		t.Fatal(err)
	}
	id := "0123456789abcdef0123456789abcdef"
	job := &codalJob{ID: id, Source: "manual", State: "waiting_captcha", CreatedAt: time.Now(), UpdatedAt: time.Now(),
		Heartbeat: time.Now(), root: root, done: make(chan struct{}), Challenge: map[string]any{"challenge_id": "current", "expires_at": float64(time.Now().Add(time.Minute).Unix())}}
	codalJobs.Lock()
	codalJobs.items[id] = job
	codalJobs.Unlock()
	return job, func() { codalJobs.Lock(); delete(codalJobs.items, id); codalJobs.Unlock() }
}

func runCodalJobHandler(t *testing.T, handler gin.HandlerFunc, jobID, body string) *httptest.ResponseRecorder {
	t.Helper()
	gin.SetMode(gin.TestMode)
	r := gin.New()
	r.POST("/jobs/:job_id/captcha", handler)
	req := httptest.NewRequest("POST", "/jobs/"+jobID+"/captcha", strings.NewReader(body))
	rec := httptest.NewRecorder()
	ctx, _ := gin.CreateTestContext(rec)
	ctx.Request = req
	ctx.Params = gin.Params{{Key: "job_id", Value: jobID}}
	ctx.Set("isAdmin", true)
	handler(ctx)
	return rec
}

func TestCodalCaptchaCommandRequiresCurrentChallengeAndIsSingleUse(t *testing.T) {
	job, cleanup := codalTestJob(t)
	defer cleanup()
	got := runCodalJobHandler(t, SubmitCodalCaptcha, job.ID, `{"challenge_id":"current","answer":"A123"}`)
	if got.Code != 202 {
		t.Fatalf("submit status=%d body=%s", got.Code, got.Body.String())
	}
	files, err := os.ReadDir(filepath.Join(job.root, "commands"))
	if err != nil || len(files) != 1 {
		t.Fatalf("expected one command file, got %d, err=%v", len(files), err)
	}
	var command map[string]any
	raw, err := os.ReadFile(filepath.Join(job.root, "commands", files[0].Name()))
	if err != nil || json.Unmarshal(raw, &command) != nil {
		t.Fatalf("invalid command file: %v", err)
	}
	if command["answer"] != "A123" || command["challenge_id"] != "current" {
		t.Fatalf("unexpected command: %#v", command)
	}
	duplicate := runCodalJobHandler(t, SubmitCodalCaptcha, job.ID, `{"challenge_id":"current","answer":"A123"}`)
	if duplicate.Code != 409 {
		t.Fatalf("duplicate answer status=%d", duplicate.Code)
	}
	old := runCodalJobHandler(t, SubmitCodalCaptcha, job.ID, `{"challenge_id":"old","answer":"A123"}`)
	if old.Code != 409 {
		t.Fatalf("stale challenge status=%d", old.Code)
	}
}

func TestCodalCaptchaRejectsInvalidJobID(t *testing.T) {
	got := runCodalJobHandler(t, SubmitCodalCaptcha, "../../not-a-job", `{"challenge_id":"x","answer":"1"}`)
	if got.Code != 400 {
		t.Fatalf("invalid job id status=%d body=%s", got.Code, got.Body.String())
	}
}
