import React from "react";
import { FaArrowUp, FaArrowDown, FaMinus, FaExclamationTriangle } from "react-icons/fa";
import type { AIStockMetric } from "../utils/api";
import { useDarkMode } from "../utils/theme";

type Props = {
  metric: AIStockMetric | undefined;
};

type Factor = {
  label: string;
  value: number | null | undefined;
  display: string;
  weight: number;
  good: boolean | null;
  note?: string;
};

type Category = {
  title: string;
  icon: React.ReactNode;
  color: string;
  maxScore: number;
  actualScore: number | undefined;
  factors: Factor[];
};

const pct = (v: number | null | undefined) =>
  v == null || Number.isNaN(v) ? "--" : `${v.toFixed(1)}%`;

const num = (v: number | null | undefined, d = 2) =>
  v == null || Number.isNaN(v) ? "--" : v.toFixed(d);

const compact = (v: number | null | undefined) => {
  if (v == null || Number.isNaN(v)) return "--";
  const abs = Math.abs(v);
  if (abs >= 1e12) return (v / 1e12).toFixed(1) + "T";
  if (abs >= 1e9) return (v / 1e9).toFixed(1) + "B";
  if (abs >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (abs >= 1e3) return (v / 1e3).toFixed(1) + "K";
  return v.toFixed(0);
};

const ratingColor = (good: boolean | null) => {
  if (good === null) return "text-gray-400";
  return good
    ? "text-green-600 dark:text-green-400"
    : "text-red-600 dark:text-red-400";
};

const barColor = (good: boolean | null) => {
  if (good === null) return "#64748b";
  return good ? "#10b981" : "#ef4444";
};

const FactorRow: React.FC<{ f: Factor; dark: boolean }> = ({ f, dark }) => {
  const pctWidth = f.weight * 100;

  return (
    <div className="flex items-center gap-3 py-1.5">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-600 dark:text-gray-300 truncate">
            {f.label}
          </span>
          <span className="text-[10px] text-gray-400 shrink-0">
            ({(f.weight * 100).toFixed(0)}%)
          </span>
        </div>
        {f.note && (
          <div className="text-[10px] text-gray-400 mt-0.5">{f.note}</div>
        )}
      </div>
      <div className="text-right shrink-0 w-20">
        <span className={`text-xs font-semibold ${ratingColor(f.good)}`}>
          {f.display}
        </span>
      </div>
      {/* نوار وزن */}
      <div
        className={`h-1.5 rounded-full shrink-0 w-16 ${
          dark ? "bg-gray-700" : "bg-gray-200"
        }`}
      >
        <div
          className="h-full rounded-full transition-all"
          style={{
            width: `${pctWidth}%`,
            backgroundColor: barColor(f.good),
          }}
        />
      </div>
    </div>
  );
};

const ScoreBreakdown: React.FC<Props> = ({ metric }) => {
  const { darkMode } = useDarkMode();
  const dark = darkMode;

  if (!metric) {
    return (
      <div
        className={`rounded-2xl border p-4 ${
          dark
            ? "bg-gray-800/60 border-gray-700"
            : "bg-white/70 border-gray-200"
        }`}
      >
        <p className="text-center text-gray-500 dark:text-gray-300 py-6">
          داده‌ی امتیاز برای این نماد موجود نیست
        </p>
      </div>
    );
  }

  const score = metric.quant_score ?? 0;
  const scoreColor =
    score >= 60
      ? "#10b981"
      : score >= 40
        ? "#f59e0b"
        : "#ef4444";

  // ---- دسته‌بندی فاکتورها ----
  const categories: Category[] = [
    {
      title: "رشد",
      icon: <FaArrowUp className="text-emerald-500" />,
      color: "emerald",
      maxScore: 43,
      actualScore: metric.growth_score,
      factors: [
        {
          label: "رشد فروش سالانه",
          value: metric.sales_growth_12m,
          display: pct(metric.sales_growth_12m),
          weight: 0.11,
          good:
            metric.sales_growth_12m == null
              ? null
              : metric.sales_growth_12m > 15,
        },
        {
          label: "رشد فروش ۳‌ماهه",
          value: metric.sales_growth_3m,
          display: pct(metric.sales_growth_3m),
          weight: 0.05,
          good:
            metric.sales_growth_3m == null
              ? null
              : metric.sales_growth_3m > 10,
        },
        {
          label: "رشد درآمد (دقیق)",
          value: metric.revenue_growth_yoy,
          display: pct(metric.revenue_growth_yoy),
          weight: 0.09,
          good:
            metric.revenue_growth_yoy == null
              ? null
              : metric.revenue_growth_yoy > 15,
        },
        {
          label: "رشد سود عملیاتی",
          value: metric.operating_profit_growth_yoy,
          display: pct(metric.operating_profit_growth_yoy),
          weight: 0.11,
          good:
            metric.operating_profit_growth_yoy == null
              ? null
              : metric.operating_profit_growth_yoy > 20,
        },
        {
          label: "رشد سود خالص",
          value: metric.net_profit_growth_4_reports,
          display: pct(metric.net_profit_growth_4_reports),
          weight: 0.07,
          good:
            metric.net_profit_growth_4_reports == null
              ? null
              : metric.net_profit_growth_4_reports > 20,
        },
      ],
    },
    {
      title: "سودآوری",
      icon: <FaArrowDown className="text-blue-500 rotate-180" />,
      color: "blue",
      maxScore: 28,
      actualScore: metric.profitability_score,
      factors: [
        {
          label: "حاشیه عملیاتی",
          value: metric.operating_margin_latest,
          display: pct(metric.operating_margin_latest),
          weight: 0.07,
          good:
            metric.operating_margin_latest == null
              ? null
              : metric.operating_margin_latest > 15,
        },
        {
          label: "حاشیه خالص (۱۲ماه)",
          value: metric.net_profit_margin_12m,
          display: pct(metric.net_profit_margin_12m),
          weight: 0.05,
          good:
            metric.net_profit_margin_12m == null
              ? null
              : metric.net_profit_margin_12m > 10,
        },
        {
          label: "روند حاشیه",
          value: metric.operating_margin_trend,
          display:
            metric.operating_margin_trend == null
              ? "--"
              : `${metric.operating_margin_trend > 0 ? "+" : ""}${metric.operating_margin_trend.toFixed(1)}%`,
          weight: 0.05,
          good:
            metric.operating_margin_trend == null
              ? null
              : metric.operating_margin_trend > 0,
        },
        {
          label: "پوشش بهره",
          value: metric.interest_coverage,
          display: num(metric.interest_coverage, 1),
          weight: 0.05,
          good:
            metric.interest_coverage == null
              ? null
              : metric.interest_coverage > 3,
          note: "بالا = توان پرداخت هزینه‌های مالی",
        },
        {
          label: "کیفیت سود",
          value: metric.non_operating_pct,
          display: pct(metric.non_operating_pct),
          weight: 0.06,
          good:
            metric.non_operating_pct == null
              ? null
              : metric.non_operating_pct < 20,
          note: "پایین = سود از فعالیت اصلی",
        },
      ],
    },
    {
      title: "ارزش‌گذاری",
      icon: <FaMinus className="text-purple-500" />,
      color: "purple",
      maxScore: 13,
      actualScore: metric.valuation_score,
      factors: [
        {
          label: "P/E",
          value: metric.pe_approx,
          display: num(metric.pe_approx, 1),
          weight: 0.09,
          good:
            metric.pe_approx == null
              ? null
              : metric.pe_approx > 0 && metric.pe_approx < 15,
          note: "پایین = ارزان‌تر",
        },
        {
          label: "P/S",
          value: metric.ps_ratio,
          display: num(metric.ps_ratio, 2),
          weight: 0.04,
          good:
            metric.ps_ratio == null
              ? null
              : metric.ps_ratio > 0 && metric.ps_ratio < 3,
        },
      ],
    },
    {
      title: "بازار",
      icon: <FaArrowUp className="text-cyan-500" />,
      color: "cyan",
      maxScore: 16,
      actualScore: metric.market_score,
      factors: [
        {
          label: "نقدشوندگی (۳۰روز)",
          value: metric.avg_trade_value_30d,
          display: compact(metric.avg_trade_value_30d),
          weight: 0.06,
          good:
            metric.avg_trade_value_30d == null
              ? null
              : metric.avg_trade_value_30d > 1e9,
          note: "ارزش میانگین معاملات روزانه",
        },
        {
          label: "ثبات فروش",
          value: metric.sales_stability,
          display: num(metric.sales_stability, 2),
          weight: 0.06,
          good:
            metric.sales_stability == null
              ? null
              : metric.sales_stability > 0.7,
        },
        {
          label: "نوسان (۳۰روز)",
          value: metric.volatility_30d,
          display: pct(metric.volatility_30d),
          weight: 0.02,
          good:
            metric.volatility_30d == null
              ? null
              : metric.volatility_30d < 3,
          note: "پایین = کم‌نوسان‌تر",
        },
        {
          label: "مومنتوم (۳۰روز)",
          value: metric.price_return_30d,
          display: pct(metric.price_return_30d),
          weight: 0.02,
          good:
            metric.price_return_30d == null
              ? null
              : metric.price_return_30d > 0 && metric.price_return_30d < 30,
        },
      ],
    },
  ];

  // ---- جریمه‌ها ----
  // جریمه‌ی پله‌ای کیفیت سود: از ۲۰٪ شروع، خطی تا ۸۰٪، سقف ۸٪
  const highNonOp =
    metric.non_operating_pct != null && metric.non_operating_pct > 20;

  const nonOpPenalty = (() => {
    const v = metric.non_operating_pct;
    if (v == null || v <= 20) return 0;
    if (v >= 80) return 15;
    return Math.round(((v - 20) / 60) * 15 * 100) / 100;
  })();

  const penalties: { label: string; active: boolean; pct: number }[] = [
    { label: "P/E نامعتبر", active: metric.bad_pe_flag, pct: 15 },
    { label: "رشد فروش ضعیف", active: metric.weak_sales_flag, pct: 10 },
    {
      label: "رشد سود عملیاتی ضعیف",
      active: metric.weak_operating_profit_flag,
      pct: 10,
    },
    { label: "شرکت زیان‌ده", active: metric.loss_maker_flag, pct: 15 },
    { label: "پوشش بهره ضعیف", active: metric.weak_coverage_flag, pct: 8 },
    {
      label: "انقباض حاشیه",
      active: metric.margin_contraction_flag,
      pct: 5,
    },
    {
      label: `سهم غیرعملیاتی (${metric.non_operating_pct != null ? metric.non_operating_pct.toFixed(0) + "٪" : "?"})`,
      active: highNonOp,
      pct: nonOpPenalty,
    },
  ];

  const activePenalties = penalties.filter((p) => p.active);
  const totalPenalty = activePenalties.reduce((s, p) => s + p.pct, 0);

  const cardCls = `rounded-2xl border p-4 ${
    dark
      ? "bg-gray-800/60 border-gray-700"
      : "bg-white/70 border-gray-200"
  }`;

  return (
    <div className={cardCls}>
      <h3 className="font-semibold text-gray-800 dark:text-white mb-3">
        تجزیه‌ی امتیاز
      </h3>

      {/* امتیاز کلی */}
      <div className="flex items-center gap-4 mb-4">
        <div className="relative w-24 h-24 shrink-0">
          <svg className="w-full h-full -rotate-90" viewBox="0 0 100 100">
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={dark ? "#374151" : "#e5e7eb"}
              strokeWidth="8"
            />
            <circle
              cx="50"
              cy="50"
              r="42"
              fill="none"
              stroke={scoreColor}
              strokeWidth="8"
              strokeLinecap="round"
              strokeDasharray={`${(score / 100) * 264} 264`}
              className="transition-all duration-700"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span
              className="text-2xl font-bold"
              style={{ color: scoreColor }}
            >
              {score.toFixed(0)}
            </span>
            <span className="text-[10px] text-gray-400">از ۱۰۰</span>
          </div>
        </div>
        <div className="flex-1">
          <div className="text-xs text-gray-500 dark:text-gray-400 mb-1">
            کیفیت داده
          </div>
          <div className="flex items-center gap-2">
            <div
              className={`h-2 rounded-full flex-1 ${
                dark ? "bg-gray-700" : "bg-gray-200"
              }`}
            >
              <div
                className="h-full rounded-full bg-indigo-500 transition-all"
                style={{
                  width: `${(metric.data_quality_score ?? 0) * 100}%`,
                }}
              />
            </div>
            <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
              {((metric.data_quality_score ?? 0) * 100).toFixed(0)}%
            </span>
          </div>
          {totalPenalty > 0 && (
            <div className="mt-2 flex items-center gap-1 text-xs text-red-500">
              <FaExclamationTriangle />
              <span>جریمه: -{totalPenalty}%</span>
            </div>
          )}
        </div>
      </div>

      {/* دسته‌بندی‌ها */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        {categories.map((cat) => {
          const earned = cat.actualScore ?? 0;
          const ratio = cat.maxScore > 0 ? earned / cat.maxScore : 0;
          const scoreColor =
            ratio >= 0.7
              ? "text-green-600 dark:text-green-400"
              : ratio >= 0.4
                ? "text-amber-500"
                : "text-red-600 dark:text-red-400";

          return (
          <div key={cat.title}>
            <div className="flex items-center gap-2 mb-1 pb-1 border-b border-gray-200 dark:border-gray-700">
              {cat.icon}
              <span className="text-xs font-bold text-gray-700 dark:text-gray-200">
                {cat.title}
              </span>
              <span className={`text-xs font-bold mr-auto ${scoreColor}`}>
                {earned.toFixed(1)} / {cat.maxScore}
              </span>
            </div>
            {cat.factors.map((f, i) => (
              <FactorRow key={i} f={f} dark={dark} />
            ))}
          </div>
          );
        })}
      </div>

      {/* جریمه‌های فعال */}
      {activePenalties.length > 0 && (
        <div className="mt-4 pt-3 border-t border-gray-200 dark:border-gray-700">
          <div className="flex items-center gap-2 mb-2">
            <FaExclamationTriangle className="text-red-500 text-sm" />
            <span className="text-xs font-bold text-red-500">
              جریمه‌های فعال ({activePenalties.length})
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {activePenalties.map((p, i) => (
              <span
                key={i}
                className="text-[11px] px-2 py-1 rounded-lg bg-red-100 dark:bg-red-900/30 text-red-600 dark:text-red-400 font-medium"
              >
                {p.label} (-{p.pct}%)
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

export default ScoreBreakdown;
