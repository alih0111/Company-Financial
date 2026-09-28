package handlers

import (
	"bytes"
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"

	"go-app/config"

	"github.com/gin-gonic/gin"
)

// ─────────────────────────────────────────────────────────────────────
// اتصال سبد هر شخص به کارگزاری آگاه (خواندن از پنل وب)
//   * اعتبارنامه رمزنگاری‌شده ذخیره می‌شود (AES-GCM).
//   * هر سینک یک job پس‌زمینه است؛ کاربر کد امنیتی را در پنجره مرورگر
//     وارد می‌کند. کلاینت با job_id وضعیت را poll می‌کند.
//   * نتیجه: جایگزینی کامل holdings + مانده نقدی آن شخص.
// ─────────────────────────────────────────────────────────────────────

const (
	agahLoginURL     = "https://online.agah.com/login"
	agahPortfolioURL = "https://online.agah.com/auth/portfolio/asset"
)

type familyBrokerAccountRow struct {
	PersonID     int        `json:"person_id"`
	PersonName   string     `json:"person_name"`
	Broker       string     `json:"broker"`
	Username     string     `json:"username"`
	HasSecret    bool       `json:"has_secret"`
	IsActive     bool       `json:"is_active"`
	LastSyncedAt *time.Time `json:"last_synced_at"`
	LastStatus   string     `json:"last_status"`
	LastError    string     `json:"last_error"`
}

type agahHolding struct {
	Symbol      string  `json:"symbol"`
	Name        string  `json:"name"`
	ISIN        string  `json:"isin"`
	NSCID       string  `json:"nscid"`
	Quantity    float64 `json:"quantity"`
	AvgBuyPrice float64 `json:"avg_buy_price"`
	LastPrice   float64 `json:"last_price"`
	CostBasis   float64 `json:"cost_basis"`
	MarketValue float64 `json:"market_value"`
	Gain        float64 `json:"gain"`
	GainPercent float64 `json:"gain_percent"`
	Sector      string  `json:"sector"`
	State       string  `json:"state"`
}

type agahCash struct {
	Available              *float64 `json:"available"`
	LastBalance            *float64 `json:"last_balance"`
	TradableT1             *float64 `json:"tradable_t1"`
	TradableT2             *float64 `json:"tradable_t2"`
	PayableWithoutCreditT0 *float64 `json:"payable_without_credit_t0"`
	PayableWithCreditT1    *float64 `json:"payable_with_credit_t1"`
	PayableWithCreditT2    *float64 `json:"payable_with_credit_t2"`
	Credit                 *float64 `json:"credit"`
	Block                  *float64 `json:"block"`
}

type agahResult struct {
	OK             bool           `json:"ok"`
	Holdings       []agahHolding  `json:"holdings"`
	Cash           agahCash       `json:"cash"`
	Error          string         `json:"error"`
	NeedsDiscovery bool           `json:"needs_discovery"`
	Source         string         `json:"source"`
	Summary        map[string]any `json:"summary"`
	Login          map[string]any `json:"login,omitempty"`
	Captured       map[string]any `json:"captured"`
}

// ────────────────────────────── job store ──────────────────────────────

type brokerSyncJob struct {
	ID        string      `json:"job_id"`
	PersonID  int         `json:"person_id"`
	State     string      `json:"state"` // running | done | error
	Message   string      `json:"message"`
	StartedAt time.Time   `json:"started_at"`
	UpdatedAt time.Time   `json:"updated_at"`
	Result    *agahResult `json:"result,omitempty"`
	// کپچای در انتظار ورود دستی (فقط هنگام running)
	NeedsCaptcha bool   `json:"needs_captcha,omitempty"`
	CaptchaImage string `json:"captcha_image,omitempty"`
	// مسیر تبادل فایل کپچا/پاسخ با کالکتور؛ برای کلاینت ارسال نمی‌شود
	exchangeDir string `json:"-"`
}

