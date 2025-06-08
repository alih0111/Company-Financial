package main

import (
	"go-app/handlers"
	"go-app/middleware"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()

	r.Use(cors.New(cors.Config{
		AllowOrigins:     []string{"http://localhost:5173"}, // frontend origin
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
	}

	r.Run(":5000")
}
