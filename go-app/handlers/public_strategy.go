package handlers

import (
	"encoding/json"
	"github.com/gin-gonic/gin"
	"io"
	"os"
	"path/filepath"
)

func pickFields(value map[string]any, keys ...string) gin.H {
	result := gin.H{}
	for _, key := range keys {
		if item, ok := value[key]; ok {
			result[key] = item
		}
	}
	return result
}

// Public output contains verified aggregate results only. No trades, universe,
// holdings, daily NAV, frozen inputs, source paths or download links are copied.
func publicStrategySummary(raw []byte) (gin.H, error) {
	var source struct {
		Schema int              `json:"schema_version"`
		Mode   string           `json:"mode"`
		Cases  []map[string]any `json:"cases"`
	}
	if err := json.Unmarshal(raw, &source); err != nil {
		return nil, err
	}
	if source.Schema != 1 || source.Mode != "historical_replay" || len(source.Cases) != 2 {
		return nil, os.ErrInvalid
	}
	cases := []gin.H{}
	for _, item := range source.Cases {
		monthly, ok := item["monthly15"].(map[string]any)
		if !ok {
			// The older 1402 case has no monthly overlay. Never substitute the
			// quarterly experiment's results for the selected monthly strategy.
			continue
		}
		account, ok := monthly["account"].(map[string]any)
		if !ok {
			return nil, os.ErrInvalid
		}
		annual, ok := monthly["annual"].([]any)
		if !ok {
			return nil, os.ErrInvalid
		}
		years := []gin.H{}
		for _, entry := range annual {
			year, ok := entry.(map[string]any)
			if !ok {
				return nil, os.ErrInvalid
			}
			years = append(years, pickFields(year, "year", "start", "end", "initial_toman", "final_toman", "return_fraction"))
		}
		view := pickFields(item, "id", "start_year", "start", "as_of", "initial_toman")
		view["account"] = pickFields(account, "start", "end", "final_toman", "total_return", "max_drawdown", "cagr")
		view["annual"] = years
		cases = append(cases, view)
	}
	if len(cases) == 0 {
		return nil, os.ErrInvalid
	}
	return gin.H{"strategy_id": "RFA-FactorMix-033-M15-Buffer8-v1.0.0", "mode": "historical_summary", "cases": cases}, nil
}

func GetPublicStrategySummary(c *gin.Context) {
	directory := os.Getenv("PUBLIC_ARTIFACTS_DIR")
	if directory == "" {
		root, err := analyticsRepoRoot()
		if err != nil {
			c.Status(503)
			return
		}
		directory = filepath.Join(root, "client", "public")
	}
	confined, err := os.OpenRoot(directory)
	if err != nil {
		c.Status(503)
		return
	}
	defer confined.Close()
	file, err := confined.Open("strategies/factormix-033/performance/performance.json")
	if err != nil {
		c.Status(503)
		return
	}
	defer file.Close()
	raw, err := io.ReadAll(io.LimitReader(file, 8<<20))
	if err != nil {
		c.Status(503)
		return
	}
	summary, err := publicStrategySummary(raw)
	if err != nil {
		c.Status(503)
		return
	}
	c.JSON(200, summary)
}