var (
	brokerJobsMu sync.Mutex
	brokerJobs   = map[string]*brokerSyncJob{}
	brokerJobSeq int
)

func newBrokerJob(personID int) *brokerSyncJob {
	brokerJobsMu.Lock()
	defer brokerJobsMu.Unlock()
	// jobهای تمام‌شده قدیمی را حذف کن تا map رشد نکند.
	for id, j := range brokerJobs {
		if j.State != "running" && time.Since(j.UpdatedAt) > time.Hour {
			delete(brokerJobs, id)
		}
	}
	brokerJobSeq++
	id := fmt.Sprintf("agah-%d-%d", personID, brokerJobSeq)
	job := &brokerSyncJob{ID: id, PersonID: personID, State: "running", Message: "در حال اجرا", StartedAt: time.Now(), UpdatedAt: time.Now()}
	brokerJobs[id] = job
	return job
}

func getBrokerJob(id string) *brokerSyncJob {
	brokerJobsMu.Lock()
	defer brokerJobsMu.Unlock()
	return brokerJobs[id]
}

// runningBrokerPersonIDs اشخاصی که سینک فعال دارند را برمی‌گرداند.
func runningBrokerPersonIDs() map[int]bool {
	brokerJobsMu.Lock()
	defer brokerJobsMu.Unlock()
	out := map[int]bool{}
	for _, j := range brokerJobs {
		if j.State == "running" {
			out[j.PersonID] = true
		}
	}
	return out
}

func updateBrokerJob(id, state, message string, result *agahResult) {
	brokerJobsMu.Lock()
	defer brokerJobsMu.Unlock()
	if job, ok := brokerJobs[id]; ok {
		job.State = state
		job.Message = message
		job.Result = result
		job.UpdatedAt = time.Now()
	}
}

// ────────────────────────────── exported handlers ──────────────────────────────

func GetFamilyBrokerAccounts(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	getFamilyBrokerAccountsPG(c)
}

func UpsertFamilyBrokerAccount(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	upsertFamilyBrokerAccountPG(c)
}

func DeleteFamilyBrokerAccount(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	deleteFamilyBrokerAccountPG(c)
}

func StartFamilyBrokerSync(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	startFamilyBrokerSyncPG(c)
}

func GetFamilyBrokerJob(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	getFamilyBrokerJobPG(c)
}

// ────────────────────────────── list / config ──────────────────────────────

func getFamilyBrokerAccountsPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}
	ctx, cancel := familyPGTimeout()
	defer cancel()

	rows, err := db.QueryContext(ctx, `
		SELECT p.person_id, p.name, b.broker, b.username,
		       (b.secret_cipher IS NOT NULL AND b.secret_cipher <> '') AS has_secret,
		       b.is_active, b.last_synced_at, COALESCE(b.last_status,''), COALESCE(b.last_error,'')
		FROM family.people p
		LEFT JOIN family.broker_accounts b ON b.person_id = p.person_id
		WHERE p.is_active = true
		ORDER BY p.sort_order, p.person_id`)
	if err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "query: " + err.Error()})
		return
	}
	defer rows.Close()

	out := []familyBrokerAccountRow{}
	for rows.Next() {
		var r familyBrokerAccountRow
		var broker, username, status, lastErr sql.NullString
		var hasSecret, isActive sql.NullBool
		var lastSync sql.NullTime
		if err := rows.Scan(&r.PersonID, &r.PersonName, &broker, &username, &hasSecret, &isActive, &lastSync, &status, &lastErr); err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "scan: " + err.Error()})
			return
		}
		r.Broker = broker.String
		r.Username = username.String
		r.HasSecret = hasSecret.Bool
		r.IsActive = isActive.Bool
		r.LastStatus = status.String
		r.LastError = lastErr.String
		if lastSync.Valid {
			t := lastSync.Time
			r.LastSyncedAt = &t
		}
		out = append(out, r)
	}
	c.JSON(http.StatusOK, out)
}

