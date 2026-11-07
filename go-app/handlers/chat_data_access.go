package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"go-app/config"
	"go-app/dataaccess"
	"go-app/integration"
	"time"
)

func chargeChatOutput(c *gin.Context, out string, targets []string) error {
	if c.GetBool("isAdmin") {
		return nil
	}
	cost, err := dataaccess.JSONCost([]byte(out))
	if err != nil {
		cost = dataaccess.Cost{Bytes: int64(len(out)), Records: 50}
	}
	cost.Requests = 1
	cost.Targets = append(cost.Targets, targets...)
	// Never place an enormous tool result into the model context. Do not fall
	// back to another data route if this check or the durable budget denies it.
	if len(out) > 64<<10 || len(cost.Targets) > 50 {
		return &dataaccess.Denied{Reason: "tool_output_limit", Reset: time.Now().Add(time.Minute)}
	}
	db, err := config.GetPG()
	if err != nil {
		return fmt.Errorf("data access check unavailable")
	}
	ctx, cancel := context.WithTimeout(c.Request.Context(), 5*time.Second)
	defer cancel()
	_, err = dataaccess.Reserve(ctx, db, c.GetString("username"), c.ClientIP(), cost)
	return err
}

func limitedChatRows(c *gin.Context, message string, rows []integration.AllScoreInputRow) ([]integration.AllScoreInputRow, error) {
	if c.GetBool("isAdmin") {
		return rows, nil
	}
	selected := []integration.AllScoreInputRow{}
	seen := map[string]bool{}
	add := func(row integration.AllScoreInputRow) {
		key := row.CanonicalID
		if key == "" {
			key = row.LegacyCompanyID
		}
		if !seen[key] {
			selected = append(selected, row)
			seen[key] = true
		}
	}
	mentions := findCompanyMentions(message, rows)
	if len(mentions) > 5 {
		return nil, fmt.Errorf("هر پرسش حداکثر پنج شرکت را می‌پذیرد")
	}
	for _, mention := range mentions {
		add(mention.row)
	}
	ranked := rowsSortedByScore(rows)
	for i := 0; i < 5 && i < len(ranked); i++ {
		add(ranked[i])
	}
	view := []gin.H{}
	for _, row := range selected {
		identity := row.Symbol
		if identity == "" {
			identity = row.CompanyName
		}
		view = append(view, gin.H{"symbol": identity, "score": row.QuantScore})
	}
	raw, _ := json.Marshal(view)
	if err := chargeChatOutput(c, string(raw), nil); err != nil {
		return nil, err
	}
	return selected, nil
}
