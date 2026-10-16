package qvt

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gin-gonic/gin"
)

// A review publication certifies bytes and arithmetic, not trading readiness.
// Read only from the repository-owned artifact root; fail closed on corruption.
func readCashReview(root string) (map[string]any, error) {
	root, err := filepath.Abs(root)
	if err != nil {
		return nil, err
	}
	pointer := readResearchMap(filepath.Join(root, "owner_current_latest.json"))
	run, err := filepath.Abs(stringField(pointer, "run_path"))
	if err != nil || stringField(pointer, "run_path") == "" {
		return nil, fmt.Errorf("missing publication")
	}
	rel, err := filepath.Rel(root, run)
	if err != nil || rel == "." || rel == ".." || filepath.IsAbs(rel) || strings.HasPrefix(rel, ".."+string(os.PathSeparator)) {
		return nil, fmt.Errorf("outside artifact root")
	}
	publication := readResearchMap(filepath.Join(run, "publication.json"))
	raw, err := os.ReadFile(filepath.Join(run, "ranking.json"))
	if err != nil || len(raw) > 4*1024*1024 {
		return nil, fmt.Errorf("missing ranking")
	}
	hash := sha256.Sum256(raw)
	digest := hex.EncodeToString(hash[:])
	if publication["status"] != "passed" || publication["real_orders"] != float64(0) ||
		publication["bundle_sha256"] != digest || pointer["bundle_sha256"] != digest {
		return nil, fmt.Errorf("publication hash mismatch")
	}
	var bundle map[string]any
	if json.Unmarshal(raw, &bundle) != nil || bundle["version"] != "cash-backed-review-v1" ||
		bundle["mode"] != "development_review" || bundle["promotion_ready"] != false || bundle["real_orders"] != float64(0) {
		return nil, fmt.Errorf("invalid review contract")
	}
	return bundle, nil
}

func GetCashReviewRanking(c *gin.Context) {
	bundle, err := readCashReview(filepath.Join("..", "ranking_research", "output"))
	if err != nil {
		c.JSON(http.StatusServiceUnavailable, gin.H{"error": "رتبه‌بندی جدید هنوز آماده یا تأیید نشده است."})
		return
	}
	zone, err := time.LoadLocation("Asia/Tehran")
	if err != nil {
		zone = time.FixedZone("Tehran", 12600)
	}
	day, err := time.ParseInLocation("2006-01-02", stringField(bundle, "as_of"), zone)
	age := time.Now().In(zone).Sub(day).Hours() / 24
	bundle["snapshot_fresh"] = err == nil && age >= 0 && age < 4
	c.Header("Cache-Control", "no-store")
	c.JSON(http.StatusOK, bundle)
}
