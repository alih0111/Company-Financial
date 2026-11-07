package main

import (
	"context"
	"errors"
	"go-app/config"
	"go-app/handlers"
	qvt "go-app/handlers/qvt"
	"go-app/middleware"
	"log"
	"net"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/gin-contrib/cors"
	"github.com/gin-gonic/gin"
)

func newRouter() (*gin.Engine, error) {
	r := gin.New()
	r.Use(middleware.RequestSafety())
	if err := r.SetTrustedProxies(config.CSVEnv("TRUSTED_PROXIES")); err != nil {
		return nil, err
	}
	r.Use(middleware.SecurityHeaders(), middleware.RateLimit(600, time.Minute), middleware.OriginGuard())
	if origins := config.CSVEnv("CORS_ALLOWED_ORIGINS"); len(origins) > 0 {
		r.Use(cors.New(cors.Config{
			AllowOrigins:     origins,
			AllowMethods:     []string{"GET", "POST", "PUT", "DELETE", "OPTIONS"},
			AllowHeaders:     []string{"Origin", "Authorization", "Content-Type"},
			ExposeHeaders:    []string{"Content-Length"},
			AllowCredentials: false,
			MaxAge:           12 * time.Hour,
		}))
	}

	api := r.Group("/api")

	// Observability only: read mode + backend availability. No secrets.
	r.GET("/api/health/live", func(c *gin.Context) { c.JSON(http.StatusOK, gin.H{"status": "ok"}) })
	r.GET("/api/health/ready", handlers.GetReadiness)
	r.GET("/api/strategy/summary", middleware.RateLimit(30, time.Minute), handlers.GetPublicStrategySummary)
	r.GET("/api/config", func(c *gin.Context) {
		c.JSON(http.StatusOK, gin.H{"registration_enabled": config.RegistrationEnabled() && config.SMTPConfigured()})
	})

	// نوار قیمت لحظه‌ای صفحه‌ی اصلی (عمومی — TSETMC + TGJU با کش سروری)
	api.GET("/market/ticker", middleware.RateLimit(120, time.Minute), handlers.GetMarketTicker)

	auth := api.Group("", middleware.RateLimit(20, time.Minute), middleware.RequestBodyLimit())
	auth.POST("/register/send-code", middleware.RateLimit(5, time.Hour), middleware.ConcurrencyLimit(2), handlers.SendVerificationCode)
	passwordWork := middleware.ConcurrencyLimit(4)
	auth.POST("/register", passwordWork, handlers.Register)
	auth.POST("/login", passwordWork, handlers.Login)

	protected := api.Group("/")
	protected.Use(middleware.RateLimit(300, time.Minute))
	protected.Use(middleware.AuthMiddleware(), middleware.RequestBodyLimit())
	admin := protected.Group("", middleware.AdminOnly())
	data := protected.Group("", middleware.DataRateLimit(), middleware.DataConcurrency(), middleware.DataAccess())
	protected.GET("/data-access", middleware.UserRateLimit(12, time.Minute), handlers.GetDataAccess)
	admin.GET("/admin/data-access", handlers.ListDataAccess)
	admin.GET("/admin/data-access/:username", handlers.GetDataAccess)
	admin.PUT("/admin/data-access/:username", handlers.SetDataAccess)
	aiQuota := middleware.UserRateLimit(30, time.Hour)
	{
		protected.GET("/health/shadow", handlers.GetShadowHealth)
		protected.POST("/logout", handlers.Logout)
		protected.GET("/me", func(c *gin.Context) {
			c.JSON(http.StatusOK, gin.H{"username": c.GetString("username"), "isAdmin": c.GetBool("isAdmin")})
		})
		admin.GET("/AllCompanyScores", handlers.GetCompanyScores)
		data.GET("/SalesData", handlers.GetSalesData)
		data.GET("/CompanyNames", handlers.GetCompanyNames)
		data.GET("/companies", handlers.GetCompanyDirectory)
		admin.POST("/GetUrl", handlers.GetURL)
		data.GET("/SalesData2", handlers.GetSalesData2)
		admin.POST("/GetUrl2", handlers.GetURL2)
		data.GET("/CompanyScores", handlers.GetCompanyScores2)
		data.GET("/StockPriceScore", handlers.StockPriceScore)
		admin.POST("/run-script", middleware.RetiredCollector(), handlers.RunScript)
		admin.POST("/run-script2", middleware.RetiredCollector(), handlers.RunScript2)
		admin.POST("/fetchAllData", middleware.RetiredCollector(), handlers.BulkFetch)
		admin.GET("/FetchFullPE", middleware.RetiredCollector(), handlers.RunScriptPE)
		protected.POST("/users/get-items", handlers.AddViewedItem)

		// تاریخچه‌ی قیمت نماد
		data.GET("/price-history", handlers.GetPriceHistory)

		// شاخص‌های بازار + صندوق‌های طلا/کالا (صفحه‌ی «بازار»)
		data.GET("/market/assets", handlers.GetMarketAssets)
		admin.POST("/market/collect", handlers.RunMarketAssetsCollector)

		// تحلیل QVT نسخه ۲ (آزمایشی) — فقط‌خواندنی روی آرتیفکت‌های پایلوت
		admin.GET("/qvt-v2", qvt.GetQvtV2Report)

		// «کشف فرصت‌ها» QVT — همان snapshot، گروه‌بندی مقایسه‌پذیر و لایه‌های پارتو (فقط‌خواندنی)
		admin.GET("/qvt-v2/discovery", qvt.GetQvtV2Discovery)

		// رتبه‌بندی سادهٔ اولویت بررسی (۰..۱۰۰ آزمایشی) — همان snapshot، فقط‌خواندنی
		admin.GET("/qvt-v2/ranking", qvt.GetQvtV2Ranking)
		admin.GET("/ranking/cash-review", qvt.GetCashReviewRanking)
		admin.GET("/qvt-v2/paper", qvt.GetQvtV2Paper)

		// خروجی CSV امتیازات
		admin.GET("/export/scores", handlers.ExportScoresCSV)

		// کالکتور قیمت BRS (فقط ادمین) → py/brs_prices.py
		admin.POST("/brs/collect", handlers.RunBrsCollector)

		// sync مبتنی بر discovery کدال (فقط ادمین) → py/sync_codal.py
		admin.POST("/sync-codal", handlers.RunSyncCodal)
		admin.POST("/sync-codal/jobs", handlers.StartCodalSyncJob)
		admin.GET("/sync-codal/jobs/active", handlers.GetActiveCodalJob)
		admin.GET("/sync-codal/jobs/:job_id", handlers.GetCodalJob)
		admin.POST("/sync-codal/jobs/:job_id/captcha", handlers.SubmitCodalCaptcha)
		admin.POST("/sync-codal/jobs/:job_id/captcha/refresh", handlers.RefreshCodalCaptcha)
		admin.POST("/sync-codal/jobs/:job_id/captcha/resume", handlers.ResumeCodalChallenge)
		admin.POST("/sync-codal/jobs/:job_id/cancel", handlers.CancelCodalJob)

		// وضعیت جمع‌آوری خودکار کدال (فقط ادمین)
		admin.GET("/sync-codal/status", handlers.GetCodalSyncStatus)

		// به‌روزرسانی دستی امتیازهای «غربال بازار» (فقط ادمین) → orchestrate_refresh.py
		// بدون این دکمه هیچ زمان‌بندی‌ای امتیازها را بازمحاسبه نمی‌کند.
		admin.POST("/admin/analytics/refresh", handlers.RefreshAnalyticsScores)

		// اجرای دستی چرخهٔ دریافت Codal و بازسازی رتبه‌بندی P1/P3 (فقط ادمین)
		admin.POST("/admin/ranking/refresh", handlers.StartRankingRefresh)
		admin.POST("/admin/factormix/ranking/refresh", handlers.RefreshFactorMixRanking)
		data.GET("/factormix/ranking", handlers.GetFactorMixRanking)
		data.POST("/factormix/plan", handlers.PlanFactorMix)
		admin.GET("/reportflow", handlers.GetReportFlow)
		admin.POST("/admin/reportflow/review", handlers.ReviewReportFlow)
		admin.GET("/admin/ranking/refresh/status", handlers.GetRankingRefreshStatus)

		// تلاش دوبارهٔ دستی اجرای سبد کاغذی (فقط ادمین) → experimental_paper.py + paper_month_trial.py
		admin.POST("/admin/paper-trial/refresh", handlers.StartPaperTrialRefresh)
		admin.GET("/admin/paper-trial/refresh/status", handlers.GetPaperTrialRefreshStatus)

		data.GET("/summary", handlers.GetAIStockSummary)
		data.GET("/detail", handlers.GetAIStockDetail)

		// صورت‌های مالی کامل (سود و زیان، ترازنامه، جریان نقد عملیاتی)
		data.GET("/financial-statements", handlers.GetFinancialStatements)
		admin.POST("/analyze", middleware.RateLimit(10, time.Hour), handlers.AnalyzeTopStocksWithAI)

		data.GET("/portfolio", handlers.GetPortfolio)
		protected.POST("/portfolio", handlers.UpsertHolding)
		protected.DELETE("/portfolio/:company_id", handlers.DeleteHolding)

		// دستیار چت سرمایه‌گذاری (مبتنی بر دیتای امتیاز کمی)
		data.POST("/chat", aiQuota, handlers.Chat)

		// همان چت با رویدادهای پیشرفت (SSE)
		data.POST("/chat/stream", aiQuota, handlers.ChatStream)

		// بررسی سلامت اتصال مدل زبانی (بدون افشای کلید)
		admin.GET("/health/ai", middleware.RateLimit(5, time.Hour), handlers.GetAIHealth)

		// دارایی خانواده (فقط ادمین) → جایگزین اکسل «دارایی»
		admin.GET("/family/assets", handlers.GetFamilyAssets)
		admin.POST("/family/assets", handlers.CreateFamilyAsset)
		admin.POST("/family/people", handlers.CreateFamilyPerson)
		admin.POST("/family/prices", handlers.SaveFamilyPrices)
		admin.POST("/family/sync-prices", handlers.SyncFamilyPrices)
		admin.PUT("/family/holdings", handlers.UpsertFamilyHolding)
		admin.DELETE("/family/holdings", handlers.DeleteFamilyHolding)
		admin.PUT("/family/account", handlers.UpdateFamilyAccount)
		admin.GET("/family/cashflows", handlers.GetFamilyCashFlows)
		admin.POST("/family/cashflows", handlers.AddFamilyCashFlow)
		admin.DELETE("/family/cashflows/:id", handlers.DeleteFamilyCashFlow)
		admin.GET("/family/history", handlers.GetFamilyHistory)

		// اتصال سبد هر شخص به کارگزاری آگاه (فقط ادمین)
		admin.GET("/family/broker", handlers.GetFamilyBrokerAccounts)
		admin.PUT("/family/broker", handlers.UpsertFamilyBrokerAccount)
		admin.DELETE("/family/broker", handlers.DeleteFamilyBrokerAccount)
		admin.POST("/family/sync-broker", handlers.StartFamilyBrokerSync)
		admin.GET("/family/sync-broker/status", handlers.GetFamilyBrokerJob)
		admin.POST("/family/sync-broker/captcha", handlers.SubmitFamilyBrokerCaptcha)
	}
	if err := serveFrontend(r, os.Getenv("FRONTEND_DIR")); err != nil {
		return nil, err
	}
	return r, nil
}