type upsertBrokerAccountRequest struct {
	PersonID int    `json:"person_id"`
	Username string `json:"username"`
	Password string `json:"password"` // خالی = بدون تغییر رمز
	IsActive *bool  `json:"is_active"`
}

func upsertFamilyBrokerAccountPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}
	var req upsertBrokerAccountRequest
	if err := c.ShouldBindJSON(&req); err != nil {
		c.JSON(http.StatusBadRequest, gin.H{"error": "invalid request body"})
		return
	}
	if req.PersonID <= 0 || strings.TrimSpace(req.Username) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id and username are required"})
		return
	}

	ctx, cancel := familyPGTimeout()
	defer cancel()

	var cipherText, nonce string
	if req.Password != "" {
		if !config.SecretsEnabled() {
			c.JSON(http.StatusServiceUnavailable, gin.H{"error": "CDF_SECRET_KEY not configured; cannot store credentials"})
			return
		}
		ct, nc, err := config.EncryptString(req.Password)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "encrypt: " + err.Error()})
			return
		}
		cipherText, nonce = ct, nc
	}

	active := true
	if req.IsActive != nil {
		active = *req.IsActive
	}

	if _, err := db.ExecContext(ctx, `
		INSERT INTO family.broker_accounts (person_id, broker, username, secret_cipher, secret_nonce, is_active, updated_at)
		VALUES ($1, 'agah', $2, NULLIF($3,''), NULLIF($4,''), $5, now())
		ON CONFLICT (person_id) DO UPDATE SET
			broker = 'agah',
			username = EXCLUDED.username,
			secret_cipher = CASE WHEN EXCLUDED.secret_cipher IS NULL THEN family.broker_accounts.secret_cipher ELSE EXCLUDED.secret_cipher END,
			secret_nonce  = CASE WHEN EXCLUDED.secret_nonce  IS NULL THEN family.broker_accounts.secret_nonce  ELSE EXCLUDED.secret_nonce  END,
			is_active = EXCLUDED.is_active,
			updated_at = now()`,
		req.PersonID, strings.TrimSpace(req.Username), cipherText, nonce, active); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "save: " + err.Error()})
		return
	}

	c.JSON(http.StatusOK, gin.H{"message": "saved"})
}

func deleteFamilyBrokerAccountPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}
	personID, _ := strconv.Atoi(c.Query("person_id"))
	if personID <= 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "person_id is required"})
		return
	}
	ctx, cancel := familyPGTimeout()
	defer cancel()
	if _, err := db.ExecContext(ctx, `DELETE FROM family.broker_accounts WHERE person_id = $1`, personID); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "delete: " + err.Error()})
		return
	}
	c.JSON(http.StatusOK, gin.H{"message": "deleted"})
}

// ────────────────────────────── sync ──────────────────────────────

type startBrokerSyncRequest struct {
	PersonID int  `json:"person_id"` // 0 = همه اشخاص پیکربندی‌شده
	All      bool `json:"all"`
}

