// هشدار قیمت — سمت کلاینت، بدون نیاز به بک‌اند.
// هر هشدار: نماد + جهت (بالای/زیر) + قیمت هدف. هنگام بارگذاری قیمت‌ها
// (مثلاً در دیده‌بان) بررسی می‌شود؛ هشدار فعال‌شده یک‌بار اعلان می‌دهد و
// تا ویرایش مجدد توسط کاربر، دوباره اعلان نمی‌دهد.

export interface PriceAlert {
  key: string; // نماد
  label: string;
  above: boolean; // true = هشدار وقتی قیمت بالای هدف رفت
  price: number;
  // زمان فعال‌سازی (epoch ms) — null یعنی هنوز فعال نشده
  triggeredAt: number | null;
}

const STORAGE_KEY = "rfa_alerts_v1";
const EVENT = "rfa:alerts-changed";

export function getAlerts(): PriceAlert[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (a) => a && typeof a.key === "string" && typeof a.price === "number",
    );
  } catch {
    return [];
  }
}

function persist(items: PriceAlert[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function getAlert(key: string): PriceAlert | undefined {
  return getAlerts().find((a) => a.key === key);
}

/** ایجاد/به‌روزرسانی هشدار یک نماد (هر نماد حداکثر یک هشدار). */
export function setAlert(alert: Omit<PriceAlert, "triggeredAt">) {
  const rest = getAlerts().filter((a) => a.key !== alert.key);
  persist([...rest, { ...alert, triggeredAt: null }]);
}

export function removeAlert(key: string) {
  persist(getAlerts().filter((a) => a.key !== key));
}

/** غیرفعال‌کردن بعد از اعلان — رکورد می‌ماند تا کاربر بداند فعال شده بوده. */
export function markTriggered(key: string) {
  persist(
    getAlerts().map((a) => (a.key === key ? { ...a, triggeredAt: Date.now() } : a)),
  );
}

export function subscribeAlerts(cb: () => void): () => void {
  const handler = () => cb();
  window.addEventListener(EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}

/**
 * بررسی هشدارها با آخرین قیمت‌ها — فقط هشدارهای تازه فعال‌شده برمی‌گرداند
 * و همان‌جا markTriggered می‌شود.
 */
export function checkAlerts(latest: Record<string, number | undefined>): PriceAlert[] {
  const fired: PriceAlert[] = [];
  const alerts = getAlerts();
  let changed = false;
  for (const a of alerts) {
    if (a.triggeredAt) continue;
    const p = latest[a.key];
    if (p == null || !Number.isFinite(p) || p <= 0) continue;
    const hit = a.above ? p >= a.price : p <= a.price;
    if (hit) {
      fired.push(a);
      a.triggeredAt = Date.now();
      changed = true;
    }
  }
  if (changed) persist(alerts);
  return fired;
}
