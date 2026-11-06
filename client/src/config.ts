// پیکربندی متمرکز فرانت — با متغیر محیطی قابل‌بازنویسی است (.env را ببینید)
export const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined) ??
  "/api";

export const APP_TITLE = "RFA | بینش شرکت‌ها";