func startFamilyBrokerSyncPG(c *gin.Context) {
	db, ok := familyPGDB(c)
	if !ok {
		return
	}
	var req startBrokerSyncRequest
	_ = c.ShouldBindJSON(&req)

	ctx, cancel := familyPGTimeout()
	defer cancel()

	type target struct{ personID int }
	targets := []target{}
	if req.All || req.PersonID == 0 {
		rows, err := db.QueryContext(ctx, `
			SELECT person_id FROM family.broker_accounts
			WHERE is_active = true AND broker = 'agah'
			ORDER BY person_id`)
		if err != nil {
			c.JSON(http.StatusInternalServerError, gin.H{"error": "query: " + err.Error()})
			return
		}
		for rows.Next() {
			var pid int
			if err := rows.Scan(&pid); err != nil {
				rows.Close()
				c.JSON(http.StatusInternalServerError, gin.H{"error": "scan: " + err.Error()})
				return
			}
			targets = append(targets, target{pid})
		}
		rows.Close()
	} else {
		targets = append(targets, target{req.PersonID})
	}

	if len(targets) == 0 {
		c.JSON(http.StatusBadRequest, gin.H{"error": "no agah broker account configured"})
		return
	}

	// سینک هم‌زمان برای یک شخص مجاز نیست (پروفایل مرورگر هر شخص فقط یک قفل دارد).
	running := runningBrokerPersonIDs()
	jobs := []*brokerSyncJob{}
	for _, t := range targets {
		if running[t.personID] {
			continue
		}
		job := newBrokerJob(t.personID)
		jobs = append(jobs, job)
		go runAgahSyncJob(job.ID, t.personID)
	}

	if len(jobs) == 0 {
		c.JSON(http.StatusConflict, gin.H{"error": "sync already running for the requested person(s)"})
		return
	}

	c.JSON(http.StatusOK, gin.H{"jobs": jobs})
}

func getFamilyBrokerJobPG(c *gin.Context) {
	id := c.Query("job_id")
	if id == "" {
		// فهرست آخرین jobها
		brokerJobsMu.Lock()
		out := make([]*brokerSyncJob, 0, len(brokerJobs))
		for _, j := range brokerJobs {
			out = append(out, j)
		}
		brokerJobsMu.Unlock()
		c.JSON(http.StatusOK, out)
		return
	}
	job := getBrokerJob(id)
	if job == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}
	attachBrokerChallenge(job)
	c.JSON(http.StatusOK, job)
}

// attachBrokerChallenge در صورت انتشار کپچای در انتظار پاسخ، آن را به job می‌چسباند.
func attachBrokerChallenge(job *brokerSyncJob) {
	if job == nil || job.exchangeDir == "" {
		return
	}
	b, err := os.ReadFile(filepath.Join(job.exchangeDir, "challenge.json"))
	needs, image := false, ""
	if err == nil {
		var ch struct {
			Captcha string `json:"captcha"`
			Attempt int    `json:"attempt"`
		}
		if json.Unmarshal(b, &ch) == nil && ch.Captcha != "" {
			needs, image = true, ch.Captcha
		}
	}
	brokerJobsMu.Lock()
	defer brokerJobsMu.Unlock()
	if job.State != "running" {
		return
	}
	job.NeedsCaptcha = needs
	job.CaptchaImage = image
}

// SubmitFamilyBrokerCaptcha کد امنیتی وارد‌شده در UI را برای job در حال اجرا می‌فرستد.
func SubmitFamilyBrokerCaptcha(c *gin.Context) {
	if !requireFamilyAdmin(c) {
		return
	}
	var req struct {
		JobID string `json:"job_id"`
		Code  string `json:"code"`
	}
	if err := c.ShouldBindJSON(&req); err != nil || strings.TrimSpace(req.JobID) == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "job_id and code are required"})
		return
	}
	code := strings.TrimSpace(req.Code)
	if code == "" {
		c.JSON(http.StatusBadRequest, gin.H{"error": "code is required"})
		return
	}
	job := getBrokerJob(strings.TrimSpace(req.JobID))
	if job == nil {
		c.JSON(http.StatusNotFound, gin.H{"error": "job not found"})
		return
	}
	if job.State != "running" {
		c.JSON(http.StatusConflict, gin.H{"error": "job is not running"})
		return
	}
	if job.exchangeDir == "" {
		c.JSON(http.StatusConflict, gin.H{"error": "this job does not accept captcha input"})
		return
	}
	if err := os.MkdirAll(job.exchangeDir, 0o755); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "exchange dir: " + err.Error()})
		return
	}
	payload, _ := json.Marshal(map[string]string{"code": code})
	tmp := filepath.Join(job.exchangeDir, "answer.json.tmp")
	if err := os.WriteFile(tmp, payload, 0o644); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "write answer: " + err.Error()})
		return
	}
	if err := os.Rename(tmp, filepath.Join(job.exchangeDir, "answer.json")); err != nil {
		c.JSON(http.StatusInternalServerError, gin.H{"error": "write answer: " + err.Error()})
		return
	}
	// تصویر کهنه حذف شود تا UI کپچای جدید (در صورت تلاش مجدد) نشان دهد.
	_ = os.Remove(filepath.Join(job.exchangeDir, "challenge.json"))
	updateBrokerJob(job.ID, "running", "کد امنیتی دریافت شد؛ در حال ورود...", nil)
	c.JSON(http.StatusOK, gin.H{"message": "submitted"})
}

