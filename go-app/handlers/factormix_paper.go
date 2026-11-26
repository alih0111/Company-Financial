package handlers

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sync/atomic"
	"time"

	"github.com/gin-gonic/gin"
)

const factorMixPaperDir = ".runtime/factormix-monthly-paper"

var factorMixPaperStarting atomic.Bool

func startFactorMixPaper() error {
	if !factorMixPaperStarting.CompareAndSwap(false, true) {
		return nil
	}
	started := false
	defer func() {
		if !started {
			factorMixPaperStarting.Store(false)
		}
	}()
	root, err := analyticsRepoRoot()
	if err != nil {
		return err
	}
	dir := filepath.Join(root, factorMixPaperDir)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return err
	}
	out, err := os.OpenFile(filepath.Join(dir, "button.log"), os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o644)
	if err != nil {
		return err
	}
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Hour)
	cmd := exec.CommandContext(ctx, analyticsRefreshPython(root), "-B", "-m", "factormix.monthly_paper")
	cmd.Dir = root
	cmd.Env = append(os.Environ(), "PYTHONUTF8=1")
	cmd.Stdout, cmd.Stderr = out, out
	if err := cmd.Start(); err != nil {
		cancel()
		out.Close()
		return err
	}
	started = true
	go func() {
		defer factorMixPaperStarting.Store(false)
		defer out.Close()
		defer cancel()
		if err := cmd.Wait(); err != nil {
			log.Printf("FactorMix monthly paper cycle failed: %v", err)
		}
	}()
	return nil
}

func GetFactorMixPaper(c *gin.Context) {
	if !adminOnly(c) {
		return
	}
	root, err := analyticsRepoRoot()
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "دفتر کاغذی در دسترس نیست."})
		return
	}
	reply := gin.H{"account": nil, "status": nil, "starting": factorMixPaperStarting.Load()}
	for _, key := range []string{"account", "status"} {
		body, err := os.ReadFile(filepath.Join(root, factorMixPaperDir, key+".json"))
		if errors.Is(err, os.ErrNotExist) {
			continue
		}
		if err != nil || !json.Valid(body) {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "خواندن دفتر کاغذی ناموفق بود."})
			return
		}
		reply[key] = json.RawMessage(body)
	}
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, reply)
}