func main() {
	if len(os.Args) > 1 && os.Args[1] == "admin" {
		if err := createAdmin(os.Args[2:], os.Stdin); err != nil {
			log.Fatal(err)
		}
		return
	}
	if len(os.Args) == 2 && os.Args[1] == "healthcheck" {
		client := &http.Client{Timeout: 5 * time.Second}
		port := os.Getenv("PORT")
		if port == "" {
			port = "5000"
		}
		res, err := client.Get("http://127.0.0.1:" + port + "/api/health/ready")
		if err != nil {
			os.Exit(1)
		}
		defer res.Body.Close()
		if res.StatusCode != http.StatusOK {
			os.Exit(1)
		}
		return
	}
	if err := config.ValidateRuntime(); err != nil {
		log.Fatal(err)
	}
	if config.Production() {
		gin.SetMode(gin.ReleaseMode)
	}
	r, err := newRouter()
	if err != nil {
		log.Fatal(err)
	}
	qvt.StartQvtPaperObserver()
	handlers.StartCodalAutoSync()
	handlers.StartReportFlowObserver()

	port := os.Getenv("PORT")
	if port == "" {
		port = "5000"
	}
	server := &http.Server{
		Addr: net.JoinHostPort(config.ListenHost(), port), Handler: r,
		ReadHeaderTimeout: 10 * time.Second, ReadTimeout: 30 * time.Second,
		IdleTimeout: 90 * time.Second, MaxHeaderBytes: 32 << 10,
		// WriteTimeout stays unset for SSE chat and long-running admin jobs.
	}
	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()
	go func() {
		log.Printf("RFA listening on %s", server.Addr)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatal(err)
		}
	}()
	<-ctx.Done()
	shutdown, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	if err := server.Shutdown(shutdown); err != nil {
		log.Print("HTTP shutdown: ", err)
	}
}
