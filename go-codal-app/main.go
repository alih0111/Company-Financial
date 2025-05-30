package main

import (
	"go-codal-app/handlers"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func main() {
	r := gin.Default()
	r.Use(cors.Default())

	api := r.Group("/api")
	{
		api.GET("/AllCompanyScores", handlers.GetCompanyScores)
		api.GET("/SalesData", handlers.GetSalesData)
		api.GET("/CompanyNames", handlers.GetCompanyNames)
		api.POST("/GetUrl", handlers.GetURL)
		api.GET("/SalesData2", handlers.GetSalesData2)
		api.POST("/GetUrl2", handlers.GetURL2)
		api.GET("/CompanyScores", handlers.GetCompanyScores2)
		api.GET("/StockPriceScore", handlers.StockPriceScore)
		api.POST("/run-script", handlers.RunScript)
		api.POST("/run-script2", handlers.RunScript2)
	}

	r.Run(":5000")
}
