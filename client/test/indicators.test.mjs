// تست واحد توابع اندیکاتور — با node --test
// فایل .generated/indicators.mjs توسط اسکریپت test:indicators از
// src/utils/indicators.ts ساخته می‌شود (esbuild).
import { test } from "node:test";
import assert from "node:assert/strict";

import {
  sma,
  ema,
  bollinger,
  rsi,
  macd,
  dailyReturns,
  correlation,
  maxDrawdown,
  percentileNow,
} from "./.generated/indicators.mjs";

const near = (a, b, eps = 1e-9) => Math.abs(a - b) < eps;

test("sma: مقادیر شناخته‌شده و nullهای ابتدای دوره", () => {
  assert.deepEqual(sma([1, 2, 3, 4, 5], 3), [null, null, 2, 3, 4]);
  assert.deepEqual(sma([1, 2], 3), [null, null]);
});

test("sma با دوره ۱ همان مقادیر را برمی‌گرداند", () => {
  assert.deepEqual(sma([7, 9, 2], 1), [7, 9, 2]);
});

test("ema: seed از SMA و هموارسازی نمایی", () => {
  // [1..5], p=3: seed=sma=2, k=0.5 → [null,null,2,3,4]
  const out = ema([1, 2, 3, 4, 5], 3);
  assert.equal(out[0], null);
  assert.equal(out[1], null);
  assert.ok(near(out[2], 2));
  assert.ok(near(out[3], 3));
  assert.ok(near(out[4], 4));
});

test("ema: ورودی کوتاه‌تر از دوره → همه null", () => {
  assert.deepEqual(ema([1, 2], 5), [null, null]);
});

test("bollinger: میانگین = SMA و سری ثابت → باند‌ها روی هم", () => {
  const flat = [5, 5, 5, 5, 5];
  const bb = bollinger(flat, 4, 2);
  assert.ok(near(bb.mid[3], 5));
  assert.ok(near(bb.upper[3], 5));
  assert.ok(near(bb.lower[3], 5));
});

test("bollinger: فرمول انحراف معیار جمعیتی", () => {
  // [1,2,3], p=3 → mean=2, sd=sqrt(2/3)
  const bb = bollinger([1, 2, 3], 3, 2);
  assert.ok(near(bb.mid[2], 2));
  assert.ok(near(bb.upper[2], 2 + 2 * Math.sqrt(2 / 3)));
  assert.ok(near(bb.lower[2], 2 - 2 * Math.sqrt(2 / 3)));
});

test("rsi: رشد پیوسته → ۱۰۰ (بدون افت)", () => {
  const up = Array.from({ length: 16 }, (_, i) => i + 1);
  const out = rsi(up, 14);
  assert.equal(out[13], null);
  assert.ok(near(out[14], 100));
  assert.ok(near(out[15], 100));
});

test("rsi: بعد از یک روز افت مقدار کم می‌شود", () => {
  const series = Array.from({ length: 16 }, (_, i) => i + 1);
  series[15] = 15; // روز آخر بدون تغییر
  const out = rsi(series, 14);
  assert.ok(near(out[15], 100));
  series[15] = 10; // افت
  const out2 = rsi(series, 14);
  assert.ok(out2[15] < 100 && out2[15] > 0);
});

test("dailyReturns: لگاریتم بازده", () => {
  const r = dailyReturns([100, 110, 121]);
  assert.equal(r.length, 2);
  assert.ok(near(r[0], Math.log(1.1)));
  assert.ok(near(r[1], Math.log(1.1)));
});

test("correlation: هم‌خطی کامل مثبت/منفی و سری ثابت", () => {
  assert.ok(near(correlation([1, 2, 3], [2, 4, 6]), 1));
  assert.ok(near(correlation([1, 2, 3], [3, 2, 1]), -1));
  assert.equal(correlation([1, 1, 1], [1, 2, 3]), null);
  assert.equal(correlation([1, 2], [1, 2]), null); // کمتر از ۳ نمونه
});

test("maxDrawdown: افت از سقف", () => {
  assert.ok(near(maxDrawdown([100, 120, 60, 90]), 50));
  assert.ok(near(maxDrawdown([10, 11, 12]), 0));
});

test("percentileNow: جایگاه آخرین مقدار در بازه", () => {
  assert.ok(near(percentileNow([1, 2, 3, 4, 5]), 1));
  assert.ok(near(percentileNow([5, 4, 3, 2, 1]), 0));
  assert.ok(near(percentileNow([3, 1, 3, 1, 2]), 0.5)); // آخرین = وسط بازه
  assert.ok(near(percentileNow([2, 2, 2]), 0.5)); // بازه ثابت
  assert.equal(percentileNow([]), null);
});

test("macd: سری ثابت → مکدی، سیگنال و هیستوگرام صفر", () => {
  const flat = Array.from({ length: 40 }, () => 100);
  const m = macd(flat, 3, 6, 2); // دوره‌های کوچک برای سری کوتاه
  const last = flat.length - 1;
  assert.ok(near(m.macd[last], 0));
  assert.ok(near(m.signal[last], 0));
  assert.ok(near(m.hist[last], 0));
});

test("macd: رشد صعودی → مکدی مثبت و هیستوگرام = مکدی منهای سیگنال", () => {
  const up = Array.from({ length: 60 }, (_, i) => 100 + i);
  const m = macd(up, 3, 6, 2);
  const last = up.length - 1;
  assert.ok(m.macd[last] > 0);
  assert.ok(near(m.hist[last], m.macd[last] - m.signal[last]));
  // قبل از تشکیل هر دو EMA همه null
  assert.equal(m.macd[0], null);
});

test("macd: نزول → مکدی منفی", () => {
  const down = Array.from({ length: 60 }, (_, i) => 200 - i);
  const m = macd(down, 3, 6, 2);
  assert.ok(m.macd[down.length - 1] < 0);
});
