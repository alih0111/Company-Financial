package handlers

import (
	"context"
	"fmt"
	"strings"

	"go-app/config"
)

// chat_settings.go — تنظیمات شخصی‌سازی هر کاربر (پروفایل ریسک + سرمایه) در
// chat.user_settings. ابزارهای get/set_my_preferences و build_portfolio از آن
// استفاده می‌کنند تا سبد با سرمایه‌ی واقعی کاربر ساخته شود.

type chatSettings struct {
	RiskLevel   string
	CapitalRial float64
	HasCapital  bool
}

func getChatSettings(ctx context.Context, username string) (chatSettings, bool) {
	if strings.TrimSpace(username) == "" {
		return chatSettings{}, false
	}
	db, err := config.GetPG()
	if err != nil || db == nil {
		return chatSettings{}, false
	}
	uid, ok, err := userIDByUsername(ctx, db, username)
	if err != nil || !ok {
		return chatSettings{}, false
	}
	var s chatSettings
	var capital *float64
	var risk *string
	err = db.QueryRowContext(ctx,
		`SELECT risk_level, capital_rial FROM chat.user_settings WHERE user_id = $1::uuid`, uid).
		Scan(&risk, &capital)
	if err != nil {
		return chatSettings{}, false
	}
	if risk != nil {
		s.RiskLevel = strings.TrimSpace(*risk)
	}
	if capital != nil && *capital > 0 {
		s.CapitalRial = *capital
		s.HasCapital = true
	}
	return s, s.RiskLevel != "" || s.HasCapital
}

func upsertChatSettings(ctx context.Context, username string, s chatSettings) error {
	if strings.TrimSpace(username) == "" {
		return errChatNoUser
	}
	db, err := config.GetPG()
	if err != nil || db == nil {
		return errChatNoDB
	}
	uid, ok, err := userIDByUsername(ctx, db, username)
	if err != nil {
		return err
	}
	if !ok {
		return errChatNoUser
	}
	_, err = db.ExecContext(ctx,
		`INSERT INTO chat.user_settings (user_id, risk_level, capital_rial, updated_at)
		 VALUES ($1::uuid, NULLIF($2,''), NULLIF($3,0), now())
		 ON CONFLICT (user_id) DO UPDATE SET
		   risk_level = COALESCE(NULLIF($2,''), chat.user_settings.risk_level),
		   capital_rial = COALESCE(NULLIF($3,0), chat.user_settings.capital_rial),
		   updated_at = now()`,
		uid, s.RiskLevel, s.CapitalRial)
	return err
}

// خطاهای به‌اشتراک‌گذاشته‌ی تنظیمات
var (
	errChatNoUser = fmt.Errorf("کاربر شناسایی نشد")
	errChatNoDB   = fmt.Errorf("پایگاه داده در دسترس نیست")
)
