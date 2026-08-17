import React from "react";
import {
  FaArrowUp,
  FaArrowDown,
  FaMinus,
  FaExclamationTriangle,
  FaInfoCircle,
} from "react-icons/fa";
import type { AIStockMetric } from "../utils/api";
import { useDarkMode } from "../utils/theme";

type Props = {
  metric: AIStockMetric | undefined;
};

type Factor = {
  label: string;
  hint: string;
  value: number | null | undefined;
  display: string;
  weight: number; // حداکثر امتیاز فاکتور (بر حسب امتیاز، نه درصد)
  rank: number | null | undefined; // رتبه‌ی درصدی بین کل بازار (۰ تا ۱)
  good: boolean | null;
  // داده‌ی فاکتور موجود نیست → موتور رتبه‌ی خنثی (۰.۳ یا ۰.۵) داده
  neutralWhenNull?: boolean;
  // مقدار نامعتبر است (مثل P/E منفی) → بدترین رتبه
  invalid?: boolean;
  note?: string;
};

type Category = {
  title: string;
  icon: React.ReactNode;
  maxScore: number;
  actualScore: number | undefined;
  penalty: number | undefined;
  penaltyReasons: string[];
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

// رنگ رتبه‌ی درصدی: بالا = سبز، متوسط = کهربایی، پایین = قرمز
const rankColor = (rank: number) => {
  if (rank >= 0.7) return "#10b981";
  if (rank >= 0.4) return "#f59e0b";
  return "#ef4444";
};

const FactorRow: React.FC<{ f: Factor; dark: boolean }> = ({ f, dark }) => {
  const hasData = f.value != null && !Number.isNaN(f.value);
  const rank = f.rank ?? null;
  const earned = rank != null ? f.weight * rank : null;

  return (
    <div className="py-1.5 border-b border-gray-100 dark:border-gray-800 last:border-0">
      {/* ردیف اول: نام فاکتور + وزن + مقدار خام */}
      <div className="flex items-center gap-2">
        <span
          className="text-xs text-gray-600 dark:text-gray-300 truncate cursor-help"
          title={f.hint}
        >
          {f.label}
        </span>
        <span className="text-[10px] text-gray-400 shrink-0">
          ({f.weight} امتیاز)
        </span>
        <span
          className={`mr-auto text-xs font-semibold shrink-0 ${ratingColor(f.good)}`}
        >
          {f.display}
        </span>
      </div>

      {/* ردیف دوم: رتبه‌ی بازار + امتیاز کسب‌شده */}
      <div className="flex items-center gap-2 mt-1">
        <div
          className={`h-1.5 rounded-full flex-1 ${
            dark ? "bg-gray-700" : "bg-gray-200"
          }`}
          title="رتبه‌ی درصدی این شرکت در این فاکتور نسبت به کل بازار"
        >
          {rank != null && (
            <div
              className="h-full rounded-full transition-all"
              style={{
                width: `${Math.min(100, rank * 100)}%`,
                backgroundColor:
                  f.invalid || (!hasData && f.neutralWhenNull)
                    ? dark
                      ? "#4b5563"
                      : "#9ca3af"
                    : rankColor(rank),
              }}
            />
          )}
        </div>

        {f.invalid ? (
          <span className="text-[10px] text-red-500 font-medium shrink-0 w-24 text-left">
            نامعتبر → رتبه ۰
          </span>
        ) : !hasData && f.neutralWhenNull ? (
          <span className="text-[10px] text-gray-400 shrink-0 w-24 text-left">
            بدون داده → خنثی {(rank != null ? rank * 100 : 0).toFixed(0)}٪
          </span>
        ) : (
          <span className="text-[10px] text-gray-500 dark:text-gray-400 shrink-0 w-24 text-left">
            رتبه {rank != null ? (rank * 100).toFixed(0) : "؟"}٪
          </span>
        )}

        <span className="text-[11px] font-bold text-gray-700 dark:text-gray-200 shrink-0 w-16 text-left tabular-nums">
          {earned != null ? `${earned.toFixed(1)}/${f.weight}` : "--"}
        </span>
      </div>

      {f.note && (
        <div className="text-[10px] text-gray-400 mt-0.5">{f.note}</div>
      )}
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
    score >= 60 ? "#10b981" : score >= 40 ? "#f59e0b" : "#ef4444";

  const peInvalid =
    metric.pe_approx == null || metric.pe_approx <= 0 || metric.pe_approx > 60;
  const psInvalid =
    metric.ps_ratio == null || metric.ps_ratio <= 0;

  // ---- دسته‌بندی فاکتورها (وزن‌ها = امتیاز، مطابق موتور v3) ----
  const categories: Category[] = [
    {
      title: "رشد",
      icon: <FaArrowUp className="text-emerald-500" />,
      maxScore: 36,
      actualScore: metric.growth_score,
      penalty: metric.growth_penalty,
      penaltyReasons: [
        ...(metric.weak_sales_flag
          ? ["رشد فروش سالانه < −۲۰٪ (−۶)"]
          : []),
        ...(metric.weak_operating_profit_flag
          ? ["رشد سود عملیاتی < −۲۵٪ (−۵)"]
          : []),
      ],
      factors: [
        {
          label: "رشد فروش سالانه",
          hint: "مقایسه‌ی مجموع فروش ۱۲ ماه اخیر با ۱۲ ماه قبل از آن (از گزارش‌های ماهانه)",
          value: metric.sales_growth_12m,
          display: pct(metric.sales_growth_12m),
          weight: 9,
          rank: metric.sales_growth_rank,
          good:
            metric.sales_growth_12m == null
              ? null
              : metric.sales_growth_12m > 15,
          neutralWhenNull: true,
        },
        {
          label: "رشد فروش ۳‌ماهه",
          hint: "مقایسه‌ی فروش ۳ ماه اخیر با ۳ ماه قبل از آن (کراپ در ±۱۵۰٪)",
          value: metric.sales_growth_3m,
          display: pct(metric.sales_growth_3m),
          weight: 4,
          rank: metric.sales_growth_3m_rank,
          good:
            metric.sales_growth_3m == null ? null : metric.sales_growth_3m > 10,
          neutralWhenNull: true,
        },
        {
          label: "رشد درآمد (دقیق)",
          hint: "رشد درآمد دوره‌ی مشابه سال قبل، مستقیماً از صورت سود و زیان (هم‌منبع)؛ فقط برای شرکت‌های دارای ستون درآمد",
          value: metric.revenue_growth_yoy,
          display: pct(metric.revenue_growth_yoy),
          weight: 5,
          rank: metric.revenue_growth_rank,
          good:
            metric.revenue_growth_yoy == null
              ? null
              : metric.revenue_growth_yoy > 15,
          neutralWhenNull: true,
        },
        {
          label: "رشد سود عملیاتی (TTM)",
          hint: "رشد سود عملیاتی ۱۲ماهه (ساخته‌شده از گزارش‌های تجمعی) نسبت به ۱۲ ماه قبل",
          value: metric.operating_profit_growth_yoy,
          display: pct(metric.operating_profit_growth_yoy),
          weight: 8,
          rank: metric.operating_profit_growth_rank,
          good:
            metric.operating_profit_growth_yoy == null
              ? null
              : metric.operating_profit_growth_yoy > 20,
          neutralWhenNull: true,
        },
        {
          label: "رشد سود خالص (TTM)",
          hint: "مهم‌ترین فاکتور رشد: سود خالص ۱۲ماهه (ترکیک گزارش + سال قبل − دوره‌ی مشابه سال قبل) در برابر ۱۲ ماه قبل از آن",
          value: metric.net_profit_growth_4_reports,
          display: pct(metric.net_profit_growth_4_reports),
          weight: 10,
          rank: metric.net_profit_growth_rank,
          good:
            metric.net_profit_growth_4_reports == null
              ? null
              : metric.net_profit_growth_4_reports > 20,
          neutralWhenNull: true,
        },
      ],
    },
    {
      title: "سودآوری",
      icon: <FaArrowDown className="text-blue-500 rotate-180" />,
      maxScore: 26,
      actualScore: metric.profitability_score,
      penalty: metric.profitability_penalty,
      penaltyReasons: [
        ...(metric.loss_maker_flag ? ["سود خالص ۱۲ماهه منفی (−۱۰)"] : []),
        ...(metric.weak_coverage_flag
          ? ["پوشش بهره < ۱٫۵ (−۴)"]
          : []),
        ...(metric.margin_contraction_flag
          ? ["انقباض حاشیه > ۲ واحد (−۳)"]
          : []),
        ...(metric.non_operating_pct != null && metric.non_operating_pct > 20
          ? [
              `سهم غیرعملیاتی ${metric.non_operating_pct.toFixed(0)}٪ (تا −۸)`,
            ]
          : []),
      ],
      factors: [
        {
          label: "حاشیه عملیاتی (۱۲ماه)",
          hint: "سود عملیاتی ۱۲ماهه تقسیم بر فروش/درآمد ۱۲ماهه — بهره‌وری فعالیت اصلی",
          value: metric.operating_margin_12m,
          display: pct(metric.operating_margin_12m),
          weight: 4,
          rank: metric.operating_margin_rank,
          good:
            metric.operating_margin_12m == null
              ? null
              : metric.operating_margin_12m > 15,
          neutralWhenNull: true,
        },
        {
          label: "حاشیه خالص (۱۲ماه)",
          hint: "سود خالص ۱۲ماهه تقسیم بر فروش/درآمد ۱۲ماهه",
          value: metric.net_profit_margin_12m,
          display: pct(metric.net_profit_margin_12m),
          weight: 3,
          rank: metric.net_margin_rank,
          good:
            metric.net_profit_margin_12m == null
              ? null
              : metric.net_profit_margin_12m > 10,
          neutralWhenNull: true,
        },
        {
          label: "بازده حقوق مالکانه (ROE)",
          hint: "سود خالص ۱۲ماهه تقسیم بر حقوق مالکانه — مهم‌ترین سنجه‌ی سودآوری برای مقایسه‌ی شرکت‌ها؛ از ترازنامه‌ی CODAL",
          value: metric.roe,
          display: pct(metric.roe),
          weight: 5,
          rank: metric.roe_rank,
          good: metric.roe == null ? null : metric.roe > 20,
          neutralWhenNull: true,
        },

        {
          label: "روند حاشیه",
          hint: "اختلاف حاشیه‌ی عملیاتی امسال با سال قبل (بر حسب واحد درصد) — مثبت یعنی بهبود بهره‌وری",
          value: metric.operating_margin_trend,
          display:
            metric.operating_margin_trend == null
              ? "--"
              : `${metric.operating_margin_trend > 0 ? "+" : ""}${metric.operating_margin_trend.toFixed(1)}%`,
          weight: 3,
          rank: metric.margin_trend_rank,
          good:
            metric.operating_margin_trend == null
              ? null
              : metric.operating_margin_trend > 0,
          neutralWhenNull: true,
        },
        {
          label: "پوشش بهره",
          hint: "سود عملیاتی ÷ هزینه‌های مالی — بالای ۳ امن، زیر ۱٫۵ پرخطر؛ بالاتر از ۲۰× سقف می‌خورد",
          value: metric.interest_coverage,
          display: num(metric.interest_coverage, 1),
          weight: 3,
          rank: metric.interest_coverage_rank,
          good:
            metric.interest_coverage == null
              ? null
              : metric.interest_coverage > 3,
          neutralWhenNull: true,
        },
        {
          label: "کیفیت نقدی سود",
          hint: "جریان نقدی عملیاتی ۱۲ماهه تقسیم بر سود خالص ۱۲ماهه — نزدیک ۱ یا بالاتر یعنی سود پشتوانه‌ی نقدی دارد؛ از صورت جریان نقدی CODAL",
          value: metric.cash_conversion,
          display:
            metric.cash_conversion == null
              ? "--"
              : `${metric.cash_conversion.toFixed(2)}×`,
          weight: 4,
          rank: metric.cash_conversion_rank,
          good:
            metric.cash_conversion == null
              ? null
              : metric.cash_conversion > 0.8,
          neutralWhenNull: true,
        },

        {
          label: "کیفیت سود",
          hint: "سهم درآمد غیرعملیاتی از سود عملیاتی — پایین (زیر ۲۰٪) یعنی سود از فعالیت اصلی و پایدار",
          value: metric.non_operating_pct,
          display: pct(metric.non_operating_pct),
          weight: 4,
          rank: metric.earnings_quality_rank,
          good:
            metric.non_operating_pct == null
              ? null
              : metric.non_operating_pct < 20,
          neutralWhenNull: true,
        },
      ],
    },
    {
      title: "ارزش‌گذاری",
      icon: <FaMinus className="text-purple-500" />,
      maxScore: 16,
      actualScore: metric.valuation_score,
      penalty: metric.valuation_penalty,
      penaltyReasons: peInvalid ? ["P/E نامعتبر یا خارج از بازه (−۸)"] : [],
      factors: [
        {
          label: "P/E (TTM)",
          hint: "قیمت ÷ سود هر سهم ۱۲ماهه — فقط بین ۰ تا ۶۰ معتبر است؛ خارج از آن بدترین رتبه + جریمه",
          value: metric.pe_approx,
          display: num(metric.pe_approx, 1),
          weight: 10,
          rank: metric.pe_rank,
          good:
            metric.pe_approx == null
              ? null
              : metric.pe_approx > 0 && metric.pe_approx < 15,
          invalid: peInvalid,
          note: peInvalid ? "نامعتبر → جریمه‌ی ارزش‌گذاری" : "پایین = ارزان‌تر",
        },
        {
          label: "P/S",
          hint: "هم‌ارز P/E × حاشیه‌ی خالص — قیمت ÷ فروش هر سهم؛ فقط وقتی محاسبه می‌شود که P/E و حاشیه معتبر باشند",
          value: metric.ps_ratio,
          display: num(metric.ps_ratio, 2),
          weight: 3,
          rank: metric.ps_rank,
          good:
            metric.ps_ratio == null
              ? null
              : metric.ps_ratio > 0 && metric.ps_ratio < 3,
          invalid: psInvalid,
        },
        {
          label: "P/B",
          hint: "قیمت به ارزش دفتری — هم‌ارز P/E × ROE؛ پایین‌تر = ارزان‌تر نسبت به ارزش دفتری",
          value: metric.pb_ratio,
          display: num(metric.pb_ratio, 2),
          weight: 3,
          rank: metric.pb_rank,
          good:
            metric.pb_ratio == null
              ? null
              : metric.pb_ratio > 0 && metric.pb_ratio < 2,
          invalid: metric.pb_ratio == null || metric.pb_ratio <= 0,
        },

      ],
    },
    {
      title: "بازار و ریسک",
      icon: <FaArrowUp className="text-cyan-500" />,
      maxScore: 22,
      actualScore: metric.market_score,
      penalty: metric.market_penalty,
      penaltyReasons: [
        ...(metric.market_data_age_days > 14
          ? [`داده‌ی قیمت ${metric.market_data_age_days} روز قدیم (−۴)`]
          : []),
        ...(metric.profit_report_age_months > 8
          ? [`گزارش سود ${metric.profit_report_age_months} ماه قدیم (−۳)`]
          : []),
      ],
      factors: [
        {
          label: "نقدشوندگی (۳۰روز)",
          hint: "میانگین ارزش معاملات روزانه در ۳۰ روز اخیر — بدون داده‌ی معاملات، بدترین رتبه",
          value: metric.avg_trade_value_30d,
          display: compact(metric.avg_trade_value_30d),
          weight: 6,
          rank: metric.liquidity_rank,
          good:
            metric.avg_trade_value_30d == null
              ? null
              : metric.avg_trade_value_30d > 1e9,
        },
        {
          label: "ثبات فروش",
          hint: "۱ منهای ضریب تغییرات فروش ماهانه‌ی ۱۲ ماه اخیر — نزدیک ۱ یعنی فروش یکنواخت",
          value: metric.sales_stability,
          display: num(metric.sales_stability, 2),
          weight: 3,
          rank: metric.stability_rank,
          good:
            metric.sales_stability == null
              ? null
              : metric.sales_stability > 0.7,
          neutralWhenNull: true,
        },
        {
          label: "اهرم مالی",
          hint: "جمع بدهی‌ها تقسیم بر حقوق مالکانه — کمتر = ریسک مالی پایین‌تر؛ از ترازنامه‌ی CODAL",
          value: metric.financial_leverage,
          display: num(metric.financial_leverage, 2),
          weight: 4,
          rank: metric.leverage_rank,
          good:
            metric.financial_leverage == null
              ? null
              : metric.financial_leverage < 1.5,
          neutralWhenNull: true,
        },
        {
          label: "نسبت جاری",
          hint: "دارایی‌های جاری تقسیم بر بدهی‌های جاری — بالای ۱٫۲ یعنی توان پرداخت تعهدات کوتاه‌مدت",
          value: metric.current_ratio,
          display: num(metric.current_ratio, 2),
          weight: 3,
          rank: metric.current_ratio_rank,
          good:
            metric.current_ratio == null
              ? null
              : metric.current_ratio > 1.2,
          neutralWhenNull: true,
        },

        {
          label: "نوسان (۳۰روز)",
          hint: "انحراف معیار بازده‌ی روزانه در ۳۰ روز اخیر — پایین‌تر = کم‌ریسک‌تر",
          value: metric.volatility_30d,
          display: pct(metric.volatility_30d),
          weight: 3,
          rank: metric.low_volatility_rank,
          good:
            metric.volatility_30d == null ? null : metric.volatility_30d < 3,
          neutralWhenNull: true,
        },
        {
          label: "مومنتوم (۳۰روز)",
          hint: "بازده‌ی قیمت ۳۰ روز اخیر با سقف +۴۰٪ و کف −۵۰٪ (رشد انفجاری دیگر جریمه نمی‌شود)",
          value: metric.price_return_30d,
          display: pct(metric.price_return_30d),
          weight: 3,
          rank: metric.momentum_rank,
          good:
            metric.price_return_30d == null
              ? null
              : metric.price_return_30d > 0 && metric.price_return_30d < 30,
          neutralWhenNull: true,
        },
      ],
    },
  ];

  // ---- فرمول کلی با اعداد واقعی ----
  const dq = metric.data_quality_score ?? 0;
  const rawTotal =
    (metric.growth_score ?? 0) +
    (metric.profitability_score ?? 0) +
    (metric.valuation_score ?? 0) +
    (metric.market_score ?? 0);
  const totalPenalty = categories.reduce((s, c) => s + (c.penalty ?? 0), 0);

  const cardCls = `rounded-2xl border p-4 ${
    dark ? "bg-gray-800/60 border-gray-700" : "bg-white/70 border-gray-200"
  }`;

  return (
    <div className={cardCls}>
      <h3 className="font-semibold text-gray-800 dark:text-white mb-1 flex items-center gap-2">
        تجزیه‌ی امتیاز
        {metric.score_version && (
          <span className="text-[10px] font-normal text-gray-400">
            موتور {metric.score_version}
          </span>
        )}
      </h3>

      {/* راهنمای روش محاسبه (باز/بسته شونده) */}
      <details className="mb-3 group">
        <summary className="flex items-center gap-1.5 text-[11px] text-indigo-500 cursor-pointer select-none">
          <FaInfoCircle className="text-[10px]" />
          این امتیاز چطور محاسبه می‌شود؟
        </summary>
        <div className="mt-2 p-3 rounded-xl bg-gray-50 dark:bg-gray-900/60 text-[11px] leading-6 text-gray-600 dark:text-gray-300 space-y-1">
          <p>
            ۱. هر فاکتورِ مالی (رشد، حاشیه، P/E و…) ابتدا برای همه‌ی شرکت‌های
            بازار محاسبه می‌شود؛ سپس <b>رتبه‌ی درصدی</b> شرکت در آن فاکتور
            مشخص می‌شود (مثلاً ۸۵٪ یعنی بهتر از ۸۵٪ شرکت‌ها).
          </p>
          <p>
            ۲. امتیاز هر فاکتور = <b>وزن × رتبه</b>. مثلاً رشد سود خالص با وزن
            ۱۲ و رتبه‌ی ۸۵٪ معادل ۱۰٫۲ امتیاز است.
          </p>
          <p>
            ۳. اگر داده‌ی یک فاکتور موجود نباشد (مثل فروش ماهانه برای
            بانک‌ها) رتبه‌ی <b>خنثی ۳۰٪</b> داده می‌شود؛ اگر مقدار
            <b> نامعتبر</b> باشد (مثل P/E منفی) بدترین رتبه + جریمه دارد.
          </p>
          <p>
            ۴. امتیاز هر دسته = مجموع امتیاز فاکتورها <b>− جریمه‌های همان
            دسته</b> (زیان‌دهی، P/E نامعتبر، داده‌ی کهنه و…).
          </p>
          <p>
            ۵. امتیاز نهایی = <b>کیفیت داده × مجموع چهار دسته</b>. کیفیت داده
            خودش از کفایت تاریخچه (فروش/سود/قیمت) و <b>تازگی داده</b> ساخته
            می‌شود.
          </p>
        </div>
      </details>

      {/* امتیاز کلی + فرمول */}
      <div className="flex items-center gap-4 mb-3">
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
            <span className="text-2xl font-bold" style={{ color: scoreColor }}>
              {score.toFixed(0)}
            </span>
            <span className="text-[10px] text-gray-400">از ۱۰۰</span>
          </div>
        </div>

        <div className="flex-1 min-w-0">
          {/* فرمول با اعداد واقعی */}
          <div className="flex flex-wrap items-center gap-x-1 gap-y-1 text-[11px] text-gray-600 dark:text-gray-300 tabular-nums">
            <span>(</span>
            <span className="px-1.5 py-0.5 rounded bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 font-semibold">
              رشد {(metric.growth_score ?? 0).toFixed(1)}
            </span>
            <span>+</span>
            <span className="px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 font-semibold">
              سودآوری {(metric.profitability_score ?? 0).toFixed(1)}
            </span>
            <span>+</span>
            <span className="px-1.5 py-0.5 rounded bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 font-semibold">
              ارزش {(metric.valuation_score ?? 0).toFixed(1)}
            </span>
            <span>+</span>
            <span className="px-1.5 py-0.5 rounded bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300 font-semibold">
              بازار {(metric.market_score ?? 0).toFixed(1)}
            </span>
            <span>)</span>
            {totalPenalty > 0 && (
              <span className="text-red-500 font-semibold">
                (شامل −{totalPenalty.toFixed(1)} جریمه)
              </span>
            )}
            <span>× کیفیت داده {dq.toFixed(2)}</span>
            <span className="font-bold text-gray-800 dark:text-white">
              = {score.toFixed(1)}
            </span>
          </div>

          {/* کیفیت داده */}
          <div className="mt-2">
            <div className="flex items-center gap-2">
              <div
                className={`h-2 rounded-full flex-1 ${
                  dark ? "bg-gray-700" : "bg-gray-200"
                }`}
                title="کیفیت داده از کفایت تاریخچه‌ی فروش/سود/قیمت و تازگی گزارش‌ها ساخته می‌شود"
              >
                <div
                  className="h-full rounded-full bg-indigo-500 transition-all"
                  style={{ width: `${dq * 100}%` }}
                />
              </div>
              <span className="text-xs font-semibold text-gray-600 dark:text-gray-300">
                {(dq * 100).toFixed(0)}%
              </span>
            </div>
            <div className="mt-1 text-[10px] text-gray-400 flex flex-wrap gap-x-3">
              <span>مجموع خام دسته‌ها: {rawTotal.toFixed(1)}</span>
              {metric.profit_report_age_months > 0 && (
                <span>گزارش سود: {metric.profit_report_age_months} ماه پیش</span>
              )}
              {metric.market_data_age_days > 0 && (
                <span>آخرین قیمت: {metric.market_data_age_days} روز پیش</span>
              )}
              {metric.stale_data_flag && (
                <span className="text-amber-500 font-medium">داده کهنه</span>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* دسته‌بندی‌ها */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-x-6 gap-y-3">
        {categories.map((cat) => {
          const earned = cat.actualScore ?? 0;
          const ratio = cat.maxScore > 0 ? earned / cat.maxScore : 0;
          const catScoreColor =
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
                {(cat.penalty ?? 0) > 0 && (
                  <span className="text-[10px] text-red-500 font-medium">
                    −{(cat.penalty ?? 0).toFixed(1)} جریمه
                  </span>
                )}
                <span
                  className={`text-xs font-bold mr-auto ${catScoreColor}`}
                  title={
                    (cat.penalty ?? 0) > 0
                      ? `خام ${(earned + (cat.penalty ?? 0)).toFixed(1)} − جریمه ${(cat.penalty ?? 0).toFixed(1)} = ${earned.toFixed(1)}`
                      : undefined
                  }
                >
                  {earned.toFixed(1)} / {cat.maxScore}
                </span>
              </div>

              {cat.factors.map((f, i) => (
                <FactorRow key={i} f={f} dark={dark} />
              ))}

              {(cat.penalty ?? 0) > 0 && cat.penaltyReasons.length > 0 && (
                <div className="mt-1.5 flex flex-col gap-1">
                  {cat.penaltyReasons.map((r, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-1.5 text-[10px] text-red-500"
                    >
                      <FaExclamationTriangle className="text-[9px]" />
                      <span>{r}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* راهنمای ستون‌ها */}
      <div className="mt-3 pt-2 border-t border-gray-200 dark:border-gray-700 flex flex-wrap gap-x-4 gap-y-1 text-[10px] text-gray-400">
        <span>مقدار خام در راست هر فاکتور</span>
        <span>نوار = رتبه‌ی درصدی در بازار</span>
        <span>عدد انتهایی = امتیاز کسب‌شده از حداکثر وزن</span>
        <span>برای توضیح هر فاکتور، نشانگر را روی نامش نگه دارید</span>
      </div>
    </div>
  );
};

export default ScoreBreakdown;