// runAgahSyncJob اجرای collector، نوشتن snapshot و جایگزینی سبد شخص.
func runAgahSyncJob(jobID string, personID int) {
	defer func() {
		if r := recover(); r != nil {
			updateBrokerJob(jobID, "error", fmt.Sprintf("panic: %v", r), nil)
		}
	}()

	db, err := config.GetPG()
	if err != nil || db == nil {
		updateBrokerJob(jobID, "error", "postgres unavailable", nil)
		return
	}
	ctx, cancel := context.WithTimeout(context.Background(), 12*time.Minute)
	defer cancel()

	var username, cipherText, nonce string
	err = db.QueryRowContext(ctx, `
		SELECT username, COALESCE(secret_cipher,''), COALESCE(secret_nonce,'')
		FROM family.broker_accounts
		WHERE person_id = $1 AND is_active = true AND broker = 'agah'`, personID).Scan(&username, &cipherText, &nonce)
	if err == sql.ErrNoRows {
		updateBrokerJob(jobID, "error", "broker account not configured", nil)
		return
	}
	if err != nil {
		updateBrokerJob(jobID, "error", "load account: "+err.Error(), nil)
		return
	}
	password := ""
	if cipherText != "" {
		password, err = config.DecryptString(cipherText, nonce)
		if err != nil {
			updateBrokerJob(jobID, "error", "decrypt credential: "+err.Error(), nil)
			return
		}
	}

	job := getBrokerJob(jobID)
	if job != nil {
		job.exchangeDir = brokerExchangeDir(jobID)
	}
	defer func() {
		if job != nil && job.exchangeDir != "" {
			_ = os.RemoveAll(job.exchangeDir)
		}
	}()

	result, runErr := runAgahCollector(ctx, personID, username, password, jobID)
	if runErr != nil {
		_ = recordBrokerSnapshot(ctx, db, personID, false, runErr.Error(), map[string]any{"error": runErr.Error()})
		_ = markBrokerAccount(ctx, db, personID, "error", runErr.Error())
		updateBrokerJob(jobID, "error", runErr.Error(), nil)
		return
	}

	raw := map[string]any{
		"ok":              result.OK,
		"holdings":        result.Holdings,
		"cash":            result.Cash,
		"source":          result.Source,
		"summary":         result.Summary,
		"login":           result.Login,
		"needs_discovery": result.NeedsDiscovery,
		"captured":        result.Captured,
	}
	if err := recordBrokerSnapshot(ctx, db, personID, true, "", raw); err != nil {
		_ = err
	}

	if !result.OK || len(result.Holdings) == 0 {
		msg := "سبدی خوانده نشد"
		if result.NeedsDiscovery {
			msg = "ساختار پنل ناشناخته است؛ dump برای کشف ذخیره شد"
		}
		_ = markBrokerAccount(ctx, db, personID, "error", msg)
		updateBrokerJob(jobID, "error", msg, &result)
		return
	}

	imported, err := reconcileBrokerHoldingsPG(ctx, db, personID, result)
	if err != nil {
		updateBrokerJob(jobID, "error", "reconcile: "+err.Error(), &result)
		return
	}

	_ = markBrokerAccount(ctx, db, personID, "ok", "")
	refreshLatestFamilyHistoryPG(ctx, db)
	updateBrokerJob(jobID, "done", fmt.Sprintf("%d دارایی به‌روزرسانی شد", imported), &result)
}

