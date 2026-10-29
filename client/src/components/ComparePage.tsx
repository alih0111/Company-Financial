// صفحه «مقایسه و نسبت» — دو قابلیت کلیدی برای تحلیل بازار ایران:
//
// ۱) نسبت A/B: قیمت نماد اول بر حسب نماد دوم (مثلاً «فولاد به طلا» = هر سهم
//    فولاد چند واحد عیار می‌ارزد). همان چیزی که در TradingView «Ratio chart»
//    نام دارد و برای دیدن قیمت واقعی سهام بر حسب طلا/دلار به کار می‌رود.
// ۲) عملکرد مقایسه‌ای: چند نماد از یک تاریخ مشترک روی پایه‌ی ۱۰۰ رسم
//    می‌شوند تا رشد نسبی‌شان قابل مقایسه باشد.
//
// همه‌ی محاسبات سمت کلاینت است و از همان اندپوینت price-history موجود
// تغذیه می‌کند — نیازی به تغییر بک‌اند ندارد.

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type Time,
  type UTCTimestamp,
} from "lightweight-charts";
import { FaBalanceScale, FaChartLine, FaInfoCircle } from "react-icons/fa";
import { getPriceHistory, type PriceHistoryRow } from "../utils/api";
import { useDarkMode } from "../utils/theme";
import AssetSelect from "./AssetSelect";
import { baseChartOptions, jalaliParts } from "../utils/chartHelpers";
import { correlation, dailyReturns, maxDrawdown, percentileNow, sma } from "../utils/indicators";

type Mode = "ratio" | "perf";

const RANGES = [
  { key: "3m", label: "۳ ماه", days: 100 },
  { key: "6m", label: "۶ ماه", days: 190 },
  { key: "1y", label: "۱ سال", days: 380 },
  { key: "2y", label: "۲ سال", days: 760 },
  { key: "5y", label: "۵ سال", days: 1300 },
  { key: "max", label: "حداکثر", days: 3000 },
] as const;

const PALETTE = ["#10b981", "#0ea5e9", "#f59e0b", "#a78bfa", "#f43f5e"];

const PRESETS: {
  label: string;
  mode: Mode;
  base?: string;
  quote?: string;
  symbols?: string[];
}[] = [
  { label: "فولاد به طلا", mode: "ratio", base: "فولاد مبارکه", quote: "عیار" },
  { label: "بورس به طلا", mode: "ratio", base: "شاخص کل", quote: "عیار" },
  { label: "عیار / مثقال", mode: "ratio", base: "عیار", quote: "مثقال" },
  { label: "طلا در برابر بورس", mode: "perf", symbols: ["عیار", "مثقال", "شاخص کل"] },
  { label: "فلزات بنیادی", mode: "perf", symbols: ["فولاد مبارکه", "فملی", "کچاد"] },
];

// ── کش ماژولی تاریخچه — بین حالت‌ها و رفرش‌های صفحه مشترک ──
const histCache = new Map<string, { at: number; rows: PriceHistoryRow[] }>();
const HIST_TTL = 5 * 60 * 1000;

async function fetchHistoryCached(key: string, limit: number): Promise<PriceHistoryRow[]> {
  const ck = `${key}#${limit}`;
  const hit = histCache.get(ck);
  if (hit && Date.now() - hit.at < HIST_TTL) return hit.rows;
  const rows = await getPriceHistory(key, limit);
  histCache.set(ck, { at: Date.now(), rows });
  return rows;
}

// آخرین قیمت هر روز (ردیف‌ها جدیدترین اول‌اند؛ تکراری‌ها دور ریخته می‌شوند)
function dailyCloses(rows: PriceHistoryRow[]): Map<string, number> {
  const map = new Map<string, number>();
  for (const r of rows) {
    if (r.closing_price > 0 && !map.has(r.date)) map.set(r.date, r.closing_price);
  }
  return map;
}

