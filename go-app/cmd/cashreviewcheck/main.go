// Exercise the real read-only handler against the published local artifact.
// This diagnostic does not change the application's authenticated route.
package main

import (
	"encoding/json"
	"fmt"
	"math"
	"net/http/httptest"
	"os"

	"github.com/gin-gonic/gin"
	"go-app/handlers/qvt"
)

func main() {
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.GET("/check", qvt.GetCashReviewRanking)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest("GET", "/check", nil))
	if response.Code != 200 {
		fmt.Printf("cash review HTTP %d\n", response.Code)
		os.Exit(1)
	}
	var data map[string]any
	if json.Unmarshal(response.Body.Bytes(), &data) != nil {
		panic("invalid JSON")
	}
	seen := map[string]bool{}
	last := 101.0
	ranked := data["ranked"].([]any)
	unscored := data["unscored"].([]any)
	for i, item := range ranked {
		row := item.(map[string]any)
		id := row["company_id"].(string)
		score := row["score"].(float64)
		if seen[id] || math.IsNaN(score) || math.IsInf(score, 0) || score < 0 || score > 100 || score > last || row["rank"] != float64(i+1) {
			panic("rank contract violated")
		}
		seen[id] = true
		last = score
		classification, ok := row["classification"].(map[string]any)
		if !ok {
			panic("missing evidence classification")
		}
		category := classification["category"].(string)
		if row["review_priority"] != (category == "supported") {
			panic("priority/category mismatch")
		}
		if category == "supported" && (classification["family_verified"] != true || classification["family"] != "general" || len(classification["gaps"].([]any)) != 0 || len(classification["concerns"].([]any)) != 0) {
			panic("unsupported priority evidence")
		}
		if row["symbol"] == "کاسپین" {
			b, _ := json.Marshal(map[string]any{"symbol": row["symbol"], "rank": row["rank"], "score": score, "cash_conversion": row["cash_conversion"], "status": row["status"]})
			fmt.Println(string(b))
		}
	}
	for _, item := range unscored {
		row := item.(map[string]any)
		id := row["company_id"].(string)
		if seen[id] || row["score"] != nil {
			panic("unscored contract violated")
		}
		seen[id] = true
		if row["review_priority"] == true {
			panic("unscored issuer passed priority")
		}
	}
	if data["real_orders"] != float64(0) || data["promotion_ready"] != false {
		panic("unsafe review contract")
	}
	b, _ := json.Marshal(map[string]any{"http_status": response.Code, "ranked": len(ranked), "unscored": len(unscored), "classification": data["classification_summary"], "as_of": data["as_of"], "snapshot_fresh": data["snapshot_fresh"], "real_orders": data["real_orders"]})
	fmt.Println(string(b))
}