// brokerExchangeDir مسیر تبادل کپچا/پاسخ بین سرور و کالکتور برای هر job.
func brokerExchangeDir(jobID string) string {
	return filepath.Join(os.TempDir(), "agah-sync", "exchange", jobID)
}

// agahProfileKey کلید امن پروفایل مرورگر برای هر حساب کارگزاری (جدا‌سازی نشست‌ها).
func agahProfileKey(personID int, username string) string {
	var b strings.Builder
	for _, r := range strings.TrimSpace(username) {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9',
			r == '.', r == '-', r == '_', r == '@':
			b.WriteRune(r)
		default:
			b.WriteRune('_')
		}
	}
	key := strings.Trim(b.String(), "_")
	if key == "" {
		key = fmt.Sprintf("person-%d", personID)
	}
	if len(key) > 80 {
		key = key[:80]
	}
	return key
}

// runAgahCollector اسکریپت پایتون را اجرا و خروجی JSON را می‌خواند.
func runAgahCollector(ctx context.Context, personID int, username, password, jobID string) (agahResult, error) {
	var result agahResult

	outDir := filepath.Join(os.TempDir(), "agah-sync")
	_ = os.MkdirAll(outDir, 0o755)
	stamp := time.Now().UnixNano()
	outPath := filepath.Join(outDir, fmt.Sprintf("result_%d.json", stamp))
	dumpDir := filepath.Join(os.TempDir(), "agah-dump", fmt.Sprintf("%d", stamp))
	exchangeDir := brokerExchangeDir(jobID)

	// ورود روی سرور headed اجرا می‌شود (رفتار امتحان‌شده) اما همه‌چیز خودکار است:
	// کپچا با OCR حل می‌شود و فقط در صورت نیاز تصویرش به UI می‌آید؛ پنجره را
	// کسی نباید لمس کند. با CDF_AGAH_HEADLESS=1 می‌توان headless اجرا کرد
	// (در برخی شبکه‌ها API پنل، مرورگر headless را نمی‌پذیرد).
	headless := false
	switch strings.ToLower(strings.TrimSpace(os.Getenv("CDF_AGAH_HEADLESS"))) {
	case "1", "true", "on":
		headless = true
	}

	cfg := map[string]any{
		"username":      username,
		"password":      password,
		"login_url":     agahLoginURL,
		"portfolio_url": agahPortfolioURL,
		"headless":      headless,
		"timeout_sec":   300,
		// پروفایل مستقل برای هر شخص: نشست هر حساب جدا می‌ماند و سینک بعدیِ
		// همان شخص تا اعتبار نشست بدون کپچا انجام می‌شود.
		"profile_dir":  filepath.Join(".runtime", "chromium-profile-agah", agahProfileKey(personID, username)),
		"exchange_dir": exchangeDir,
	}
	cfgJSON, _ := json.Marshal(cfg)

	pythonExe := os.Getenv("CDF_PYTHON")
	if pythonExe == "" {
		pythonExe = "python"
	}
	cmd := exec.CommandContext(ctx, pythonExe, "py/broker_agah.py", "--out", outPath, "--dump-dir", dumpDir, "--timeout", "300")
	cmd.Stdin = bytes.NewReader(cfgJSON)
	var stderr bytes.Buffer
	cmd.Stderr = &stderr

	runErr := cmd.Run()
	body, readErr := os.ReadFile(outPath)
	if readErr != nil {
		if runErr != nil {
			return result, fmt.Errorf("collector failed: %v (%s)", runErr, strings.TrimSpace(stderr.String()))
		}
		return result, fmt.Errorf("collector produced no output: %v", readErr)
	}
	if err := json.Unmarshal(body, &result); err != nil {
		return result, fmt.Errorf("collector output parse: %v", err)
	}
	if result.Error != "" && !result.OK {
		return result, fmt.Errorf("%s", result.Error)
	}
	return result, nil
}

