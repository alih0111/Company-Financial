import React, { useEffect, useMemo, useState } from "react";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from "recharts";
import { FaChartLine, FaDownload, FaSync } from "react-icons/fa";
import {
  getPriceHistory,
  collectBrsPrices,
  type PriceHistoryRow,
} from "../utils/api";
import { getAuthStatus } from "../hooks/useGetUser";
import { useDarkMode } from "../utils/theme";
import {
  chartPalette,
  glassTooltipStyle,
  fmtShort,
} from "../utils/chart-theme";

type Props = {
  companyName: string;
};

const RANGES = [
  { label: "۱ماه", days: 30 },
  { label: "۳ماه", days: 90 },
  { label: "۶ماه", days: 180 },
  { label: "۱سال", days: 365 },
  { label: "همه", days: 5000 },
];

const PriceChart: React.FC<Props> = ({ companyName }) => {
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

  const loadData = () => {
    if (!companyName) return;
    setLoading(true);
    setError(null);
    getPriceHistory(companyName, RANGES[rangeIdx].days)
      .then((rows) => {
        setData(rows.reverse());
      })
      .catch((e) => setError(e?.message || "خطا"))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    loadData();
  }, [companyName, rangeIdx]);

  const handleFetchPrices = async () => {
    setFetching(true);
    setFetchMsg(null);
    try {
      await collectBrsPrices("backfill", { symbol: companyName, raw: true, limit: 0 });
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

  const chartData = useMemo(() => {
    return data
      .filter((d) => d.closing_price > 0)
      .map((d) => ({
        date: d.jalali_date || d.date,
        close: d.closing_price,
        volume: d.volume,
      }));
  }, [data]);

  const stats = useMemo(() => {
    if (chartData.length === 0) return null;
    const prices = chartData.map((d) => d.close);
    const latest = prices[prices.length - 1];
    const first = prices[0];
    const max = Math.max(...prices);
    const min = Math.min(...prices);
    const totalReturn = first > 0 ? ((latest - first) / first) * 100 : 0;
    return { latest, max, min, totalReturn };
  }, [chartData]);

  const cardCls = `rounded-2xl border p-5 ${
    dark
      ? "bg-gray-800/50 border-gray-700/60"
      : "bg-white/60 border-gray-200/60"
  } backdrop-blur-sm`;

  const priceFmt = (n: number) =>
    n.toLocaleString("en-US", { maximumFractionDigits: 0 });

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null;
    const p = payload[0].payload;
    return (
      <div
        style={{
          ...glassTooltipStyle(dark),
          display: "flex",
          flexDirection: "column",
          gap: 4,
          minWidth: 120,
        }}
      >
        <div style={{ opacity: 0.7, fontSize: 11 }}>{p.date}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: 3,
              background: chartPalette.series[0],
              display: "inline-block",
            }}
          />
          <span style={{ fontWeight: 700 }}>{priceFmt(p.close)}</span>
        </div>
      </div>
    );
  };

  return (
    <div className={cardCls}>
      {/* ── Header ── */}
      <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-indigo-500/10 text-indigo-500">
            <FaChartLine className="text-sm" />
          </span>
          <h3 className="font-bold text-gray-800 dark:text-white text-sm">
            نمودار قیمت
          </h3>
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
                    ? "bg-indigo-600 text-white shadow-sm shadow-indigo-500/25"
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

      {/* ── Stats Cards ── */}
      {stats && (
        <div className="grid grid-cols-4 gap-2 mb-4">
          <div className="rounded-xl bg-gray-50 dark:bg-gray-800/40 p-2.5 text-center border border-gray-100 dark:border-gray-700/40">
            <div className="text-[10px] text-gray-400 dark:text-gray-500 font-medium mb-0.5">قیمت</div>
            <div className="text-sm font-bold text-gray-800 dark:text-white tabular-nums">
              {priceFmt(stats.latest)}
            </div>
          </div>
          <div className="rounded-xl bg-emerald-50 dark:bg-emerald-900/15 p-2.5 text-center border border-emerald-100 dark:border-emerald-900/30">
            <div className="text-[10px] text-emerald-600 dark:text-emerald-400/70 font-medium mb-0.5">سقف</div>
            <div className="text-sm font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">
              {priceFmt(stats.max)}
            </div>
          </div>
          <div className="rounded-xl bg-red-50 dark:bg-red-900/15 p-2.5 text-center border border-red-100 dark:border-red-900/30">
            <div className="text-[10px] text-red-500 dark:text-red-400/70 font-medium mb-0.5">کف</div>
            <div className="text-sm font-bold text-red-500 dark:text-red-400 tabular-nums">
              {priceFmt(stats.min)}
            </div>
          </div>
          <div className={`rounded-xl p-2.5 text-center border ${
            stats.totalReturn >= 0
              ? "bg-emerald-50 dark:bg-emerald-900/15 border-emerald-100 dark:border-emerald-900/30"
              : "bg-red-50 dark:bg-red-900/15 border-red-100 dark:border-red-900/30"
          }`}>
            <div className={`text-[10px] font-medium mb-0.5 ${
              stats.totalReturn >= 0
                ? "text-emerald-600 dark:text-emerald-400/70"
                : "text-red-500 dark:text-red-400/70"
            }`}>بازده</div>
            <div className={`text-sm font-bold tabular-nums ${
              stats.totalReturn >= 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-500 dark:text-red-400"
            }`}>
              {stats.totalReturn >= 0 ? "+" : ""}
              {stats.totalReturn.toFixed(1)}%
            </div>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-center text-gray-400 dark:text-gray-500 py-10">
          در حال بارگذاری نمودار...
        </p>
      ) : error ? (
        <p className="text-center text-red-500 py-10">{error}</p>
      ) : chartData.length === 0 ? (
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
                  : "bg-gradient-to-r from-indigo-500 to-purple-600 hover:from-indigo-600 hover:to-purple-700 hover:shadow-xl hover:shadow-indigo-500/20"
              }`}
            >
              {fetching ? (
                <>
                  <FaSync className="animate-spin" />
                  در حال جمع‌آوری...
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
            <p className="mt-3 text-xs text-gray-500 dark:text-gray-400">{fetchMsg}</p>
          )}
        </div>
      ) : (
        <ResponsiveContainer width="100%" height={320}>
          <AreaChart
            data={chartData}
            margin={{ top: 10, right: 16, bottom: 8, left: 8 }}
          >
            <defs>
              <linearGradient id="priceGrad" x1="0" y1="0" x2="0" y2="1">
                <stop
                  offset="0%"
                  stopColor={chartPalette.series[0]}
                  stopOpacity={0.25}
                />
                <stop
                  offset="100%"
                  stopColor={chartPalette.series[0]}
                  stopOpacity={0}
                />
              </linearGradient>
            </defs>
            <CartesianGrid
              strokeDasharray="3 6"
              stroke={chartPalette.gridStroke(dark)}
              vertical={false}
            />
            <XAxis
              dataKey="date"
              tick={{ fill: chartPalette.axisTick(dark), fontSize: 10 }}
              tickLine={{ stroke: chartPalette.axisStroke(dark) }}
              axisLine={{ stroke: chartPalette.axisStroke(dark) }}
              minTickGap={40}
              dy={6}
            />
            <YAxis
              tick={{ fill: chartPalette.axisTick(dark), fontSize: 10 }}
              tickLine={false}
              axisLine={false}
              width={56}
              scale={logScale ? "log" : "linear"}
              domain={
                logScale
                  ? [
                      (dataMin: number) => Math.max(dataMin * 0.9, 1),
                      (dataMax: number) => dataMax * 1.1,
                    ]
                  : ["dataMin - 5%", "dataMax + 5%"]
              }
              allowDataOverflow
              tickFormatter={(v) => fmtShort(Number(v), 0)}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="close"
              stroke={chartPalette.series[0]}
              strokeWidth={2.5}
              fill="url(#priceGrad)"
              isAnimationActive
              animationDuration={600}
            />
          </AreaChart>
        </ResponsiveContainer>
      )}
    </div>
  );
};

export default PriceChart;