const fmtNum = (n: number): string => {
  const a = Math.abs(n);
  if (a >= 1000) return n.toLocaleString("en-US", { maximumFractionDigits: 0 });
  if (a >= 10) return n.toFixed(1);
  if (a >= 1) return n.toFixed(2);
  return n.toFixed(3);
};
const fmtPct = (n: number): string => `${n >= 0 ? "+" : ""}${n.toFixed(1)}%`;

const ComparePage: React.FC = () => {
  const { darkMode: dark } = useDarkMode();
  const [searchParams, setSearchParams] = useSearchParams();

  // ── وضعیت از URL خوانده می‌شود تا لینک مستقیم (مثلاً از صفحه بازار) کار کند ──
  const [mode, setMode] = useState<Mode>(() =>
    searchParams.get("mode") === "perf" ? "perf" : "ratio",
  );
  const [base, setBase] = useState(() => searchParams.get("base") || "فولاد مبارکه");
  const [quote, setQuote] = useState(() => searchParams.get("quote") || "عیار");
  const [perfSymbols, setPerfSymbols] = useState<string[]>(() => {
    const s = searchParams.get("symbols");
    if (s) return s.split(",").filter(Boolean).slice(0, 5);
    return ["عیار", "مثقال", "شاخص کل"];
  });
  const [rangeKey, setRangeKey] = useState<string>(() => {
    const r = searchParams.get("range");
    return RANGES.some((x) => x.key === r) ? (r as string) : "1y";
  });

  const range = RANGES.find((r) => r.key === rangeKey) ?? RANGES[2];

  // همگام‌سازی URL برای اشتراک‌گذاری لینک تحلیل (پارامتر dev مثل __mock حفظ می‌شود)
  useEffect(() => {
    const p = new URLSearchParams();
    if (searchParams.has("__mock")) p.set("__mock", "1");
    p.set("mode", mode);
    p.set("range", rangeKey);
    if (mode === "ratio") {
      p.set("base", base);
      p.set("quote", quote);
    } else {
      p.set("symbols", perfSymbols.join(","));
    }
    setSearchParams(p, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mode, base, quote, perfSymbols, rangeKey]);

  // در حالت نسبت هر دو نماد لازم است؛ در حالت عملکرد همه‌ی سری‌ها
  const activeSymbols = mode === "ratio" ? [base, quote] : perfSymbols;
  // کلیدهای وابستگی به‌صورت رشته — تا آرایه/شیء جدید در هر رندر افکت را دوباره اجرا نکند
  const activeKey = activeSymbols.join(",");
  const perfKey = perfSymbols.join(",");

  // ── واکشی تاریخچه‌ها ──
  const [histories, setHistories] = useState<
    Record<string, { rows?: PriceHistoryRow[]; error?: string; loading: boolean }>
  >({});
  const fetchTick = useRef(0);

  useEffect(() => {
    const keys = mode === "ratio" ? [base, quote] : perfSymbols;
    if (keys.some((k) => !k)) return;
    const tick = ++fetchTick.current;
    setHistories((prev) => {
      const next: typeof prev = {};
      for (const k of keys) next[k] = prev[k] ?? { loading: true };
      return next;
    });
    (async () => {
      for (const k of keys) {
        try {
          const rows = await fetchHistoryCached(k, range.days);
          if (tick !== fetchTick.current) return;
          setHistories((prev) => ({ ...prev, [k]: { rows, loading: false } }));
        } catch (e: any) {
          if (tick !== fetchTick.current) return;
          setHistories((prev) => ({
            ...prev,
            [k]: { error: e?.message || "خطا در دریافت تاریخچه", loading: false },
          }));
        }
      }
    })();
  }, [mode, base, quote, perfKey, range.days]);

  // ── الحاق روی تاریخ‌های مشترک ──
  const joined = useMemo(() => {
    const maps = activeSymbols.map((k) => ({
      key: k,
      map: histories[k]?.rows ? dailyCloses(histories[k].rows!) : null,
    }));
    if (maps.some((m) => !m.map) || maps.some((m) => m.map!.size === 0)) return null;

    const sets = maps.map((m) => m.map!);
    const common = [...sets[0].keys()].filter((d) => sets.every((s) => s.has(d))).sort();
    if (common.length === 0) return null;

    const series: Record<string, number[]> = {};
    for (const m of maps) series[m.key] = common.map((d) => m.map!.get(d)!);
    return { dates: common, series };
    // activeKey صرفاً کلید کش است؛ خود activeSymbols از حالت/کلیدهای پایدار می‌آید
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeKey, histories]);

  // ── محاسبات آماری ──
  const analysis = useMemo(() => {
    if (!joined) return null;
    const { dates, series } = joined;
    const keys = Object.keys(series);

    if (mode === "ratio") {
      const [a, b] = [series[base], series[quote]];
      if (!a || !b) return null;
      const ratios = a.map((v, i) => v / b[i]);
      const last = ratios[ratios.length - 1];
      const first = ratios[0];
      const min = Math.min(...ratios);
      const max = Math.max(...ratios);
      const mean = ratios.reduce((s, v) => s + v, 0) / ratios.length;
      return {
        kind: "ratio" as const,
        ratios,
        ratioSma50: sma(ratios, 50),
        last,
        changePct: first > 0 ? ((last - first) / first) * 100 : 0,
        min,
        max,
        mean,
        percentile: percentileNow(ratios),
        lastA: a[a.length - 1],
        lastB: b[b.length - 1],
        days: dates.length,
      };
    }

    // perf: هر سری به پایه‌ی ۱۰۰ از اولین روز مشترک
    const rebased: Record<string, number[]> = {};
    const statsList: {
      key: string;
      ret: number;
      dailyVol: number;
      mdd: number;
    }[] = [];
    for (const k of keys) {
      const s = series[k];
      const base0 = s[0];
      const rb = s.map((v) => (v / base0) * 100);
      rebased[k] = rb;
      const ret = (s[s.length - 1] / base0 - 1) * 100;
      const rets = dailyReturns(s);
      const mu = rets.reduce((x, y) => x + y, 0) / (rets.length || 1);
      const dailyVol =
        Math.sqrt(rets.reduce((x, y) => x + (y - mu) ** 2, 0) / (rets.length || 1)) * 100;
      statsList.push({ key: k, ret, dailyVol, mdd: maxDrawdown(rb) });
    }
    // ماتریس همبستگی بازده‌های روزانه
    const corr: Record<string, Record<string, number | null>> = {};
    for (const k1 of keys) {
      corr[k1] = {};
      for (const k2 of keys) {
        corr[k1][k2] =
          k1 === k2 ? 1 : correlation(dailyReturns(series[k1]), dailyReturns(series[k2]));
      }
    }
    return {
      kind: "perf" as const,
      rebased,
      statsList: statsList.sort((x, y) => y.ret - x.ret),
      corr,
      days: dates.length,
      startDate: dates[0],
      endDate: dates[dates.length - 1],
    };
  }, [joined, mode, base, quote]);

  // ── نمودار ──
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const [hover, setHover] = useState<{ date: string; rows: { key: string; value: number; color: string }[] } | null>(null);

  const seriesSig = mode === "ratio" ? `${base}|${quote}` : perfSymbols.join("|");
  const hasData = Boolean(joined && analysis);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || !joined || !analysis) return;

    const chart = createChart(el, {
      ...baseChartOptions(dark),
      width: el.clientWidth,
      height: 460,
      rightPriceScale: { borderVisible: false, scaleMargins: { top: 0.08, bottom: 0.08 } },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        minBarSpacing: 3,
        fixLeftEdge: true,
        fixRightEdge: false,
      },
      localization: {
        locale: "fa-IR",
        timeFormatter: (t: Time) => jalaliParts(t).full,
        priceFormatter: (v: number) => fmtNum(v),
      },
    });
    chartRef.current = chart;

    const times = joined.dates.map(
      (d) => Math.floor(new Date(d + "T00:00:00Z").getTime() / 1000) as UTCTimestamp,
    );

    const lines: { key: string; series: ISeriesApi<"Line">; color: string }[] = [];

    if (analysis.kind === "ratio") {
      const main = chart.addLineSeries({
        color: "#10b981",
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      main.setData(
        analysis.ratios
          .map((v, i) => ({ time: times[i], value: v }))
          .filter((p) => Number.isFinite(p.value)),
      );
      lines.push({ key: base, series: main, color: "#10b981" });

      const smaSeries = chart.addLineSeries({
        color: "#f59e0b",
        lineWidth: 1,
        lineStyle: 2,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      smaSeries.setData(
        analysis.ratioSma50
          .map((v, i) => (v == null ? null : { time: times[i], value: v }))
          .filter((p): p is { time: UTCTimestamp; value: number } => p !== null),
      );
      lines.push({ key: "sma50", series: smaSeries, color: "#f59e0b" });
    } else {
      analysis.statsList.forEach((st, i) => {
        const color = PALETTE[i % PALETTE.length];
        const s = chart.addLineSeries({
          color,
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });
        s.setData(analysis.rebased[st.key].map((v, i2) => ({ time: times[i2], value: v })));
        lines.push({ key: st.key, series: s, color });
      });
    }

    chart.timeScale().fitContent();

    // لجند کراس‌هیر
    const onMove = (param: any) => {
      if (!param || !param.time) {
        setHover(null);
        return;
      }
      const idx = times.findIndex((t) => t === param.time);
      if (idx < 0) {
        setHover(null);
        return;
      }
      const rows = lines
        .filter((l) => l.key !== "sma50")
        .map((l) => {
          const pt = param.seriesData.get(l.series) as { value: number } | undefined;
          const raw =
            analysis.kind === "ratio"
              ? analysis.ratios[idx]
              : analysis.rebased[l.key]?.[idx];
          return {
            key: l.key,
            value: pt?.value ?? raw ?? NaN,
            color: l.color,
          };
        });
      setHover({
        date: jalaliParts(param.time).full,
        rows,
      });
    };
    chart.subscribeCrosshairMove(onMove);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.applyOptions({ width: Math.round(w) });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      chartRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, seriesSig, rangeKey, hasData, joined, analysis]);

  const applyPreset = useCallback((p: (typeof PRESETS)[number]) => {
    setMode(p.mode);
    if (p.mode === "ratio") {
      if (p.base) setBase(p.base);
      if (p.quote) setQuote(p.quote);
    } else if (p.symbols) {
      setPerfSymbols(p.symbols);
    }
  }, []);

  const loading = activeSymbols.some((k) => histories[k]?.loading);
  const errors = activeSymbols
    .map((k) => ({ k, e: histories[k]?.error }))
    .filter((x) => x.e);

  const cardCls = `rounded-2xl border ${
    dark ? "bg-gray-800/50 border-gray-700/60" : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const pillCls = (active: boolean) =>
    `px-3 py-1.5 rounded-xl text-[11px] font-semibold transition-all duration-200 ${
      active
        ? "bg-emerald-600 text-white shadow-sm shadow-emerald-500/25"
        : dark
          ? "bg-gray-700/50 text-gray-300 hover:bg-gray-700"
          : "bg-gray-100 text-gray-600 hover:bg-gray-200"
    }`;

  return (
    <div className="flex flex-col gap-4">
      {/* ── سربرگ ── */}
      <div className={`${cardCls} p-4 flex items-center justify-between flex-wrap gap-3`}>
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br from-sky-500 to-indigo-600 text-white shadow-sm">
            <FaBalanceScale size={14} />
          </span>
          <div>
            <h2 className="font-bold text-gray-800 dark:text-white text-sm">
              مقایسه و نسبت نمادها
            </h2>
            <p className="text-[11px] text-gray-500 dark:text-gray-400">
              قیمت هر نماد بر حسب نماد دیگر (مثل سهم به طلا) یا مقایسه‌ی عملکرد چند نماد
            </p>
          </div>
        </div>
      </div>

      {/* ── کنترل‌ها ── */}
      <div className={`${cardCls} p-4 flex flex-col gap-3`}>
        <div className="flex flex-wrap items-center gap-2">
          {/* حالت */}
          <div className="flex gap-0.5 p-0.5 rounded-xl bg-gray-100 dark:bg-gray-700/40">
            <button
              onClick={() => setMode("ratio")}
              className={pillCls(mode === "ratio")}
            >
              نسبت A / B
            </button>
            <button onClick={() => setMode("perf")} className={pillCls(mode === "perf")}>
              عملکرد مقایسه‌ای
            </button>
          </div>
          {/* بازه */}
          <div className="flex gap-0.5 p-0.5 rounded-xl bg-gray-100 dark:bg-gray-700/40">
            {RANGES.map((r) => (
              <button key={r.key} onClick={() => setRangeKey(r.key)} className={pillCls(rangeKey === r.key)}>
                {r.label}
              </button>
            ))}
          </div>
        </div>

        {/* انتخاب نماد */}
        {mode === "ratio" ? (
          <div className="grid grid-cols-1 md:grid-cols-[1fr_auto_1fr] gap-2 items-center">
            <div>
              <label className="mb-1 block px-1 text-[10px] font-bold text-gray-500 dark:text-gray-400">
                نماد اول (صورت نسبت)
              </label>
              <AssetSelect
                value={[base]}
                max={1}
                placeholder="مثلاً فولاد مبارکه"
                onChange={(v) => v[0] && setBase(v[0])}
              />
            </div>
            <div className="flex items-end justify-center pb-1.5">
              <span className="w-8 h-8 rounded-full bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 flex items-center justify-center font-bold text-sm">
                ÷
              </span>
            </div>
            <div>
              <label className="mb-1 block px-1 text-[10px] font-bold text-gray-500 dark:text-gray-400">
                نماد دوم (مبنای نسبت)
              </label>
              <AssetSelect
                value={[quote]}
                max={1}
                placeholder="مثلاً عیار"
                onChange={(v) => v[0] && setQuote(v[0])}
              />
            </div>
          </div>
        ) : (
          <div>
            <label className="mb-1 block px-1 text-[10px] font-bold text-gray-500 dark:text-gray-400">
              نمادها (حداکثر ۵ عدد)
            </label>
            <AssetSelect
              value={perfSymbols}
              max={5}
              placeholder="نمادها را انتخاب کنید…"
              onChange={setPerfSymbols}
            />
          </div>
        )}

        {/* پیش‌تنظیم‌ها */}
        <div className="flex flex-wrap items-center gap-1.5 pt-1 border-t border-gray-100 dark:border-gray-700/50">
          <span className="text-[10px] font-bold text-gray-400 pt-1">تحلیل‌های آماده:</span>
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              className="text-[11px] px-2.5 py-1 rounded-full border border-sky-500/30 text-sky-700 dark:text-sky-300 hover:bg-sky-500/10 transition-colors"
            >
              {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* خطاها */}
      {errors.length > 0 && (
        <div className="rounded-2xl border border-red-200 dark:border-red-900/50 bg-red-50/70 dark:bg-red-950/20 px-4 py-2 text-xs text-red-600 dark:text-red-300">
          {errors.map((x) => (
            <p key={x.k}>
              «{x.k}»: {x.e}
            </p>
          ))}
        </div>
      )}

      {loading && (
        <div className={`${cardCls} p-10 flex items-center justify-center gap-3 text-gray-500 dark:text-gray-400`}>
          <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24" fill="none">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
          </svg>
          <span className="text-sm font-medium">در حال دریافت تاریخچه‌ها…</span>
        </div>
      )}

      {/* ── نمودار + آمار ── */}
      {!loading && analysis && (
        <>
          {analysis.days < 10 && (
            <div className="rounded-2xl border border-amber-200 dark:border-amber-900/50 bg-amber-50/70 dark:bg-amber-950/20 px-4 py-2 text-xs text-amber-700 dark:text-amber-300 flex items-center gap-2">
              <FaInfoCircle />
              فقط {analysis.days.toLocaleString("fa-IR")} روز معامله‌ی مشترک بین این دو
              نماد در این بازه وجود دارد — نمودار ممکن است ناکافی باشد.
            </div>
          )}

          <div className={`${cardCls} p-4`}>
            <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
              <h3 className="font-bold text-gray-800 dark:text-white text-sm flex items-center gap-2">
                <FaChartLine className="text-emerald-500 text-xs" />
                {mode === "ratio" ? (
                  <span>
                    {base} <span className="text-gray-400">÷</span> {quote}
                    <span className="text-[10px] font-medium text-gray-400 mr-2">
                      ({base} بر حسب {quote})
                    </span>
                  </span>
                ) : (
                  <span>
                    عملکرد مقایسه‌ای
                    <span className="text-[10px] font-medium text-gray-400 mr-2">(پایه = ۱۰۰)</span>
                  </span>
                )}
              </h3>
              {/* لجند */}
              <div className="flex items-center gap-3 text-[11px] font-semibold tabular-nums min-h-[16px]" dir="ltr">
                {hover ? (
                  <>
                    <span className="text-gray-400">{hover.date}</span>
                    {hover.rows.map((r) => (
                      <span key={r.key} style={{ color: r.color }}>
                        {r.key}: <b>{fmtNum(r.value)}</b>
                      </span>
                    ))}
                  </>
                ) : (
                  <span className="text-gray-400" dir="rtl">
                    با نشانگر روی نمودار حرکت کنید
                  </span>
                )}
              </div>
            </div>
            <div ref={containerRef} dir="ltr" className="rounded-xl overflow-hidden" style={{ height: 460 }} />
            {mode === "ratio" && (
              <p className="mt-2 text-[10px] text-gray-400 flex items-center gap-1.5">
                <span className="inline-block w-4 h-0.5 bg-amber-400 rounded" /> میانگین متحرک ۵۰ روزه‌ی نسبت
              </p>
            )}
          </div>

          {/* ── کارت‌های آمار ── */}
          {analysis.kind === "ratio" ? (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-2">
              <StatBox label={`آخرین نسبت (${analysis.days.toLocaleString("fa-IR")} روز)`} value={fmtNum(analysis.last)} />
              <StatBox
                label="تغییر نسبت در دوره"
                value={fmtPct(analysis.changePct)}
                tone={analysis.changePct >= 0 ? "up" : "down"}
              />
              <StatBox label="کمینه" value={fmtNum(analysis.min)} />
              <StatBox label="بیشینه" value={fmtNum(analysis.max)} />
              <StatBox label="میانگین" value={fmtNum(analysis.mean)} />
              <StatBox
                label="جایگاه فعلی در بازه"
                value={analysis.percentile != null ? `${Math.round(analysis.percentile * 100)}٪` : "—"}
                tone={analysis.percentile != null ? (analysis.percentile > 0.7 ? "high" : analysis.percentile < 0.3 ? "low" : undefined) : undefined}
              />
            </div>
          ) : (
            <>
              <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
                {analysis.statsList.map((st, i) => (
                  <div
                    key={st.key}
                    className={`${cardCls} p-3 flex flex-col gap-1.5 border-r-2`}
                    style={{ borderRightColor: PALETTE[i % PALETTE.length] }}
                  >
                    <span className="text-xs font-bold text-gray-700 dark:text-gray-200 truncate">
                      {st.key}
                    </span>
                    <span
                      className={`text-sm font-bold tabular-nums ${
                        st.ret >= 0 ? "text-emerald-600 dark:text-emerald-400" : "text-red-500 dark:text-red-400"
                      }`}
                    >
                      {fmtPct(st.ret)}
                    </span>
                    <div className="flex justify-between text-[10px] text-gray-500 dark:text-gray-400 tabular-nums">
                      <span>ریسک روزانه {st.dailyVol.toFixed(2)}٪</span>
                      <span>بیشینه‌افت {st.mdd.toFixed(0)}٪</span>
                    </div>
                  </div>
                ))}
              </div>

              {/* همبستگی بازده‌های روزانه */}
              {analysis.statsList.length >= 2 && (
                <div className={`${cardCls} p-4 overflow-x-auto`}>
                  <h4 className="text-xs font-bold text-gray-700 dark:text-gray-200 mb-2">
                    همبستگی بازده‌های روزانه
                  </h4>
                  <table className="text-[11px] tabular-nums border-collapse">
                    <thead>
                      <tr>
                        <th className="p-1.5" />
                        {analysis.statsList.map((s) => (
                          <th key={s.key} className="p-1.5 font-semibold text-gray-600 dark:text-gray-300 whitespace-nowrap">
                            {s.key}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.statsList.map((r) => (
                        <tr key={r.key}>
                          <td className="p-1.5 font-semibold text-gray-600 dark:text-gray-300 whitespace-nowrap">
                            {r.key}
                          </td>
                          {analysis.statsList.map((c) => {
                            const v = analysis.corr[r.key]?.[c.key];
                            return (
                              <td key={c.key} className="p-1.5 text-center">
                                {v == null ? (
                                  "—"
                                ) : (
                                  <span
                                    className="inline-block px-2 py-0.5 rounded-md font-semibold"
                                    style={{
                                      background:
                                        v >= 0
                                          ? `rgba(16,185,129,${0.08 + Math.abs(v) * 0.3})`
                                          : `rgba(239,68,68,${0.08 + Math.abs(v) * 0.3})`,
                                      color: v >= 0 ? "#059669" : "#dc2626",
                                    }}
                                  >
                                    {v.toFixed(2)}
                                  </span>
                                )}
                              </td>
                            );
                          })}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}

          <p className="text-[10px] text-gray-400 px-1">
            محاسبات بر پایه‌ی قیمت پایانی (سری تعدیل‌شده) است؛ فقط روزهای دارای معامله‌ی
            مشترک در هر دو سری لحاظ می‌شود.
          </p>
        </>
      )}

      {!loading && !analysis && errors.length === 0 && (
        <div className={`${cardCls} p-10 text-center text-sm text-gray-500 dark:text-gray-400`}>
          داده‌ی مشترکی برای این انتخاب‌ها پیدا نشد — نمادها یا بازه‌ی زمانی را عوض کنید.
        </div>
      )}
    </div>
  );
};

const StatBox: React.FC<{
  label: string;
  value: string;
  tone?: "up" | "down" | "high" | "low";
}> = ({ label, value, tone }) => (
  <div className="rounded-xl bg-gray-50 dark:bg-gray-800/40 p-2.5 text-center border border-gray-100 dark:border-gray-700/40">
    <div className="text-[10px] text-gray-500 dark:text-gray-400 font-medium mb-0.5">{label}</div>
    <div
      className={`text-sm font-bold tabular-nums ${
        tone === "up" || tone === "high"
          ? "text-emerald-600 dark:text-emerald-400"
          : tone === "down" || tone === "low"
            ? "text-red-500 dark:text-red-400"
            : "text-gray-800 dark:text-white"
      }`}
    >
      {value}
    </div>
  </div>
);

export default ComparePage;
