package handlers

import (
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"go-app/integration"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestLimitedMarketListCannotReturnAllFactors(t *testing.T) {
	rows := []integration.AllScoreInputRow{}
	for i := 0; i < 75; i++ {
		rows = append(rows, integration.AllScoreInputRow{LegacyCompanyID: fmt.Sprint(i), CanonicalID: fmt.Sprint(i), CompanyName: fmt.Sprintf("Company %02d", i), Symbol: fmt.Sprintf("S%02d", i), QuantScore: float64(i), FactorRaw: map[string]float64{"PE": 7}})
	}
	for _, query := range []string{"?limit=999999", "?page=2", "?q=S00", "?companyName=Company%2000", "?page_size=999", "?page=0", "?page=1&page=2"} {
		w := httptest.NewRecorder()
		c, _ := gin.CreateTestContext(w)
		c.Request = httptest.NewRequest("GET", "/api/summary"+query, nil)
		writeLimitedSummary(c, rows)
		if strings.Contains(query, "page_size=999") || strings.Contains(query, "page=0") || strings.Contains(query, "page=1&page=2") {
			if w.Code != 400 {
				t.Fatal("invalid pagination accepted")
			}
			continue
		}
		var body []map[string]any
		if json.Unmarshal(w.Body.Bytes(), &body) != nil || len(body) > 20 {
			t.Fatal("full list escaped page boundary")
		}
		if strings.Contains(query, "Company%2000") {
			if len(body) != 1 {
				t.Fatal("exact company selection did not constrain the response")
			}
		} else {
			for _, row := range body {
				if _, exists := row["pe_rank"]; exists {
					t.Fatal("factor details included in market bulk listing")
				}
			}
		}
		if query == "?page=2" && body[0]["symbol"] != "S54" {
			t.Fatal("pagination is not stable")
		}
	}
}

func TestPublicSummaryCannotCopyUnknownPrivateFields(t *testing.T) {
	raw := []byte(`{"schema_version":1,"mode":"historical_replay","cases":[{"id":"one","start_year":1401,"secret":"PRIVATE_DATA","path":["PRIVATE_DATA"],"monthly15":{"account":{"final_toman":200,"total_return":1,"holdings":["PRIVATE_DATA"]},"annual":[{"year":1401,"return_fraction":1,"trades":["PRIVATE_DATA"]}],"downloads":{"archive":"PRIVATE_DATA"}}},{"id":"two","monthly15":{"account":{},"annual":[]}}]}`)
	summary, err := publicStrategySummary(raw)
	if err != nil {
		t.Fatal(err)
	}
	body, _ := json.Marshal(summary)
	if strings.Contains(string(body), "PRIVATE_DATA") || strings.Contains(string(body), "downloads") || strings.Contains(string(body), "holdings") {
		t.Fatal("private payload was copied into public summary")
	}
}

func TestServerPlanPreservesRegisteredBufferAndBand(t *testing.T) {
	ranking := factorMixSnapshot{Date: "2026-11-07", ComputedAt: "test", MarketDate: "2026-11-07"}
	for i := 1; i <= 10; i++ {
		rank := i
		score := float64(11 - i)
		ranking.Rows = append(ranking.Rows, factorMixRow{Symbol: fmt.Sprint(i), Rank: &rank, Score: &score})
	}
	plan, err := buildFactorMixPlan(ranking, []planHolding{{"8", 200}, {"9", 200}}, 600)
	if err != nil {
		t.Fatal(err)
	}
	rows := plan["rows"].([]gin.H)
	if len(rows) != 6 || plan["changes"] != 5 || plan["nav_toman"] != float64(1000) {
		t.Fatalf("unexpected proposal: %+v", plan)
	}
	for _, row := range rows {
		if row["symbol"] == "8" && row["action"] != "HOLD" {
			t.Fatal("rank-eight buffer changed")
		}
		if row["symbol"] == "9" && row["action"] != "SELL" {
			t.Fatal("out-of-buffer holding was retained")
		}
	}
	for _, holdings := range [][]planHolding{{{"1", 0}}, {{"unknown", 100}}, {{"1", 100}, {"1", 100}}} {
		if _, err = buildFactorMixPlan(ranking, holdings, 100); err == nil {
			t.Fatal("invalid portfolio accepted")
		}
	}
}
