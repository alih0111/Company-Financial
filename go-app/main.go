package main

import (
	"go-app/handlers"
	"go-app/middleware"
	"os"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"*"},
		AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
		AllowHeaders:     []string{"Origin", "Authorization", "Content-Type"},
		ExposeHeaders:    []string{"Content-Length"},
		AllowCredentials: true,
		MaxAge:           12 * time.Hour,
	}))

	api := r.Group("/api")

	r.POST("/api/register/send-code", handlers.SendVerificationCode)
	r.POST("/api/register", handlers.Register)
	api.POST("/login", handlers.Login)

	protected := api.Group("/")
	protected.Use(middleware.AuthMiddleware())
	{
		protected.GET("/AllCompanyScores", handlers.GetCompanyScores)
		protected.GET("/SalesData", handlers.GetSalesData)
		protected.GET("/CompanyNames", handlers.GetCompanyNames)
		protected.POST("/GetUrl", handlers.GetURL)
		protected.GET("/SalesData2", handlers.GetSalesData2)
		protected.POST("/GetUrl2", handlers.GetURL2)
		protected.GET("/CompanyScores", handlers.GetCompanyScores2)
		protected.GET("/StockPriceScore", handlers.StockPriceScore)
		protected.POST("/run-script", handlers.RunScript)
		protected.POST("/run-script2", handlers.RunScript2)
		protected.POST("/fetchAllData", handlers.BulkFetch)
		protected.GET("/FetchFullPE", handlers.RunScriptPE)
		protected.POST("/users/get-items", handlers.AddViewedItem)

		// تاریخچه‌ی قیمت نماد
		protected.GET("/price-history", handlers.GetPriceHistory)

		// خروجی CSV امتیازات
		protected.GET("/export/scores", handlers.ExportScoresCSV)

		// کالکتور قیمت BRS (فقط ادمین) → py/brs_prices.py
		protected.POST("/brs/collect", handlers.RunBrsCollector)

		protected.GET("/summary", handlers.GetAIStockSummary)
		protected.GET("/detail", handlers.GetAIStockDetail)
		protected.POST("/analyze", handlers.AnalyzeTopStocksWithAI)

		protected.GET("/portfolio", handlers.GetPortfolio)
		protected.POST("/portfolio", handlers.UpsertHolding)
		protected.DELETE("/portfolio/:company_id", handlers.DeleteHolding)

		// دارایی خانواده (فقط ادمین) → جایگزین اکسل «دارایی»
		protected.GET("/family/assets", handlers.GetFamilyAssets)
		protected.POST("/family/assets", handlers.CreateFamilyAsset)
		protected.POST("/family/people", handlers.CreateFamilyPerson)
		protected.POST("/family/prices", handlers.SaveFamilyPrices)
		protected.POST("/family/sync-prices", handlers.SyncFamilyPrices)
		protected.PUT("/family/holdings", handlers.UpsertFamilyHolding)
		protected.DELETE("/family/holdings", handlers.DeleteFamilyHolding)
		protected.PUT("/family/account", handlers.UpdateFamilyAccount)
		protected.GET("/family/cashflows", handlers.GetFamilyCashFlows)
		protected.POST("/family/cashflows", handlers.AddFamilyCashFlow)
		protected.DELETE("/family/cashflows/:id", handlers.DeleteFamilyCashFlow)
		protected.GET("/family/history", handlers.GetFamilyHistory)
	}

	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}
	r.Run(":" + port)
}
