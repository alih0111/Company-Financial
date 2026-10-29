// اندیکاتورهای تکنیکال و آمار — توابع خالص، بدون وابستگی به React.
// همه‌ی ورودی‌ها دنباله‌های قیمتی صعودی از نظر زمان هستند و خروجی‌ها
// هم‌طول ورودی‌اند (نقاط بدون مقدار کافی = null) تا ایندکس‌ها هم‌راستا بمانند.

/** میانگین متحرک ساده — period اول null است. */
export function sma(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (period <= 1) return values.map((v) => v);
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i];
    if (i >= period) sum -= values[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/** میانگین متحرک نمایی — با seed = SMA(period) مطابق روش استاندارد. */
export function ema(values: number[], period: number): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length < period || period <= 0) return out;
  const k = 2 / (period + 1);
  let seed = 0;
  for (let i = 0; i < period; i++) seed += values[i];
  seed /= period;
  out[period - 1] = seed;
  let prev = seed;
  for (let i = period; i < values.length; i++) {
    prev = values[i] * k + prev * (1 - k);
    out[i] = prev;
  }
  return out;
}

/** باندهای بولینگر — میانگین ± mult انحراف معیار. */
export function bollinger(
  values: number[],
  period = 20,
  mult = 2
): { mid: (number | null)[]; upper: (number | null)[]; lower: (number | null)[] } {
  const mid = sma(values, period);
  const upper: (number | null)[] = new Array(values.length).fill(null);
  const lower: (number | null)[] = new Array(values.length).fill(null);
  for (let i = period - 1; i < values.length; i++) {
    const m = mid[i];
    if (m == null) continue;
    let sq = 0;
    for (let j = i - period + 1; j <= i; j++) sq += (values[j] - m) ** 2;
    const sd = Math.sqrt(sq / period);
    upper[i] = m + mult * sd;
    lower[i] = m - mult * sd;
  }
  return { mid, upper, lower };
}

/** RSI با هموارسازی Wilder (روش کلاسیک وایلدر). */
export function rsi(values: number[], period = 14): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  if (values.length <= period) return out;
  let gain = 0;
  let loss = 0;
  for (let i = 1; i <= period; i++) {
    const d = values[i] - values[i - 1];
    if (d >= 0) gain += d;
    else loss -= d;
  }
  let avgGain = gain / period;
  let avgLoss = loss / period;
  out[period] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  for (let i = period + 1; i < values.length; i++) {
    const d = values[i] - values[i - 1];
    const g = d > 0 ? d : 0;
    const l = d < 0 ? -d : 0;
    avgGain = (avgGain * (period - 1) + g) / period;
    avgLoss = (avgLoss * (period - 1) + l) / period;
    out[i] = avgLoss === 0 ? 100 : 100 - 100 / (1 + avgGain / avgLoss);
  }
  return out;
}

/**
 * MACD — خط مکدی (EMA سریع منهای EMA کند)، خط سیگنال (EMA از مکدی)
 * و هیستوگرام (مکدی منهای سیگنال). مقادیر قبل از تشکیل سیگنال null است.
 */
export function macd(
  values: number[],
  fast = 12,
  slow = 26,
  signalPeriod = 9
): { macd: (number | null)[]; signal: (number | null)[]; hist: (number | null)[] } {
  const emaFast = ema(values, fast);
  const emaSlow = ema(values, slow);
  const n = values.length;
  const macdLine: (number | null)[] = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    const f = emaFast[i];
    const s = emaSlow[i];
    if (f != null && s != null) macdLine[i] = f - s;
  }
  // سیگنال: EMA روی بخش غیرnull مکدی، به همان ایندکس‌ها برمی‌گردد
  const signal: (number | null)[] = new Array(n).fill(null);
  const hist: (number | null)[] = new Array(n).fill(null);
  const startIdx = macdLine.findIndex((v) => v != null);
  if (startIdx >= 0) {
    const compact = macdLine.slice(startIdx) as number[];
    const sig = ema(compact, signalPeriod);
    for (let i = 0; i < sig.length; i++) {
      if (sig[i] == null) continue;
      const idx = startIdx + i;
      signal[idx] = sig[i];
      hist[idx] = (macdLine[idx] as number) - (sig[i] as number);
    }
  }
  return { macd: macdLine, signal, hist };
}

/** بازده‌های لگاریتمی روزانه — برای همبستگی. */
export function dailyReturns(values: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < values.length; i++) {
    if (values[i - 1] > 0 && values[i] > 0) {
      out.push(Math.log(values[i] / values[i - 1]));
    }
  }
  return out;
}

/** ضریب همبستگی پیرسون دو دنباله هم‌طول. */
export function correlation(a: number[], b: number[]): number | null {
  const n = Math.min(a.length, b.length);
  if (n < 3) return null;
  let ma = 0;
  let mb = 0;
  for (let i = 0; i < n; i++) {
    ma += a[i];
    mb += b[i];
  }
  ma /= n;
  mb /= n;
  let cov = 0;
  let va = 0;
  let vb = 0;
  for (let i = 0; i < n; i++) {
    const da = a[i] - ma;
    const db = b[i] - mb;
    cov += da * db;
    va += da * da;
    vb += db * db;
  }
  if (va === 0 || vb === 0) return null;
  return cov / Math.sqrt(va * vb);
}

/** بیشینه‌ی افت از سقف تاکنونی (بر حسب درصد؛ مثبت = اندازه‌ی افت). */
export function maxDrawdown(series: number[]): number {
  let peak = -Infinity;
  let mdd = 0;
  for (const v of series) {
    if (v > peak) peak = v;
    if (peak > 0) mdd = Math.max(mdd, (peak - v) / peak);
  }
  return mdd * 100;
}

/** صدک مقدار فعلی در بازه‌ی [min,max] دوره (۰ تا ۱). */
export function percentileNow(series: number[]): number | null {
  if (series.length === 0) return null;
  const min = Math.min(...series);
  const max = Math.max(...series);
  if (max === min) return 0.5;
  return (series[series.length - 1] - min) / (max - min);
}
