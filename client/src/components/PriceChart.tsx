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
import { FaChartLine } from "react-icons/fa";
import { getPriceHistory, type PriceHistoryRow } from "../utils/api";
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
  const [rangeIdx, setRangeIdx] = useState(2); // پیش‌فرض: ۶ ماه

  useEffect(() => {
    if (!companyName) return;
    setLoading(true);
    setError(null);
    getPriceHistory(companyName, RANGES[rangeIdx].days)
      .then((rows) => {
        // مرتب‌سازی از قدیم به جدید
        setData(rows.reverse());
      })
      .catch((e) => setError(e?.message || "خطا"))
      .finally(() => setLoading(false));
  }, [companyName, rangeIdx]);

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

  const cardCls = `rounded-2xl border p-4 ${
    dark
      ? "bg-gray-800/60 border-gray-700"
      : "bg-white/70 border-gray-200"
  }`;

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
      <div className="flex items-center justify-between mb-3 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <FaChartLine className="text-indigo-500" />
          <h3 className="font-semibold text-gray-800 dark:text-white">
            نمودار قیمت
          </h3>
        </div>
        <div className="flex gap-1">
          {RANGES.map((r, i) => (
            <button
              key={i}
              onClick={() => setRangeIdx(i)}
              className={`px-2 py-1 rounded-lg text-xs font-medium transition ${
                i === rangeIdx
                  ? "bg-indigo-600 text-white"
                  : dark
                    ? "bg-gray-700 text-gray-300 hover:bg-gray-600"
                    : "bg-gray-100 text-gray-600 hover:bg-gray-200"
              }`}
            >
              {r.label}
            </button>
          ))}
        </div>
      </div>

      {stats && (
        <div className="flex gap-4 mb-3 text-xs flex-wrap">
          <div>
            <span className="text-gray-500 dark:text-gray-400">قیمت: </span>
            <span className="font-bold text-gray-800 dark:text-white">
              {priceFmt(stats.latest)}
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">سقف: </span>
            <span className="font-semibold text-green-600 dark:text-green-400">
              {priceFmt(stats.max)}
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">کف: </span>
            <span className="font-semibold text-red-600 dark:text-red-400">
              {priceFmt(stats.min)}
            </span>
          </div>
          <div>
            <span className="text-gray-500 dark:text-gray-400">بازده: </span>
            <span
              className={`font-bold ${
                stats.totalReturn >= 0
                  ? "text-green-600 dark:text-green-400"
                  : "text-red-600 dark:text-red-400"
              }`}
            >
              {stats.totalReturn >= 0 ? "+" : ""}
              {stats.totalReturn.toFixed(1)}%
            </span>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-center text-gray-500 dark:text-gray-300 py-10">
          در حال بارگذاری نمودار...
        </p>
      ) : error ? (
        <p className="text-center text-red-500 py-10">{error}</p>
      ) : chartData.length === 0 ? (
        <p className="text-center text-gray-500 dark:text-gray-300 py-10">
          داده‌ای برای این نماد موجود نیست
        </p>
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
                  stopOpacity={0.3}
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
              tickFormatter={(v) => fmtShort(Number(v), 0)}
              domain={["dataMin - 5%", "dataMax + 5%"]}
            />
            <Tooltip content={<CustomTooltip />} />
            <Area
              type="monotone"
              dataKey="close"
              stroke={chartPalette.series[0]}
              strokeWidth={2}
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
