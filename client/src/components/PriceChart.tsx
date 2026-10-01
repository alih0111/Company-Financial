import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
  ColorType,
  CrosshairMode,
  PriceScaleMode,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from "lightweight-charts";
import {
  FaChartLine,
  FaDownload,
  FaSync,
  FaArrowUp,
  FaArrowDown,
} from "react-icons/fa";
import {
  getPriceHistory,
  collectBrsPrices,
  type PriceHistoryRow,
} from "../utils/api";
import { getAuthStatus } from "../hooks/useGetUser";
import { useDarkMode } from "../utils/theme";

type Props = {
  companyName: string;
  refreshTick?: number;
};

const RANGES = [
  { label: "۱ماه", days: 30 },
  { label: "۳ماه", days: 90 },
  { label: "۶ماه", days: 180 },
  { label: "۱سال", days: 365 },
  { label: "همه", days: 5000 },
];

// رنگ‌های کندل مطابق هویت سبز/قرمز مالی
const C = {
  up: "#10b981",
  down: "#ef4444",
  upFill: "rgba(16,185,129,0.55)",
  downFill: "rgba(239,68,68,0.55)",
};

type CandlePoint = {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
};

type VolumePoint = {
  time: UTCTimestamp;
  value: number;
  color: string;
};

const PriceChart: React.FC<Props> = ({ companyName, refreshTick = 0 }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;
  const [data, setData] = useState<PriceHistoryRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [rangeIdx, setRangeIdx] = useState(2);
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<string | null>(null);
  const [logScale, setLogScale] = useState(true);
  const { isAdmin } = getAuthStatus();

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // برای auto-extend هنگام زوم‌اوت
  const candlesRef = useRef<CandlePoint[]>([]);
  const rangeIdxRef = useRef(rangeIdx);
  const loadingRef = useRef(false);
  const autoExtendRef = useRef(false);
  rangeIdxRef.current = rangeIdx;
  const [hover, setHover] = useState<{
    date: string;
    o: number;
    h: number;
    l: number;
    c: number;
    vol: number;
    chg: number;
  } | null>(null);

  const loadData = () => {
    if (!companyName) return;
    loadingRef.current = true;
    setLoading(true);
    setError(null);
    getPriceHistory(companyName, RANGES[rangeIdx].days)
      .then((rows) => {
        setData(rows.reverse());
      })
      .catch((e) => setError(e?.message || "خطا"))
      .finally(() => {
        loadingRef.current = false;
        setLoading(false);
      });
  };

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName, rangeIdx, refreshTick]);

  const handleFetchPrices = async () => {
    setFetching(true);
    setFetchMsg(null);
    try {
      await collectBrsPrices("backfill", {
        symbol: companyName,
        raw: true,
        limit: 0,
      });
      setFetchMsg("قیمت‌ها جمع شد ✓");
      setTimeout(() => {
        loadData();
        setFetchMsg(null);
      }, 2000);
    } catch (e: any) {
      setFetchMsg(e?.message || "خطا در جمع‌آوری قیمت");
    } finally {
      setFetching(false);
    }
  };

  // ساخت کندل: open = قیمت پایانی روز قبل، close = آخرین معامله، high/low از داده
  const { candles, volumes, jalaliMap } = useMemo(() => {
    const candles: CandlePoint[] = [];
    const volumes: VolumePoint[] = [];
    const jalaliMap = new Map<number, { jdate: string; chg: number }>();

    const clean = data
      .filter((d) => d.closing_price > 0)
      .slice()
      .sort((a, b) => (a.date < b.date ? -1 : 1));

    let prevClose = 0;
    const seen = new Set<string>();
    for (const d of clean) {
      if (seen.has(d.date)) continue;
      seen.add(d.date);

      const open = prevClose > 0 ? prevClose : d.closing_price;
      const close = d.last_price > 0 ? d.last_price : d.closing_price;
      const rawHigh = d.high_price > 0 ? d.high_price : Math.max(open, close);
      const rawLow = d.low_price > 0 ? d.low_price : Math.min(open, close);
      const high = Math.max(rawHigh, open, close);
      const low = Math.min(rawLow, open, close);

      // time به‌صورت UTC timestamp از روی رشته‌ی YYYY-MM-DD
      const t = Math.floor(
        new Date(d.date + "T00:00:00Z").getTime() / 1000,
      ) as UTCTimestamp;

      candles.push({ time: t, open, high, low, close });
      volumes.push({
        time: t,
        value: d.volume || 0,
        color: close >= open ? C.upFill : C.downFill,
      });
      jalaliMap.set(t, {
        jdate: d.jalali_date || d.date,
        chg: d.change_percent || 0,
      });
      prevClose = d.closing_price;
    }
    return { candles, volumes, jalaliMap };
  }, [data]);

  const stats = useMemo(() => {
    if (candles.length === 0) return null;
    const closes = candles.map((c) => c.close);
    const latest = closes[closes.length - 1];
    const max = Math.max(...candles.map((c) => c.high));
    const min = Math.min(...candles.map((c) => c.low));
    const first = candles[0].open;
    const totalReturn = first > 0 ? ((latest - first) / first) * 100 : 0;
    return { latest, max, min, totalReturn };
  }, [candles]);

  const priceFmt = (n: number) =>
    n.toLocaleString("en-US", { maximumFractionDigits: 0 });

  const volFmt = (n: number) => {
    if (n >= 1e9) return (n / 1e9).toFixed(1) + "B";
    if (n >= 1e6) return (n / 1e6).toFixed(1) + "M";
    if (n >= 1e3) return (n / 1e3).toFixed(1) + "K";
    return String(Math.round(n));
  };

  // ── ساخت چارت — وقتی داده رسید و container در DOM قرار گرفت ──
  const hasData = candles.length > 0;
  useEffect(() => {
    const el = containerRef.current;
    if (!el || !hasData) return;

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 400,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: dark ? "#94a3b8" : "#64748b",
        fontFamily: '"Vazirmatn", "Segoe UI", Tahoma, system-ui, sans-serif',
        fontSize: 11,
      },
      grid: {
        vertLines: { visible: false },
        horzLines: {
          color: dark ? "rgba(148,163,184,0.08)" : "rgba(100,116,139,0.1)",
        },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: {
          color: dark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.35)",
          width: 1,
          style: 2,
          labelBackgroundColor: dark ? "#334155" : "#475569",
        },
        horzLine: {
          color: dark ? "rgba(148,163,184,0.35)" : "rgba(100,116,139,0.35)",
          labelBackgroundColor: dark ? "#334155" : "#475569",
        },
      },
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.26 },
      },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        barSpacing: 9,
        minBarSpacing: 2,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: true },
        axisDoubleClickReset: { time: true, price: true },
        mouseWheel: true,
        pinch: true,
      },
    });

    const candleSeries = chart.addCandlestickSeries({
      upColor: C.up,
      downColor: C.down,
      borderVisible: false,
      wickUpColor: C.up,
      wickDownColor: C.down,
      priceLineColor: dark ? "rgba(148,163,184,0.5)" : "rgba(100,116,139,0.5)",
      priceLineStyle: 3,
    });

    const volumeSeries = chart.addHistogramSeries({
      priceFormat: { type: "volume" },
      priceScaleId: "vol",
      lastValueVisible: false,
      priceLineVisible: false,
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candleRef.current = candleSeries;
    volumeRef.current = volumeSeries;

    // ResizeObserver برای واکنش‌گرایی
    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.applyOptions({ width: Math.round(w) });
    });
    ro.observe(el);

    // Crosshair → legend
    const onMove = (param: any) => {
      if (!param || !param.time) {
        setHover(null);
        return;
      }
      const bar = param.seriesData.get(candleSeries) as
        | { open: number; high: number; low: number; close: number }
        | undefined;
      const v = param.seriesData.get(volumeSeries) as
        | { value: number }
        | undefined;
      if (!bar) {
        setHover(null);
        return;
      }
      const meta = jalaliMap.get(param.time as number);
      setHover({
        date: meta?.jdate || String(param.time),
        o: bar.open,
        h: bar.high,
        l: bar.low,
        c: bar.close,
        vol: v?.value ?? 0,
        chg: meta?.chg ?? 0,
      });
    };
    chart.subscribeCrosshairMove(onMove);

    // زوم‌اوت خودکار: اگر کاربر از ابتدای داده رد شد، بازه‌ی بزرگ‌تر لود کن
    const onRangeChange = (range: any) => {
      if (!range || loadingRef.current) return;
      if (range.from < 0.5 && candlesRef.current.length > 0) {
        const nextIdx = Math.min(rangeIdxRef.current + 1, RANGES.length - 1);
        if (nextIdx !== rangeIdxRef.current) {
          autoExtendRef.current = true;
          rangeIdxRef.current = nextIdx;
          setRangeIdx(nextIdx);
        }
      }
    };
    chart.timeScale().subscribeVisibleLogicalRangeChange(onRangeChange);

    return () => {
      ro.disconnect();
      chart.unsubscribeCrosshairMove(onMove);
      chart.timeScale().unsubscribeVisibleLogicalRangeChange(onRangeChange);
      chart.remove();
      chartRef.current = null;
      candleRef.current = null;
      volumeRef.current = null;
    };
    // jalaliMap عمداً خارج از وابستگی‌هاست؛ legend با data جدید re-render می‌شود
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, hasData]);

  // ── آپدیت داده‌ها و مقیاس ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleRef.current || !volumeRef.current) return;

    const ts = chart.timeScale();
    // اگر با زوم‌اوت خودکار داده‌ی قدیمی‌تر لود شد، جای پنجره‌ی دید کاربر را حفظ کن
    const keepView = autoExtendRef.current && candlesRef.current.length > 0;
    const prevRange = keepView ? ts.getVisibleLogicalRange() : null;
    const prevCount = candlesRef.current.length;

    candlesRef.current = candles;
    chart.priceScale("right").applyOptions({
      mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    candleRef.current.setData(candles as any);
    volumeRef.current.setData(volumes as any);
    ts.fitContent();
    if (keepView && prevRange && candles.length > prevCount) {
      const added = candles.length - prevCount;
      ts.setVisibleLogicalRange({
        from: prevRange.from + added,
        to: prevRange.to + added,
      });
    }
    autoExtendRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candles, volumes, logScale]);

  const cardCls = `rounded-2xl border p-5 ${
    dark
      ? "bg-gray-800/50 border-gray-700/60"
      : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const legendUp = hover ? hover.c >= hover.o : true;

  return (
    <div className={cardCls}>
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-emerald-500/10 text-emerald-500">
            <FaChartLine className="text-sm" />
          </span>
          <h3 className="font-bold text-gray-800 dark:text-white text-sm">
            نمودار قیمت
          </h3>
          <span className="text-[10px] font-medium text-gray-400 bg-gray-100 dark:bg-gray-700/50 px-2 py-0.5 rounded-full">
            کندل + حجم
          </span>
        </div>
        <div className="flex items-center gap-2">
          {/* Range pills */}
          <div className="flex gap-0.5 p-0.5 rounded-xl bg-gray-100 dark:bg-gray-700/40">
            {RANGES.map((r, i) => (
              <button
                key={i}
                onClick={() => setRangeIdx(i)}
                className={`px-3 py-1.5 rounded-lg text-[11px] font-medium transition-all duration-200 ${
                  i === rangeIdx
                    ? "bg-emerald-600 text-white shadow-sm shadow-emerald-500/25"
                    : dark
                      ? "text-gray-400 hover:text-gray-200 hover:bg-gray-600/40"
                      : "text-gray-500 hover:text-gray-700 hover:bg-gray-200/60"
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          {/* Log/Linear toggle */}
          <button
            onClick={() => setLogScale(!logScale)}
            title="تغییر مقیاس نمودار"
            className={`px-3 py-1.5 rounded-xl text-[11px] font-medium transition-all duration-200 ${
              logScale
                ? "bg-purple-600 text-white shadow-sm shadow-purple-500/25"
                : dark
                  ? "bg-gray-700/60 text-gray-400 hover:text-gray-200"
                  : "bg-gray-100 text-gray-500 hover:text-gray-700"
            }`}
          >
            {logScale ? "Log" : "Linear"}
          </button>
        </div>
      </div>

      {/* ── Legend / Crosshair readout ── */}
      <div
        className="flex items-center gap-4 mb-2 px-1 text-[11px] font-semibold tabular-nums min-h-[18px]"
        dir="ltr"
      >
        {hover ? (
          <>
            <span className="text-gray-400">{hover.date}</span>
            <span className="text-gray-500 dark:text-gray-400">
              O{" "}
              <b className="text-gray-700 dark:text-gray-200">
                {priceFmt(hover.o)}
              </b>
            </span>
            <span className="text-gray-500 dark:text-gray-400">
              H{" "}
              <b className="text-emerald-600 dark:text-emerald-400">
                {priceFmt(hover.h)}
              </b>
            </span>
            <span className="text-gray-500 dark:text-gray-400">
              L{" "}
              <b className="text-red-500 dark:text-red-400">
                {priceFmt(hover.l)}
              </b>
            </span>
            <span className="text-gray-500 dark:text-gray-400">
              C{" "}
              <b className="text-gray-700 dark:text-gray-200">
                {priceFmt(hover.c)}
              </b>
            </span>
            <span
              className={
                hover.chg >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-red-500 dark:text-red-400"
              }
            >
              {hover.chg >= 0 ? "+" : ""}
              {hover.chg.toFixed(2)}%
            </span>
            <span className="text-gray-400">Vol {volFmt(hover.vol)}</span>
          </>
        ) : (
          <span className="text-gray-400 dark:text-gray-500" dir="rtl">
            {candles.length > 0
              ? `${candles.length} کندل — با نشانگر روی نمودار حرکت کنید`
              : ""}
          </span>
        )}
      </div>

      {/* ── Stats Cards ── */}
      {stats && (
        <div className="grid grid-cols-4 gap-2 mb-4">
          <div className="rounded-xl bg-gray-50 dark:bg-gray-800/40 p-2.5 text-center border border-gray-100 dark:border-gray-700/40">
            <div className="text-[10px] text-gray-400 dark:text-gray-500 font-medium mb-0.5">
              آخرین قیمت
            </div>
            <div className="text-sm font-bold text-gray-800 dark:text-white tabular-nums">
              {priceFmt(stats.latest)}
            </div>
          </div>
          <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/15 p-2.5 text-center border border-emerald-100 dark:border-emerald-900/30">
            <div className="text-[10px] text-emerald-600 dark:text-emerald-400/70 font-medium mb-0.5">
              سقف
            </div>
            <div className="text-sm font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
              {priceFmt(stats.max)}
            </div>
          </div>
          <div className="rounded-xl bg-red-50 dark:bg-red-900/15 p-2.5 text-center border border-red-100 dark:border-red-900/30">
            <div className="text-[10px] text-red-500 dark:text-red-400/70 font-medium mb-0.5">
              کف
            </div>
            <div className="text-sm font-bold text-red-500 dark:text-red-400 tabular-nums">
              {priceFmt(stats.min)}
            </div>
          </div>
          <div
            className={`rounded-xl p-2.5 text-center border ${
              stats.totalReturn >= 0
                ? "bg-emerald-50 dark:bg-emerald-900/15 border-emerald-100 dark:border-emerald-900/30"
                : "bg-red-50 dark:bg-red-900/15 border-red-100 dark:border-red-900/30"
            }`}
          >
            <div
              className={`text-[10px] font-medium mb-0.5 flex items-center justify-center gap-1 ${
                stats.totalReturn >= 0
                  ? "text-emerald-600 dark:text-emerald-400/70"
                  : "text-red-500 dark:text-red-400/70"
              }`}
            >
              {stats.totalReturn >= 0 ? (
                <FaArrowUp size={8} />
              ) : (
                <FaArrowDown size={8} />
              )}
              بازده
            </div>
            <div
              className={`text-sm font-bold tabular-nums ${
                stats.totalReturn >= 0
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-red-500 dark:text-red-400"
              }`}
            >
              {stats.totalReturn >= 0 ? "+" : ""}
              {stats.totalReturn.toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <div className="h-[400px] flex items-center justify-center">
          <div className="flex items-center gap-3 text-gray-400 dark:text-gray-500">
            <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
              <circle
                className="opacity-25"
                cx="12"
                cy="12"
                r="10"
                stroke="currentColor"
                strokeWidth="4"
                fill="none"
              />
              <path
                className="opacity-75"
                fill="currentColor"
                d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
              />
            </svg>
            <span className="text-sm font-medium">در حال بارگذاری نمودار…</span>
          </div>
        </div>
      ) : error ? (
        <p className="text-center text-red-500 py-10">{error}</p>
      ) : candles.length === 0 ? (
        <div className="text-center py-10">
          <p className="text-gray-400 dark:text-gray-500 mb-4">
            داده‌ای برای این نماد موجود نیست
          </p>
          {isAdmin && (
            <button
              onClick={handleFetchPrices}
              disabled={fetching}
              className={`inline-flex items-center gap-2 px-5 py-2.5 rounded-xl font-semibold text-white text-sm shadow-lg transition-all duration-200 ${
                fetching
                  ? "bg-gray-400 cursor-not-allowed"
                  : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 hover:shadow-xl hover:shadow-emerald-500/20"
              }`}
            >
              {fetching ? (
                <>
                  <FaSync className="animate-spin" />
                  در حال جمع‌آوری…
                </>
              ) : (
                <>
                  <FaDownload />
                  جمع کردن قیمت
                </>
              )}
            </button>
          )}
          {fetchMsg && (
            <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">
              {fetchMsg}
            </p>
          )}
        </div>
      ) : (
        <div
          ref={containerRef}
          dir="ltr"
          className={`rounded-xl overflow-hidden ${legendUp ? "" : ""}`}
          style={{ height: 400 }}
        />
      )}
    </div>
  );
};

export default PriceChart;