// reconcileBrokerHoldingsPG سبد شخص را با داده کارگزاری جایگزین می‌کند.
func reconcileBrokerHoldingsPG(ctx context.Context, db *sql.DB, personID int, result agahResult) (int, error) {
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return 0, err
	}
	defer tx.Rollback()

	keepAssetIDs := []int{}
	imported := 0
	todayKey := todayFamilyDateKey()

	for _, h := range result.Holdings {
		symbol := strings.TrimSpace(normalizePersian(h.Symbol))
		name := strings.TrimSpace(normalizePersian(h.Name))
		if symbol == "" {
			symbol = name
		}
		if symbol == "" {
			continue
		}

		assetID, err := resolveFamilyAssetTx(ctx, tx, symbol, name)
		if err != nil {
			return imported, err
		}
		if assetID == 0 {
			continue
		}

		if h.Quantity == 0 {
			continue
		}

		// بهای تمام‌شده واقعی سبد (calculatedAssetCost) اولویت دارد؛
		// در نبود آن از میانگین خرید و در نبود آن از قیمت روز.
		costBasis := h.CostBasis
		if costBasis <= 0 && h.AvgBuyPrice > 0 {
			costBasis = h.Quantity * h.AvgBuyPrice
		}
		if costBasis <= 0 && h.LastPrice > 0 {
			costBasis = h.Quantity * h.LastPrice
		}

		if _, err := tx.ExecContext(ctx, `
			INSERT INTO family.holdings (person_id, asset_id, quantity, cost_basis)
			VALUES ($1, $2, $3, $4)
			ON CONFLICT (person_id, asset_id) DO UPDATE SET
				quantity = EXCLUDED.quantity, cost_basis = EXCLUDED.cost_basis`,
			personID, assetID, h.Quantity, costBasis); err != nil {
			return imported, err
		}

		// قیمت لحظه‌ای کارگزاری را برای امروز ثبت کن تا ارزش سبد بدون
		// سینک بازار هم به‌روز باشد.
		if h.LastPrice > 0 {
			if _, err := tx.ExecContext(ctx, `
				INSERT INTO family.prices (date_key, asset_id, price)
				VALUES ($1, $2, $3)
				ON CONFLICT (date_key, asset_id) DO UPDATE SET price = EXCLUDED.price`,
				todayKey, assetID, h.LastPrice); err != nil {
				return imported, err
			}
		}

		keepAssetIDs = append(keepAssetIDs, assetID)
		imported++
	}

	// حذف دارایی‌های شخص که در سبد کارگزاری نیستند (جایگزینی کامل).
	if len(keepAssetIDs) == 0 {
		if _, err := tx.ExecContext(ctx, `DELETE FROM family.holdings WHERE person_id = $1`, personID); err != nil {
			return imported, err
		}
	} else {
		if _, err := tx.ExecContext(ctx, `
			DELETE FROM family.holdings
			WHERE person_id = $1 AND asset_id <> ALL($2::int[])`,
			personID, intArray(keepAssetIDs)); err != nil {
			return imported, err
		}
	}

	// مانده نقدی
	if result.Cash.Available != nil {
		if _, err := tx.ExecContext(ctx, `
			INSERT INTO family.accounts (person_id, cash_balance)
			VALUES ($1, $2)
			ON CONFLICT (person_id) DO UPDATE SET cash_balance = EXCLUDED.cash_balance`,
			personID, *result.Cash.Available); err != nil {
			return imported, err
		}
	}

	if err := tx.Commit(); err != nil {
		return imported, err
	}
	return imported, nil
}

