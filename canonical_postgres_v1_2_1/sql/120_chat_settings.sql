-- 120_chat_settings.sql — تنظیمات شخصی‌سازی دستیار (پروفایل ریسک + سرمایه)
-- chat.user_settings: هر کاربر یک ردیف؛ ابزارهای get/set_my_preferences و
-- build_portfolio از آن می‌خوانند تا سبد پیشنهادی با سرمایه و ریسک واقعی
-- کاربر ساخته شود، نه پیش‌فرض سراسری.

CREATE SCHEMA IF NOT EXISTS chat;

CREATE TABLE IF NOT EXISTS chat.user_settings (
    user_id       uuid        PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    risk_level    text,
    capital_rial  numeric(30,4),
    updated_at    timestamptz NOT NULL DEFAULT now()
);
