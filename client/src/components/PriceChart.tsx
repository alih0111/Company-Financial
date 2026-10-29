import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  createChart,
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
import WatchStar from "./WatchStar";
import {
  baseChartOptions,
  jalaliTickMark,
} from "../utils/chartHelpers";
import { bollinger, macd as macdCalc, rsi as rsiCalc, sma } from "../utils/indicators";

type Props = {
  companyName: string;
  refreshTick?: number;
};

// سقف درخواست از سرور (برابر سقف سمت بک‌اند)
const ALL_DAYS = 100000;

// رنگ‌های کندل مطابق هویت سبز/قرمز مالی
const C = {
  up: "#10b981",
  down: "#ef4444",
  upFill: "rgba(16,185,129,0.55)",
  downFill: "rgba(239,68,68,0.55)",
};

// اندیکاتورهای قابل‌نمایش — رنگ‌ها با سری‌های چارت هماهنگ‌اند
const INDICATORS: {
  key: "ma20" | "ma50" | "ma200" | "bb" | "rsi" | "macd";
  label: string;
  color: string;
}[] = [
  { key: "ma20", label: "میانگین ۲۰", color: "#f59e0b" },
  { key: "ma50", label: "میانگین ۵۰", color: "#3b82f6" },
  { key: "ma200", label: "میانگین ۲۰۰", color: "#8b5cf6" },
  { key: "bb", label: "بولینگر", color: "#94a3b8" },
  { key: "rsi", label: "RSI ۱۴", color: "#a855f7" },
  { key: "macd", label: "MACD", color: "#ec4899" },
];

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
  // تعداد رکورد درخواستی؛ با زوم‌اوت خودکار بزرگ‌تر می‌شود (بدون سقف ثابت)
  const [days, setDays] = useState(180);
  const [fetching, setFetching] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<string | null>(null);
  const [logScale, setLogScale] = useState(true);
  // اندیکاتورهای تکنیکال — پیش‌فرض: میانگین‌های ۵۰ و ۲۰۰ روشن
  const [ov, setOv] = useState({
    ma20: false,
    ma50: true,
    ma200: true,
    bb: false,
    rsi: false,
    macd: false,
  });
  const { isAdmin } = getAuthStatus();

  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const volumeRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  // سری‌های اندیکاتور روی همان مقیاس قیمت
  const overlayRef = useRef<Record<string, ISeriesApi<"Line"> | null>>({});
  // نمودار RSI جداگانه با محور زمان هم‌گام
  const rsiContainerRef = useRef<HTMLDivElement>(null);
  const rsiChartRef = useRef<IChartApi | null>(null);
  const rsiSeriesRef = useRef<ISeriesApi<"Line"> | null>(null);
  // نمودار MACD جداگانه (هیستوگرام + خط مکدی + سیگنال)
  const macdContainerRef = useRef<HTMLDivElement>(null);
  const macdChartRef = useRef<IChartApi | null>(null);
  const macdHistRef = useRef<ISeriesApi<"Histogram"> | null>(null);
  const macdLineRef = useRef<ISeriesApi<"Line"> | null>(null);
  const macdSignalRef = useRef<ISeriesApi<"Line"> | null>(null);
  // برای auto-extend هنگام زوم‌اوت
  const candlesRef = useRef<CandlePoint[]>([]);
  const daysRef = useRef(days);
  const loadingRef = useRef(false);
  const autoExtendRef = useRef(false);
  // وقتی بازه‌ی بزرگ‌تر هم رکورد جدیدی برنگرداند، دوباره درخواست نمی‌فرستیم
  const exhaustedRef = useRef(false);
  daysRef.current = days;
  const [hover, setHover] = useState<{
    date: string;
    o: number;
    h: number;
    l: number;
    c: number;
    vol: number;
    chg: number;
  } | null>(null);

  const loadData = (reqDays: number = days) => {
    if (!companyName) return;
    loadingRef.current = true;
    setLoading(true);
    setError(null);
    getPriceHistory(companyName, reqDays)
      .then((rows) => {
        setData(rows.reverse());
      })
      .catch((e) => setError(e?.message || "خطا"))
      .finally(() => {
        loadingRef.current = false;
        setLoading(false);
      });
  };

  const prevCompanyRef = useRef(companyName);
  const prevTickRef = useRef(refreshTick);

  useEffect(() => {
    const companyChanged = prevCompanyRef.current !== companyName;
    const tickChanged = prevTickRef.current !== refreshTick;
    prevCompanyRef.current = companyName;
    prevTickRef.current = refreshTick;

    if (companyChanged) {
      // نماد عوض شد → بازه و وضعیت‌ها به حالت اولیه، بدون درخواست با بازه‌ی قبلی
      exhaustedRef.current = false;
      autoExtendRef.current = false;
      candlesRef.current = [];
      daysRef.current = 180;
      setDays(180);
      if (days === 180) loadData(180);
      return;
    }
    // قیمت تازه رسیده → ممکن است تاریخچه‌ی جدیدی اضافه شده باشد
    if (tickChanged) exhaustedRef.current = false;
    loadData(days);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [companyName, days, refreshTick]);

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
      ...baseChartOptions(dark),
      width: el.clientWidth,
      height: 600,
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.08, bottom: 0.26 },
      },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        barSpacing: 9,
        // تیک‌های محور با تقویم شمسی
        tickMarkFormatter: jalaliTickMark,
        // کفِ فاصله‌ی کندل‌ها = سقف زوم‌اوت. با مقدار بزرگ، کتابخانه زوم‌اوت را
        // زودتر قفل می‌کند؛ عدد کوچک اجازه‌ی زوم‌اوت عمیق (و لود خودکار تاریخچه) می‌دهد.
        minBarSpacing: 0.05,
        // لبه‌ها را قفل نکن تا فضای خالی سمت چپ برای رسیدن به داده‌ی قدیمی‌تر باز بماند
        fixLeftEdge: false,
        fixRightEdge: false,
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

    // سری‌های اندیکاتور — روی همان مقیاس قیمت؛ روشن/خاموش با visible
    const mkOverlay = (color: string, dashed = false) =>
      chart.addLineSeries({
        color,
        lineWidth: dashed ? 1 : 2,
        lineStyle: dashed ? 2 : 0,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
    overlayRef.current = {
      ma20: mkOverlay("#f59e0b"),
      ma50: mkOverlay("#3b82f6"),
      ma200: mkOverlay("#8b5cf6"),
      bbUpper: mkOverlay("#94a3b8", true),
      bbLower: mkOverlay("#94a3b8", true),
    };

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

    // زوم‌اوت خودکار: هر وقت فضای خالی سمت چپ (قبل از قدیمی‌ترین کندل) دیده شد،
    // به‌اندازه‌ی همان فضای خالی رکورد قدیمی‌تر بگیر — بدون سقف، تا وقتی داده تمام شود.
    const onRangeChange = (range: any) => {
      if (!range || loadingRef.current || exhaustedRef.current) return;
      if (range.from >= -1 || candlesRef.current.length === 0) return;
      const cur = daysRef.current;
      if (cur >= ALL_DAYS) return;
      // رکورد لازم = کندل‌های فعلی + فضای خالی سمت چپ (+ حاشیه)
      const needed = candlesRef.current.length - range.from + 8;
      const next = Math.min(Math.max(Math.ceil(needed), cur * 2), ALL_DAYS);
      autoExtendRef.current = true;
      daysRef.current = next;
      setDays(next);
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
      overlayRef.current = {};
    };
    // jalaliMap عمداً خارج از وابستگی‌هاست؛ legend با data جدید re-render می‌شود
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dark, hasData]);

  // ── نمودار RSI — جدا از چارت اصلی، با محور زمان هم‌گام ──
  useEffect(() => {
    if (!ov.rsi) return;
    const el = rsiContainerRef.current;
    const main = chartRef.current;
    if (!el || !main) return;

    const chart = createChart(el, {
      ...baseChartOptions(dark),
      width: el.clientWidth,
      height: 132,
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.12, bottom: 0.08 },
      },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        minBarSpacing: 0.05,
        fixLeftEdge: false,
        fixRightEdge: false,
        visible: true,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: false },
        mouseWheel: false,
        pinch: false,
      },
    });
    const series = chart.addLineSeries({
      color: "#a855f7",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    series.createPriceLine({
      price: 70,
      color: "#ef4444",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "",
    });
    series.createPriceLine({
      price: 30,
      color: "#10b981",
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: true,
      title: "",
    });
    rsiChartRef.current = chart;
    rsiSeriesRef.current = series;

    // هم‌گام‌سازی دوسویه‌ی بازه‌ی دید با گارد ضدحلقه
    let syncing = false;
    const fromMain = (range: any) => {
      if (syncing || !range) return;
      syncing = true;
      try {
        chart.timeScale().setVisibleLogicalRange(range);
      } catch {
        /* چارت اصلی حذف شده است */
      }
      syncing = false;
    };
    const fromRsi = (range: any) => {
      if (syncing || !range) return;
      syncing = true;
      try {
        main.timeScale().setVisibleLogicalRange(range);
      } catch {
        /* چارت حذف شده است */
      }
      syncing = false;
    };
    main.timeScale().subscribeVisibleLogicalRangeChange(fromMain);
    chart.timeScale().subscribeVisibleLogicalRangeChange(fromRsi);
    const initial = main.timeScale().getVisibleLogicalRange();
    if (initial) chart.timeScale().setVisibleLogicalRange(initial);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.applyOptions({ width: Math.round(w) });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      try {
        main.timeScale().unsubscribeVisibleLogicalRangeChange(fromMain);
      } catch {
        /* noop */
      }
      chart.remove();
      rsiChartRef.current = null;
      rsiSeriesRef.current = null;
    };
  }, [ov.rsi, dark, hasData]);

  // داده‌ی RSI با کندل‌ها هم‌گام می‌شود
  useEffect(() => {
    const s = rsiSeriesRef.current;
    if (!s || !ov.rsi) return;
    const closes = candlesRef.current.map((c) => c.close);
    const vals = rsiCalc(closes, 14);
    const pts = vals
      .map((v, i) => (v == null ? null : { time: candlesRef.current[i].time, value: v }))
      .filter((p): p is { time: UTCTimestamp; value: number } => p !== null);
    s.setData(pts);
  }, [candles, ov.rsi]);

  // ── نمودار MACD — جدا از چارت اصلی، با محور زمان هم‌گام ──
  useEffect(() => {
    if (!ov.macd) return;
    const el = macdContainerRef.current;
    const main = chartRef.current;
    if (!el || !main) return;

    const chart = createChart(el, {
      ...baseChartOptions(dark),
      width: el.clientWidth,
      height: 132,
      rightPriceScale: {
        borderVisible: false,
        scaleMargins: { top: 0.15, bottom: 0.05 },
      },
      timeScale: {
        borderVisible: false,
        rightOffset: 4,
        minBarSpacing: 0.05,
        fixLeftEdge: false,
        fixRightEdge: false,
        visible: true,
      },
      handleScale: {
        axisPressedMouseMove: { time: true, price: false },
        mouseWheel: false,
        pinch: false,
      },
    });
    const hist = chart.addHistogramSeries({
      priceLineVisible: false,
      lastValueVisible: false,
      base: 0,
    });
    const line = chart.addLineSeries({
      color: "#ec4899",
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: true,
    });
    const signal = chart.addLineSeries({
      color: "#6366f1",
      lineWidth: 1,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    macdChartRef.current = chart;
    macdHistRef.current = hist;
    macdLineRef.current = line;
    macdSignalRef.current = signal;

    // هم‌گام‌سازی دوسویه‌ی بازه‌ی دید با گارد ضدحلقه
    let syncing = false;
    const fromMain = (range: any) => {
      if (syncing || !range) return;
      syncing = true;
      try {
        chart.timeScale().setVisibleLogicalRange(range);
      } catch {
        /* چارت اصلی حذف شده است */
      }
      syncing = false;
    };
    const fromMacd = (range: any) => {
      if (syncing || !range) return;
      syncing = true;
      try {
        main.timeScale().setVisibleLogicalRange(range);
      } catch {
        /* چارت حذف شده است */
      }
      syncing = false;
    };
    main.timeScale().subscribeVisibleLogicalRangeChange(fromMain);
    chart.timeScale().subscribeVisibleLogicalRangeChange(fromMacd);
    const initial = main.timeScale().getVisibleLogicalRange();
    if (initial) chart.timeScale().setVisibleLogicalRange(initial);

    const ro = new ResizeObserver((entries) => {
      const w = entries[0]?.contentRect.width;
      if (w && w > 0) chart.applyOptions({ width: Math.round(w) });
    });
    ro.observe(el);

    return () => {
      ro.disconnect();
      try {
        main.timeScale().unsubscribeVisibleLogicalRangeChange(fromMain);
      } catch {
        /* noop */
      }
      chart.remove();
      macdChartRef.current = null;
      macdHistRef.current = null;
      macdLineRef.current = null;
      macdSignalRef.current = null;
    };
  }, [ov.macd, dark, hasData]);

  // داده‌ی MACD با کندل‌ها هم‌گام می‌شود
  useEffect(() => {
    const hist = macdHistRef.current;
    const line = macdLineRef.current;
    const signal = macdSignalRef.current;
    if (!hist || !line || !signal || !ov.macd) return;
    const closes = candlesRef.current.map((c) => c.close);
    const m = macdCalc(closes, 12, 26, 9);
    const toPts = (vals: (number | null)[]) =>
      vals
        .map((v, i) => (v == null ? null : { time: candlesRef.current[i].time, value: v }))
        .filter((p): p is { time: UTCTimestamp; value: number } => p !== null);
    line.setData(toPts(m.macd));
    signal.setData(toPts(m.signal));
    hist.setData(
      m.hist
        .map((v, i) => {
          if (v == null) return null;
          return {
            time: candlesRef.current[i].time,
            value: v,
            color: v >= 0 ? "rgba(16,185,129,0.55)" : "rgba(239,68,68,0.55)",
          };
        })
        .filter((p): p is { time: UTCTimestamp; value: number; color: string } => p !== null)
    );
  }, [candles, ov.macd]);

  // ── آپدیت داده‌ها و مقیاس ──
  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !candleRef.current || !volumeRef.current) return;

    const ts = chart.timeScale();
    // اگر با زوم‌اوت خودکار داده‌ی قدیمی‌تر لود شد، جای پنجره‌ی دید کاربر را حفظ کن
    const keepView = autoExtendRef.current && candlesRef.current.length > 0;
    const prevRange = keepView ? ts.getVisibleLogicalRange() : null;
    const prevCount = candlesRef.current.length;
    // درخواست بزرگ‌تر هم کندل جدیدی اضافه نکرد → تاریخچه تمام شده است
    if (keepView && candles.length <= prevCount) exhaustedRef.current = true;

    candlesRef.current = candles;
    chart.priceScale("right").applyOptions({
      mode: logScale ? PriceScaleMode.Logarithmic : PriceScaleMode.Normal,
    });
    candleRef.current.setData(candles as any);
    volumeRef.current.setData(volumes as any);

    // ── اندیکاتورها: محاسبه از قیمت پایانی و اعمال روی سری‌ها ──
    const closes = candles.map((c) => c.close);
    const mkPts = (vals: (number | null)[]) =>
      vals
        .map((v, i) => (v == null ? null : { time: candles[i].time, value: v }))
        .filter((p): p is { time: UTCTimestamp; value: number } => p !== null);
    const applyOverlay = (
      key: string,
      vals: (number | null)[] | undefined,
      visible: boolean,
    ) => {
      const s = overlayRef.current[key];
      if (!s) return;
      s.applyOptions({ visible });
      if (vals && visible) s.setData(mkPts(vals));
    };
    applyOverlay("ma20", sma(closes, 20), ov.ma20);
    applyOverlay("ma50", sma(closes, 50), ov.ma50);
    applyOverlay("ma200", sma(closes, 200), ov.ma200);
    if (ov.bb) {
      const bb = bollinger(closes, 20, 2);
      applyOverlay("bbUpper", bb.upper, true);
      applyOverlay("bbLower", bb.lower, true);
    } else {
      applyOverlay("bbUpper", undefined, false);
      applyOverlay("bbLower", undefined, false);
    }

    ts.fitContent();
    if (keepView && prevRange && candles.length > prevCount) {
      const added = candles.length - prevCount;
      ts.setVisibleLogicalRange({
        from: prevRange.from + added,
        to: prevRange.to + added,
      });
    }
    autoExtendRef.current = false;
  }, [candles, volumes, logScale, ov]);

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
          <WatchStar itemKey={companyName} label={companyName} kind="stock" size={12} />
          <span className="text-[10px] font-medium text-gray-400 bg-gray-100 dark:bg-gray-700/50 px-2 py-0.5 rounded-full">
            کندل + حجم
          </span>
        </div>
        <div className="flex items-center gap-1.5 flex-wrap">
          {/* Indicator toggles */}
          {INDICATORS.map((ind) => (
            <button
              key={ind.key}
              onClick={() => setOv((s) => ({ ...s, [ind.key]: !s[ind.key] }))}
              title={
                ind.key === "rsi"
                  ? "شاخص قدرت نسبی (زیر ۳۰ اشباع فروش، بالای ۷۰ اشباع خرید)"
                  : ind.key === "bb"
                    ? "باندهای بولینگر (میانگین ۲۰ ± ۲ انحراف معیار)"
                    : ind.key === "macd"
                      ? "همگرایی/واگرایی میانگین متحرک (۱۲، ۲۶، ۹)"
                      : `میانگین متحرک ساده‌ی ${ind.key === "ma20" ? "۲۰" : ind.key === "ma50" ? "۵۰" : "۲۰۰"} روزه`
              }
              className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-[11px] font-semibold transition-all duration-200 border ${
                ov[ind.key]
                  ? "border-transparent text-white shadow-sm"
                  : dark
                    ? "border-gray-700/60 bg-gray-700/40 text-gray-400 hover:text-gray-200"
                    : "border-gray-200 bg-gray-100/70 text-gray-500 hover:text-gray-700"
              }`}
              style={ov[ind.key] ? { background: ind.color } : undefined}
            >
              <span
                className="inline-block w-2 h-0.5 rounded"
                style={{ background: ov[ind.key] ? "rgba(255,255,255,0.85)" : ind.color }}
              />
              {ind.label}
            </button>
          ))}
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
          <span className="text-gray-500 dark:text-gray-400" dir="rtl">
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
            <div className="text-[10px] text-gray-500 dark:text-gray-400 font-medium mb-0.5">
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

      {loading && candles.length === 0 ? (
        <div className="h-[600px] flex items-center justify-center">
          <div className="flex items-center gap-3 text-gray-500 dark:text-gray-400">
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
          <p className="text-gray-500 dark:text-gray-400 mb-4">
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
        <>
          <div
            ref={containerRef}
            dir="ltr"
            className={`rounded-xl overflow-hidden ${legendUp ? "" : ""}`}
            style={{ height: 600 }}
          />
          {ov.rsi && (
            <div className="mt-2">
              <div className="flex items-center gap-2 mb-1 px-1 text-[10px] text-gray-500 dark:text-gray-400">
                <span className="inline-block w-2 h-2 rounded-full bg-purple-500" />
                <span className="font-bold">RSI (۱۴)</span>
                <span>— بالای ۷۰ اشباع خرید، زیر ۳۰ اشباع فروش</span>
              </div>
              <div
                ref={rsiContainerRef}
                dir="ltr"
                className="rounded-xl overflow-hidden border-t border-gray-100 dark:border-gray-700/40"
                style={{ height: 132 }}
              />
            </div>
          )}
          {ov.macd && (
            <div className="mt-2">
              <div className="flex items-center gap-2 mb-1 px-1 text-[10px] text-gray-500 dark:text-gray-400">
                <span className="inline-block w-2 h-2 rounded-full bg-pink-500" />
                <span className="font-bold">MACD (12, 26, 9)</span>
                <span>
                  — قطع سیگنال از پایین به بالا = جریان صعودی؛ هیستوگرام = فاصله‌ی مکدی و سیگنال
                </span>
              </div>
              <div
                ref={macdContainerRef}
                dir="ltr"
                className="rounded-xl overflow-hidden border-t border-gray-100 dark:border-gray-700/40"
                style={{ height: 132 }}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
};

export default PriceChart;