// resolveFamilyAssetTx دارایی family را با نماد کوتاه بازار پیدا یا می‌سازد.
// نماد/نام کارگزاری (securityTitle/companyName) ابتدا به نماد کوتاه کانونی
// نگاشت می‌شود تا دارایی تکراری با نام کامل شرکت ساخته نشود و نام نمایشی
// همیشه همان نماد کوتاه باشد.
func resolveFamilyAssetTx(ctx context.Context, tx *sql.Tx, symbol, name string) (int, error) {
	symbol = strings.TrimSpace(normalizePersian(symbol))
	name = strings.TrimSpace(normalizePersian(name))

	key, err := resolveCanonicalSymbol(ctx, tx, symbol, name)
	if err != nil {
		return 0, err
	}
	if key == "" {
		// خارج از فهرست کانونی (صندوق/نماد بدون شرکت): نماد کارگزاری کوتاه است.
		if symbol != "" {
			key = symbol
		} else {
			key = name
		}
	}
	if key == "" {
		return 0, nil
	}

	var id int
	err = tx.QueryRowContext(ctx, `
		SELECT asset_id FROM family.assets
		WHERE symbol = $1 OR name = $1
		ORDER BY is_active DESC, asset_id LIMIT 1`, key).Scan(&id)
	if err == nil {
		return id, renameFamilyAssetTx(ctx, tx, id, key)
	}
	if err != sql.ErrNoRows {
		return 0, err
	}

	// سازگاری با دارایی‌های قدیمی که با نام کامل/ISIN ذخیره شده‌اند:
	// همان رکورد پیدا و به نماد کوتاه تغییرنام می‌شود (نه رکورد جدید).
	if name != "" || symbol != "" {
		ferr := tx.QueryRowContext(ctx, `
			SELECT asset_id FROM family.assets
			WHERE name = $1 OR symbol = $1 OR ($2 <> '' AND (name = $2 OR symbol = $2))
			ORDER BY is_active DESC, asset_id LIMIT 1`, name, symbol).Scan(&id)
		if ferr == nil {
			return id, renameFamilyAssetTx(ctx, tx, id, key)
		}
		if ferr != sql.ErrNoRows {
			return 0, ferr
		}
	}

	if err := tx.QueryRowContext(ctx, `
		INSERT INTO family.assets (name, symbol, category, commission_rate, sort_order)
		VALUES ($1, $1, 'stock', $2, 100)
		RETURNING asset_id`, key, familyDefaultCommission).Scan(&id); err != nil {
		return 0, err
	}
	return id, nil
}

// renameFamilyAssetTx نام نمایشی و نماد دارایی را به نماد کوتاه بازار یکسان می‌کند.
func renameFamilyAssetTx(ctx context.Context, tx *sql.Tx, id int, key string) error {
	if _, err := tx.ExecContext(ctx, `
		UPDATE family.assets SET name = $1, symbol = $1
		WHERE asset_id = $2 AND (name <> $1 OR symbol IS DISTINCT FROM $1)`, key, id); err != nil {
		return err
	}
	return nil
}

func recordBrokerSnapshot(ctx context.Context, db *sql.DB, personID int, ok bool, errMsg string, payload map[string]any) error {
	b, _ := json.Marshal(payload)
	_, err := db.ExecContext(ctx, `
		INSERT INTO family.broker_snapshots (person_id, broker, ok, error, payload)
		VALUES ($1, 'agah', $2, NULLIF($3,''), $4::jsonb)`, personID, ok, errMsg, string(b))
	return err
}

func markBrokerAccount(ctx context.Context, db *sql.DB, personID int, status, errMsg string) error {
	_, err := db.ExecContext(ctx, `
		UPDATE family.broker_accounts
		SET last_synced_at = now(), last_status = $2, last_error = NULLIF($3,''), updated_at = now()
		WHERE person_id = $1`, personID, status, errMsg)
	return err
}

// intArray قالب‌بندی آرایه int برای پارامتر ANY در PostgreSQL.
func intArray(ids []int) string {
	parts := make([]string, len(ids))
	for i, id := range ids {
		parts[i] = strconv.Itoa(id)
	}
	return "{" + strings.Join(parts, ",") + "}"
}
