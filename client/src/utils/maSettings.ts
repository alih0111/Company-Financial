// تنظیمات دوره‌ی میانگین‌های متحرک نمودار قیمت.
// دوره‌ها به‌ازای هر نماد جداگانه در localStorage ذخیره می‌شوند تا دفعه‌ی بعد
// کاربر همان MA را روی نمودار همان نماد ببیند.

export type MaKey = "ma20" | "ma50" | "ma200";
export type MaPeriods = Record<MaKey, number>;

export const MA_MIN = 2;
export const MA_MAX = 500;

export const DEFAULT_MA_PERIODS: MaPeriods = {
  ma20: 20,
  ma50: 50,
  ma200: 200,
};

const STORAGE_KEY = "priceChartMaPeriods:v1";

const clamp = (value: unknown, fallback: number): number => {
  const n = Math.round(Number(value));
  if (!Number.isFinite(n)) return fallback;
  return Math.min(MA_MAX, Math.max(MA_MIN, n));
};

const sanitize = (raw: unknown): MaPeriods => {
  const src = (raw ?? {}) as Partial<Record<MaKey, unknown>>;
  return {
    ma20: clamp(src.ma20, DEFAULT_MA_PERIODS.ma20),
    ma50: clamp(src.ma50, DEFAULT_MA_PERIODS.ma50),
    ma200: clamp(src.ma200, DEFAULT_MA_PERIODS.ma200),
  };
};

const readAll = (): Record<string, MaPeriods> => {
  try {
    const parsed = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
};

export function loadMaPeriods(symbol: string): MaPeriods {
  const key = symbol.trim();
  if (!key) return { ...DEFAULT_MA_PERIODS };
  const stored = readAll()[key];
  return stored ? sanitize(stored) : { ...DEFAULT_MA_PERIODS };
}

export function saveMaPeriods(symbol: string, periods: MaPeriods): void {
  const key = symbol.trim();
  if (!key) return;
  try {
    const all = readAll();
    all[key] = sanitize(periods);
    localStorage.setItem(STORAGE_KEY, JSON.stringify(all));
  } catch {
    /* storage may be disabled */
  }
}

export function isMaKey(key: string): key is MaKey {
  return key === "ma20" || key === "ma50" || key === "ma200";
}
