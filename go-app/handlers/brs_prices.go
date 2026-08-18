package handlers

import (
	"fmt"
	"log"
	"net/http"
	"os/exec"
	"strconv"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// BrsCollectRequest بدنه‌ی درخواست اجرای کالکتور قیمت BRS.
type BrsCollectRequest struct {
	Mode      string  `json:"mode"`   // "daily" | "backfill" | "sync"
	Limit     int     `json:"limit"`  // backfill: تعداد نماد | sync: تعداد روز
	Symbol    string  `json:"symbol"` // فقط backfill: نماد خاص
	Force     bool    `json:"force"`  // فقط backfill: نادیده‌گرفتن تاریخچه
	Raw       bool    `json:"raw"`    // فقط backfill: بدون تطبیق codal
	API       bool    `json:"api"`    // فقط sync: استفاده از API به‌جای تعدیل محلی
	Threshold float64 `json:"threshold"` // فقط sync: آستانه‌ی تشخیص شکاف (درصد)
}

// RunBrsCollector کالکتور قیمت BRS (py/brs_prices.py) را اجرا می‌کند.
// دسترسی فقط برای ادمین. لاگ‌ها به‌صورت زنده به کنسول سرور استریم می‌شوند.
func RunBrsCollector(c *gin.Context) {
	if !c.GetBool("isAdmin") {
		c.JSON(http.StatusForbidden, gin.H{"error": "admin only"})
		return
	}

	var req BrsCollectRequest
	// بدنه اختیاری است؛ اگر نبود با مقادیر پیش‌فرض ادامه می‌دهیم.
	_ = c.ShouldBindJSON(&req)

	mode := req.Mode
	if mode != "daily" && mode != "backfill" && mode != "sync" {
		mode = "daily"
	}

	args := []string{"py/brs_prices.py", mode}
	if mode == "backfill" {
		if req.Limit > 0 {
			args = append(args, "--limit", strconv.Itoa(req.Limit))
		}
		if req.Symbol != "" {
			args = append(args, "--symbol", req.Symbol)
		}
		if req.Force {
			args = append(args, "--force")
		}
		if req.Raw && req.Symbol != "" {
			args = append(args, "--raw")
		}
	}
	if mode == "sync" {
		if req.Limit > 0 {
			args = append(args, "--days", strconv.Itoa(req.Limit))
		}
		if req.Threshold > 0 {
			args = append(args, "--threshold", strconv.FormatFloat(req.Threshold, 'f', -1, 64))
		}
		if req.API {
			args = append(args, "--api")
		}
	}

	cmd := exec.Command("python", args...)

	// دیباگ: نمایش args برای عیب‌یابی
	log.Printf("🔍 BRS collector args: %v", args)
	fmt.Printf("🔍 BRS raw=%v symbol=%q\n", req.Raw, req.Symbol)

	stdout, err := cmd.StdoutPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stdout pipe: " + err.Error()})
		return
	}
	stderr, err := cmd.StderrPipe()
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "stderr pipe: " + err.Error()})
		return
	}

	if err := cmd.Start(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "start failed: " + err.Error()})
		return
	}

	// استریم لاگ به کنسول سرور (همان الگوی run_script.go)
	go streamLogs(stdout)
	go streamLogs(stderr)

	if err := cmd.Wait(); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{
			"error": "collector failed: " + err.Error(),
			"mode":  mode,
		})
		return
	}

	// بعد از دریافت قیمت روزانه بازار، قیمت دارایی‌های خانواده هم خودکار
	// از همان داده‌ها به‌روز می‌شود (دارایی‌های بدون نماد دستی می‌مانند).
	result := gin.H{
		"message": "collector executed",
		"mode":    mode,
	}
	if mode == "daily" || mode == "backfill" {
		if db := config.GetDB(); db != nil {
			updated, missing, syncErr := syncFamilyPricesFromMarket(db, false)
			db.Close()
			if syncErr != nil {
				log.Printf("⚠️ family price sync failed: %v", syncErr)
				result["family_sync"] = "failed"
				result["family_sync_error"] = syncErr.Error()
			} else {
				log.Printf("👨‍👩‍👧‍👦 family prices synced: %d updated, %d manual (%v)", len(updated), len(missing), missing)
				result["family_synced"] = len(updated)
				result["family_manual"] = missing
			}
		}
	}

	c.JSON(http.StatusOK, result)
}
