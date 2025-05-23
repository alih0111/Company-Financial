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
		api.GET("/SalesData", handlers.GetSalesData)
		api.GET("/SalesData2", handlers.GetSalesData2)
		api.GET("/CompanyScores", handlers.GetCompanyScores)
		api.GET("/CompanyNames", handlers.GetCompanyNames)
		api.POST("/GetUrl", handlers.GetURL)
		api.POST("/GetUrl2", handlers.GetURL2)
	}

	r.Run(":5000")
}
