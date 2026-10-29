// دیده‌بان شخصی — ذخیره محلی (localStorage) با رویداد تغییر تا همه‌ی
// کامپوننت‌ها (صفحه دیده‌بان، ستاره‌های صفحه بازار و ...) هم‌زمان به‌روز شوند.

export type WatchKind = "stock" | "fund" | "index";

export interface WatchItem {
  key: string; // نماد/نام — همان کلیدی که price-history می‌پذیرد
  label: string; // نمایش فارسی
  kind: WatchKind;
}

const STORAGE_KEY = "rfa_watchlist_v1";
export const MAX_WATCH = 15;
const EVENT = "rfa:watchlist-changed";

export function getWatchlist(): WatchItem[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (x) => x && typeof x.key === "string" && typeof x.label === "string",
    );
  } catch {
    return [];
  }
}

function persist(items: WatchItem[]) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  window.dispatchEvent(new CustomEvent(EVENT));
}

export function isWatched(key: string): boolean {
  return getWatchlist().some((x) => x.key === key);
}

/** افزودن/حذف — خروجی: true اگر اکنون در دیده‌بان است. */
export function toggleWatch(item: WatchItem): boolean {
  const cur = getWatchlist();
  const exists = cur.some((x) => x.key === item.key);
  if (exists) {
    persist(cur.filter((x) => x.key !== item.key));
    return false;
  }
  if (cur.length >= MAX_WATCH) return false;
  persist([...cur, item]);
  return true;
}

export function removeFromWatch(key: string) {
  persist(getWatchlist().filter((x) => x.key !== key));
}

/** اشتراک در تغییرات (رویداد سفارشی + storage برای تب‌های دیگر). */
export function subscribeWatchlist(cb: () => void): () => void {
  const handler = () => cb();
  window.addEventListener(EVENT, handler);
  window.addEventListener("storage", handler);
  return () => {
    window.removeEventListener(EVENT, handler);
    window.removeEventListener("storage", handler);
  };
}
