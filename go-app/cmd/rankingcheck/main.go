// Local handler diagnostic. The application endpoint keeps authentication.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"net/http/httptest"
	"os"

	"github.com/gin-gonic/gin"
	"github.com/joho/godotenv"
	"go-app/handlers/qvt"
)

func main() {
	output := flag.String("output", "", "save the full handler response")
	checkRelated := flag.Bool("check-related", false, "also verify the report and discovery handlers")
	checkPaper := flag.Bool("check-paper", false, "also verify the read-only forward paper summary")
	flag.Parse()
	_ = godotenv.Load()
	gin.SetMode(gin.ReleaseMode)
	router := gin.New()
	router.GET("/ranking", qvt.GetQvtV2Ranking)
	response := httptest.NewRecorder()
	router.ServeHTTP(response, httptest.NewRequest("GET", "/ranking", nil))
	if response.Code != 200 {
		fmt.Printf("ranking HTTP %d: %s\n", response.Code, response.Body.String())
		os.Exit(1)
	}
	var body map[string]any
	if err := json.Unmarshal(response.Body.Bytes(), &body); err != nil {
		panic(err)
	}
	if *output != "" {
		if err := os.WriteFile(*output, response.Body.Bytes(), 0600); err != nil {
			panic(err)
		}
	}
	statuses := map[string]int{}
	for _, item := range body["ranked"].([]any) {
		row := item.(map[string]any)
		statuses[row["status"].(string)]++
	}
	summary := map[string]any{"as_of": body["as_of"], "universe": body["universe"], "freshness": body["freshness"], "statuses": statuses}
	text, _ := json.Marshal(summary)
	fmt.Println(string(text))
	if *checkPaper {
		paperRouter := gin.New()
		paperRouter.GET("/paper", qvt.GetQvtV2Paper)
		checked := httptest.NewRecorder()
		paperRouter.ServeHTTP(checked, httptest.NewRequest("GET", "/paper", nil))
		if checked.Code != 200 {
			fmt.Printf("paper HTTP %d: %s\n", checked.Code, checked.Body.String())
			os.Exit(1)
		}
		var document map[string]any
		if err := json.Unmarshal(checked.Body.Bytes(), &document); err != nil {
			panic(err)
		}
		fmt.Printf("paper HTTP 200; decision=%v; status=%v; real_orders=%v\n", document["decision_id"], document["status"], document["real_orders"])
		if history, ok := document["historical"].(map[string]any); ok {
			fmt.Printf("historical scope=%v; dates=%v; full_qvt_status=%v\n", history["scope"], history["n_dates"], history["full_qvt_status"])
		}
	}
	if *checkRelated {
		for _, related := range []struct {
			name    string
			handler gin.HandlerFunc
		}{{"report", qvt.GetQvtV2Report}, {"discovery", qvt.GetQvtV2Discovery}} {
			checkRouter := gin.New()
			checkRouter.GET("/check", related.handler)
			checked := httptest.NewRecorder()
			checkRouter.ServeHTTP(checked, httptest.NewRequest("GET", "/check", nil))
			if checked.Code != 200 {
				fmt.Printf("%s HTTP %d: %s\n", related.name, checked.Code, checked.Body.String())
				os.Exit(1)
			}
			var document map[string]any
			if err := json.Unmarshal(checked.Body.Bytes(), &document); err != nil {
				panic(err)
			}
			if document["as_of"] != body["as_of"] {
				fmt.Printf("%s snapshot differs from ranking\n", related.name)
				os.Exit(1)
			}
			fmt.Printf("%s HTTP 200; same snapshot\n", related.name)
		}
	}
}
