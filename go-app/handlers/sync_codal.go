package handlers

import (
	"net/http"
	"time"

	"github.com/gin-gonic/gin"
)

// SyncCodalRequest contains immutable arguments captured by a Codal job.
type SyncCodalRequest struct {
	Mode     string `json:"mode"`
	DryRun   bool   `json:"dry_run"`
	MaxPages int    `json:"max_pages"`
	Limit    int    `json:"limit"`
	Symbol   string `json:"symbol"`
}

// RunSyncCodal is the legacy adapter. A normal run retains its historical 200
// summary; jobs needing user input return immediately with their durable ID.
func RunSyncCodal(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	var req SyncCodalRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(400, gin.H{"error": "invalid request body"})
		return
	}
	job, conflict, err := startCodalSyncJob(req, "manual")
	if err != nil {
		if conflict {
			c.JSON(http.StatusConflict, gin.H{"error": err.Error(), "active_job_id": anyActiveCodalJobID()})
			return
		}
		c.JSON(500, gin.H{"error": err.Error()})
		return
	}
	if conflict {
		c.JSON(http.StatusConflict, gin.H{"error": "یک جمع‌آوری کدال در حال اجراست", "active_job_id": job.ID, "job": job.snapshot()})
		return
	}
	ctxDone := c.Request.Context().Done()
	tick := time.NewTicker(250 * time.Millisecond)
	defer tick.Stop()
	deadline := time.NewTimer(30 * time.Minute)
	defer deadline.Stop()
	for {
		select {
		case <-job.done:
			job.mu.RLock()
			summary := job.Summary
			job.mu.RUnlock()
			if summary != nil {
				c.JSON(http.StatusOK, summary)
				return
			}
			c.JSON(500, job.snapshot())
			return
		case <-ctxDone:
			// Request cancellation only detaches this compatibility caller.
			return
		case <-deadline.C:
			c.JSON(http.StatusAccepted, job.snapshot())
			return
		case <-tick.C:
			refreshCodalJob(job)
			job.mu.RLock()
			state := job.State
			job.mu.RUnlock()
			if state == "waiting_captcha" || state == "rate_limited" {
				c.JSON(http.StatusAccepted, job.snapshot())
				return
			}
		}
	}
}
