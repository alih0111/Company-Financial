import { useEffect, useMemo, useState } from "react";
import {
  fetchQvtV2Detail,
  fetchQvtV2Summary,
  type QvtAxisView,
  type QvtCompanyRow,
  type QvtV2Summary,
} from "../utils/api";

// ─────────────────────────────────────────────────────────────────────────────
// صفحه‌ی «تحلیل QVT — آزمایشی»
//
// فقط نمایش خروجی واقعی پایلوت V2 (سه آرتیفکت Q و V و T) از endpoint
// فقط‌خواندنی ‎/api/qvt-v2. هیچ داده نمونه یا امتیاز فرضی وجود ندارد؛ اگر
// آرتیفکت موجود نباشد یا اسنپ‌شات‌ها هم‌خوان نباشند، پیام خطای سرور نمایش
// داده می‌شود.
//
// مرزهای قرارداد که این صفحه عمداً نمی‌شکند:
//   * هیچ امتیاز کل از ۱۰۰ و هیچ جمع Q+V+T ساخته نمی‌شود
//   * امتیاز ناقص به ۴۰/۳۵/۲۵ کامل تبدیل نمی‌شود — همیشه «X از max»
//     همراه با پوشش واقعی نمایش داده می‌شود
//   * ترتیب پیش‌فرض بر اساس نماد است، نه امتیاز؛ مرتب‌سازی بر اساس امتیاز
//     به‌عنوان رتبه نهایی سرمایه‌گذاری وجود ندارد
//   * Data Confidence و Risk Gate «ارزیابی نشده» نمایش داده می‌شوند
// ─────────────────────────────────────────────────────────────────────────────

const FALLBACK_DISCLAIMER =
  "نسخه آزمایشی — اعتبار تاریخی اطلاعات مالی و قیمت‌ها به‌طور کامل تأیید نشده است. نتایج توصیه خرید و فروش نیستند.";

// برچسب فارسی فاکتورها — فقط شناسه‌های واقعی کانفیگ؛ شناسه ناشناخته به‌صورت
// خودِ شناسه نمایش داده می‌شود (چیزی اختراع نمی‌شود).
const FACTOR_LABELS: Record<string, string> = {
  // Q (quality)
  margins: "حاشیه سود",
  roe_level: "سطح ROE",
  roe_stability: "پایداری ROE",
  margin_trend: "روند حاشیه سود",
  earnings_quality: "کیفیت سود",
  cash_conversion: "تبدیل نقدینه",
  interest_coverage: "پوشش بهره",
  leverage: "اهرم",
  revenue_growth: "رشد فروش",
  earnings_growth: "رشد سود",
  // V (valuation)
  pe: "نسبت P/E",
  pb: "نسبت P/B",
  ps: "نسبت P/S",
  // T (timing)
  momentum_6m_rel: "مومنتوم ۶ ماهه نسبی به بازار",
  momentum_3m_rel: "مومنتوم ۳ ماهه نسبی به بازار",
  relative_strength_6m_sector: "قدرت نسبی ۶ ماهه در صنعت",
  liquidity: "نقدشوندگی (ارزش معاملات ۳۰ روزه)",
  low_volatility: "نوسان ۳۰ روزه (کمتر بهتر)",
};

const AXIS_TITLES: Record<"q" | "v" | "t", string> = {
  q: "کیفیت (Q)",
  v: "ارزش‌گذاری (V)",
  t: "زمان‌بندی (T)",
};

const NORMALIZATION_LABELS: Record<string, string> = {
  ranked: "رتبه‌بندی‌شده",
  not_ranked_raw_not_applicable: "قابل‌کاربرد برای این شرکت نیست",
  pending_data: "در انتظار داده",
};

const RAW_STATUS_LABELS: Record<string, string> = {
  valid: "معتبر",
  missing: "مفقود",
  invalid: "نامعتبر",
  not_applicable: "قابل‌کاربرد نیست",
};

const fmt = (v: number | null | undefined, digits = 2) =>
  v == null ? "—" : v.toFixed(digits);

const fmtPct = (v: number | null | undefined, digits = 1) =>
  v == null ? "—" : `${(v * 100).toFixed(digits)}%`;

// مقدار خام بر اساس واحد واقعی فاکتور (بدون تغییر مقدار — فقط قالب‌بندی)
const fmtRaw = (factorId: string, v: number | null | undefined): string => {
  if (v == null) return "—";
  if (factorId === "liquidity") {
    // ارزش معاملات ۳۰ روزه به ریال
    if (Math.abs(v) >= 1e9) return `${(v / 1e9).toFixed(2)} میلیارد ریال`;
    if (Math.abs(v) >= 1e6) return `${(v / 1e6).toFixed(1)} میلیون ریال`;
    return `${v.toFixed(0)} ریال`;
  }
  if (
    factorId === "momentum_6m_rel" ||
    factorId === "momentum_3m_rel" ||
    factorId === "relative_strength_6m_sector" ||
    factorId === "low_volatility"
  ) {
    // کسر بازده/انحراف معیار روزانه → درصد
    return `${(v * 100).toFixed(1)}%`;
  }
  if (Math.abs(v) >= 1000) return v.toLocaleString("en-US", { maximumFractionDigits: 1 });
  return v.toFixed(2);
};

const factorLabel = (id: string) => FACTOR_LABELS[id] ?? id;

const directionLabel = (d: string) =>
  d === "lower" ? "پایین‌تر بهتر ↓" : d === "higher" ? "بالاتر بهتر ↑" : d;

const Chip: React.FC<{ tone: "ok" | "off" | "neutral" | "warn"; children: React.ReactNode; title?: string }> = ({
  tone,
  children,
  title,
}) => {
  const tones = {
    ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/25",
    off: "bg-gray-100 dark:bg-gray-700/40 text-gray-500 dark:text-gray-400 ring-gray-400/20",
    neutral: "bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-sky-500/25",
    warn: "bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-amber-500/25",
  } as const;
  return (
    <span
      title={title}
      className={`inline-flex items-center gap-1 rounded-lg px-1.5 py-0.5 text-[10px] font-semibold ring-1 whitespace-nowrap ${tones[tone]}`}
    >
      {children}
    </span>
  );
};

// سلول یک محور در جدول: امتیاز مشاهده‌شده + پوشش واقعی + وضعیت واجد شرایط
const AxisCell: React.FC<{ a: QvtAxisView; axis: "q" | "v" | "t" }> = ({ a, axis }) => {
  if (!a.present) {
    return <span className="text-xs text-gray-400 dark:text-gray-500">بدون داده</span>;
  }
  const eligibleTone = a.eligibility_known ? (a.pilot_eligible ? "ok" : "off") : "warn";
  const eligibleText = a.eligibility_known
    ? a.pilot_eligible
      ? "واجد ✓"
      : "ناواجد"
    : "خارج از دامنه";
  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-baseline gap-1">
        <span className="text-sm font-bold tabular-nums text-gray-800 dark:text-gray-100">
          {fmt(a.points)}
        </span>
        <span className="text-[10px] text-gray-400 dark:text-gray-500 tabular-nums">
          از {a.max_weight % 1 === 0 ? a.max_weight : fmt(a.max_weight, 1)}
        </span>
        <Chip tone={eligibleTone as "ok" | "off" | "warn"}>{eligibleText}</Chip>
      </div>
      <div className="flex items-center gap-1">
        <span
          className="text-[10px] tabular-nums text-gray-400 dark:text-gray-500"
          title={`پوشش واقعی ${AXIS_TITLES[axis]}`}
        >
          پوشش {fmt(a.covered_weight, 1)} ({fmtPct(a.coverage_ratio, 0)})
        </span>
      </div>
    </div>
  );
};

// ── پنل جزئیات یک نماد ───────────────────────────────────────────────────────
type QvtDetail = {
  company: {
    company_id: string;
    symbol: string;
    model_family: string;
    industry: string;
    axes: { q?: any; v?: any; t?: any };
    axis_max_weights: Record<string, number>;
  };
  weight_tables: Record<string, any>;
  disclaimer: string;
  as_of: string;
  cutoff: string;
};

const FactorRows: React.FC<{ factors: Record<string, any> }> = ({
  factors,
}) => {
  const ids = Object.keys(factors);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-separate border-spacing-y-1">
        <thead>
          <tr className="text-[10px] text-gray-400 dark:text-gray-500 text-right">
            <th className="px-2 py-1">فاکتور</th>
            <th className="px-2 py-1">وزن</th>
            <th className="px-2 py-1">جهت</th>
            <th className="px-2 py-1">وضعیت</th>
            <th className="px-2 py-1">مقدار خام</th>
            <th className="px-2 py-1">صدک</th>
            <th className="px-2 py-1">امتیاز وزنی</th>
            <th className="px-2 py-1">همتایان</th>
            <th className="px-2 py-1">دلیل / هشدار</th>
          </tr>
        </thead>
        <tbody>
          {ids.map((id) => {
            const f = factors[id];
            const ranked = f.normalization_status === "ranked" && f.score != null;
            const statusLabel =
              RAW_STATUS_LABELS[f.raw_status ?? ""] ??
              NORMALIZATION_LABELS[f.normalization_status ?? ""] ??
              f.normalization_status ??
              "—";
            const reason: string | null = f.not_included_reason ?? null;
            const warnings: string[] = f.warnings ?? [];
            return (
              <tr
                key={id}
                className="bg-white/70 dark:bg-gray-800/40 rounded-xl align-top"
              >
                <td className="px-2 py-1.5 font-semibold text-gray-700 dark:text-gray-200 rounded-r-xl">
                  {factorLabel(id)}
                  {f.essential ? (
                    <span className="mr-1 text-[9px] text-emerald-600 dark:text-emerald-400">
                      (ضروری)
                    </span>
                  ) : null}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300">
                  {f.weight}
                </td>
                <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">
                  {directionLabel(f.direction)}
                </td>
                <td className="px-2 py-1.5">
                  {f.included ? (
                    <Chip tone="ok">{statusLabel}</Chip>
                  ) : (
                    <Chip tone={f.raw_status === "invalid" ? "warn" : "off"}>
                      {statusLabel}
                    </Chip>
                  )}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300">
                  {fmtRaw(id, f.raw_value)}
                </td>
                <td className="px-2 py-1.5 tabular-nums">
                  {ranked ? (
                    <span className="text-sky-600 dark:text-sky-400 font-semibold">
                      {fmtPct(f.score, 1)}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300">
                  {f.included ? fmt(f.contribution_points) : "—"}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-500 dark:text-gray-400">
                  {f.n_valid_market_family != null
                    ? `بازار ${f.n_valid_market_family} / صنعت ${f.n_valid_sector ?? "—"}`
                    : "—"}
                </td>
                <td className="px-2 py-1.5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 rounded-l-xl max-w-[280px] break-words">
                  {reason && <div className="text-amber-600/90 dark:text-amber-400/80">{reason}</div>}
                  {warnings.map((w, i) => (
                    <div key={i}>{w}</div>
                  ))}
                  {!reason && warnings.length === 0 && <div>—</div>}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
};

const AxisDetail: React.FC<{
  axis: "q" | "v" | "t";
  data: any;
  maxWeight: number;
}> = ({ axis, data, maxWeight }) => {
  if (!data) {
    return (
      <p className="text-xs text-gray-400 dark:text-gray-500 px-1">
        برای این محور داده‌ای در آرتیفکت پایلوت نیست.
      </p>
    );
  }
  const factors = data.factors ?? {};
  const outOfScope = data.aggregation_status === "family_out_of_scope";
  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap items-center gap-2">
        <h4 className="text-sm font-bold text-gray-700 dark:text-gray-200">
          {AXIS_TITLES[axis]}
        </h4>
        <span className="text-xs tabular-nums text-gray-500 dark:text-gray-400">
          امتیاز مشاهده‌شده{" "}
          <b className="text-gray-800 dark:text-gray-100">
            {fmt(data[`${axis}_observed_points`])}
          </b>{" "}
          از {maxWeight}
        </span>
        <span className="text-[11px] tabular-nums text-gray-400 dark:text-gray-500">
          پوشش {fmt(data.covered_weight, 1)} از {maxWeight} ({fmtPct(data.coverage_ratio, 0)})
        </span>
        {data.pilot_eligible === true && <Chip tone="ok">واجد شرایط پایلوت ✓</Chip>}
        {data.pilot_eligible === false && <Chip tone="off">واجد شرایط نیست</Chip>}
        {outOfScope && <Chip tone="warn">خارج از دامنه این پایلوت</Chip>}
        {data.essential_status?.missing?.length > 0 && (
          <Chip tone="warn" title={data.essential_status.missing.join("، ")}>
            فاکتور ضروری مفقود: {data.essential_status.missing.map(factorLabel).join("، ")}
          </Chip>
        )}
      </div>
      {outOfScope && data.reason && (
        <p className="text-[11px] text-amber-600/90 dark:text-amber-400/80 px-1">
          {data.reason}
        </p>
      )}
      <FactorRows factors={factors} />      {axis === "q" && Array.isArray(data.limitations) && data.limitations.length > 0 && (
        <div className="px-1">
          <p className="text-[11px] font-semibold text-gray-500 dark:text-gray-400 mb-1">
            محدودیت‌های ثبت‌شده (بدون بازتوزیع وزن):
          </p>
          <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-400 dark:text-gray-500 space-y-0.5">
            {data.limitations.map((l: string, i: number) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

const DetailPanel: React.FC<{
  companyId: string;
  symbol: string;
  onClose: () => void;
}> = ({ companyId, symbol, onClose }) => {
  const [detail, setDetail] = useState<QvtDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setDetail(null);
    fetchQvtV2Detail(companyId)
      .then((d) => alive && setDetail(d))
      .catch((e) => alive && setError(e?.message || "خطا در دریافت جزئیات"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [companyId]);

  const finWarnings: string[] = detail
    ? [
        ...(detail.company.axes.q?.risk_gate?.financial_warnings ?? []),
        ...(detail.company.axes.v?.risk_gate?.financial_warnings ?? []),
      ]
    : [];
  const tradeWarnings: string[] = detail
    ? [
        ...(detail.company.axes.t?.risk_gate?.trading_warnings ?? []),
        ...(detail.company.axes.q?.risk_gate?.trading_warnings ?? []),
        ...(detail.company.axes.v?.risk_gate?.trading_warnings ?? []),
      ]
    : [];

  return (
    <div className="fixed inset-y-0 left-0 z-40 w-full max-w-3xl overflow-y-auto bg-gray-50 dark:bg-gray-900 shadow-2xl border-r border-gray-200/70 dark:border-gray-700/60 p-5">
      <div className="flex items-start justify-between gap-3 mb-3">
        <div>
          <h3 className="text-lg font-bold text-gray-800 dark:text-gray-100">
            {symbol || "—"}
          </h3>
          {detail && (
            <p className="text-[11px] text-gray-400 dark:text-gray-500 mt-0.5">
              {detail.company.industry} · خانواده {detail.company.model_family} ·{" "}
              <span dir="ltr" className="font-mono">{detail.company.company_id}</span>
            </p>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 flex items-center justify-center w-8 h-8 rounded-xl text-gray-500 hover:bg-gray-200/70 dark:hover:bg-gray-700/50 transition"
          aria-label="بستن جزئیات"
        >
          ✕
        </button>
      </div>

      <div className="rounded-2xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/60 dark:bg-amber-900/10 p-3 mb-4">
        <p className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 leading-5">
          {FALLBACK_DISCLAIMER}
        </p>
      </div>

      {loading && (
        <p className="text-sm text-gray-400 dark:text-gray-500 py-6 text-center">
          در حال بارگذاری جزئیات…
        </p>
      )}
      {error && (
        <div className="rounded-2xl border border-red-200/70 dark:border-red-900/40 bg-red-50/70 dark:bg-red-900/10 p-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}
      {detail && (
        <div className="flex flex-col gap-5">
          <div className="flex flex-wrap gap-2">
            <Chip tone="neutral">Data Confidence: ارزیابی نشده</Chip>
            <Chip tone="neutral">Risk Gate: ارزیابی نشده</Chip>
            <Chip tone="off">snapshot {detail.as_of}</Chip>
          </div>

          {(finWarnings.length > 0 || tradeWarnings.length > 0) && (
            <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
              <p className="text-xs font-bold text-gray-600 dark:text-gray-300 mb-1.5">
                هشدارهای مالی و معاملاتی (شواهد حفظ‌شده — نه ریسک ارزیابی‌شده)
              </p>
              <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5">
                {finWarnings.map((w, i) => (
                  <li key={`f${i}`}>{w}</li>
                ))}
                {tradeWarnings.map((w, i) => (
                  <li key={`t${i}`}>{w}</li>
                ))}
              </ul>
            </div>
          )}

          <AxisDetail axis="q" data={detail.company.axes.q} maxWeight={40} />
          <hr className="border-gray-200/60 dark:border-gray-700/40" />
          <AxisDetail axis="v" data={detail.company.axes.v} maxWeight={35} />
          <hr className="border-gray-200/60 dark:border-gray-700/40" />
          <AxisDetail axis="t" data={detail.company.axes.t} maxWeight={25} />
        </div>
      )}
    </div>
  );
};

// ── صفحه اصلی ────────────────────────────────────────────────────────────────
const QvtAnalysisPage: React.FC = () => {
  const [summary, setSummary] = useState<QvtV2Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [query, setQuery] = useState("");
  const [onlyTriple, setOnlyTriple] = useState(false);
  const [selected, setSelected] = useState<QvtCompanyRow | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetchQvtV2Summary()
      .then((d) => alive && setSummary(d))
      .catch((e) => alive && setError(e?.message || "خطا در دریافت خروجی QVT"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const rows = useMemo(() => {
    if (!summary) return [];
    const q = query.trim();
    return summary.companies.filter((r) => {
      if (onlyTriple && !r.all_three_eligible) return false;
      if (!q) return true;
      return (
        r.symbol.includes(q) ||
        r.industry.includes(q) ||
        r.model_family.includes(q) ||
        r.company_id.toLowerCase().includes(q.toLowerCase())
      );
    });
  }, [summary, query, onlyTriple]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-gray-400 dark:text-gray-500">
        <span className="text-sm font-medium">در حال بارگذاری خروجی واقعی QVT…</span>
      </div>
    );
  }

  if (error) {
    return (
      <div className="max-w-2xl mx-auto mt-10 rounded-3xl border border-red-200/70 dark:border-red-900/40 bg-red-50/70 dark:bg-red-900/10 p-6">
        <h2 className="text-base font-bold text-red-600 dark:text-red-400 mb-2">
          خروجی QVT قابل نمایش نیست
        </h2>
        <p className="text-sm text-red-500/90 dark:text-red-400/80 leading-6">{error}</p>
        <p className="text-xs text-gray-400 dark:text-gray-500 mt-3 leading-5">
          این صفحه فقط خروجی واقعی پایلوت V2 را نمایش می‌دهد و عمداً هیچ داده نمونه یا
          امتیاز فرضی ندارد. پس از تولید دوباره آرتیفکت‌های پایلوت (Q و V و T با یک
          اسنپ‌شات یکسان) صفحه به‌طور خودکار در reload بعدی پر می‌شود.
        </p>
      </div>
    );
  }

  if (!summary) return null;
  const c = summary.counts;

  return (
    <div className="flex flex-col gap-3">
      {/* بنر هشدار اجباری */}
      <div className="animate-fade-in-up rounded-2xl border border-amber-300/70 dark:border-amber-800/50 bg-gradient-to-l from-amber-50 to-orange-50/60 dark:from-amber-900/20 dark:to-orange-900/10 p-4">
        <p className="text-sm font-bold text-amber-700 dark:text-amber-300 leading-6">
          ⚠️ {summary.disclaimer || FALLBACK_DISCLAIMER}
        </p>
        <div className="flex flex-wrap items-center gap-2 mt-2">
          <Chip tone="neutral">Data Confidence: ارزیابی نشده</Chip>
          <Chip tone="neutral">Risk Gate: ارزیابی نشده</Chip>
          <Chip tone="off">snapshot {summary.as_of}</Chip>
          <Chip tone="off" title={`cutoff: ${summary.cutoff}`}>
            سه محور Q و V و T مستقل‌اند — هیچ امتیاز کل از ۱۰۰ وجود ندارد
          </Chip>
        </div>
      </div>

      {/* خلاصه واقعی پوشش (از خود آرتیفکت‌ها بازشماری‌شده) */}
      <div className="animate-fade-in-up grid grid-cols-3 md:grid-cols-6 gap-2" style={{ animationDelay: "60ms" }}>
        {[
          { label: "کل شرکت‌ها", value: c.n_total },
          { label: "Q واجد", value: c.n_q_eligible },
          { label: "V واجد", value: c.n_v_eligible },
          { label: "T واجد", value: c.n_t_eligible },
          { label: "Q و V", value: c.n_q_and_v },
          { label: "هر سه محور", value: c.n_all_three, hot: true },
        ].map((s) => (
          <div
            key={s.label}
            className={`rounded-2xl border p-3 text-center ${
              s.hot
                ? "border-emerald-300/70 dark:border-emerald-800/50 bg-emerald-50/70 dark:bg-emerald-900/20"
                : "border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30"
            }`}
          >
            <p className="text-lg font-bold tabular-nums text-gray-800 dark:text-gray-100">
              {s.value}
            </p>
            <p className="text-[10px] text-gray-400 dark:text-gray-500">{s.label}</p>
          </div>
        ))}
      </div>

      {/* جست‌وجو و فیلتر */}
      <div className="animate-fade-in-up flex flex-wrap items-center gap-2" style={{ animationDelay: "120ms" }}>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="جست‌وجوی نماد، صنعت یا شناسه…"
          className="h-9 w-64 rounded-xl border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-3 text-sm text-gray-700 dark:text-gray-200 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500 transition"
        />
        <button
          onClick={() => setOnlyTriple((v) => !v)}
          className={`h-9 px-3 rounded-xl text-xs font-semibold ring-1 transition ${
            onlyTriple
              ? "bg-emerald-500 text-white ring-emerald-600 shadow-sm shadow-emerald-500/25"
              : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-emerald-400/50"
          }`}
        >
          فقط واجد شرایط هر سه محور ({c.n_all_three})
        </button>
        <span className="text-[11px] text-gray-400 dark:text-gray-500">
          {rows.length} شرکت در نمایش
        </span>
        <span className="mr-auto text-[10px] text-gray-400 dark:text-gray-500" dir="ltr">
          {summary.sources.q.file} · {summary.sources.v.file} · {summary.sources.t.file}
        </span>
      </div>

      {/* جدول اصلی */}
      <div className="animate-fade-in-up rounded-3xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 overflow-hidden" style={{ animationDelay: "180ms" }}>
        <div className="overflow-x-auto max-h-[65vh] overflow-y-auto">
          <table className="w-full text-xs">
            <thead className="sticky top-0 z-10 bg-gray-100/95 dark:bg-gray-800/95 backdrop-blur text-[10px] text-gray-500 dark:text-gray-400">
              <tr className="text-right">
                <th className="px-3 py-2.5 font-semibold">نماد</th>
                <th className="px-3 py-2.5 font-semibold">صنعت</th>
                <th className="px-3 py-2.5 font-semibold">کیفیت Q (از ۴۰)</th>
                <th className="px-3 py-2.5 font-semibold">ارزش‌گذاری V (از ۳۵)</th>
                <th className="px-3 py-2.5 font-semibold">زمان‌بندی T (از ۲۵)</th>
                <th className="px-3 py-2.5 font-semibold">هر سه محور</th>
                <th className="px-3 py-2.5 font-semibold">هشدارها</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-3 py-8 text-center text-gray-400 dark:text-gray-500">
                    شرکتی با این جست‌وجو/فیلتر یافت نشد
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr
                  key={r.company_id}
                  onClick={() => setSelected(r)}
                  className="cursor-pointer border-t border-gray-100/80 dark:border-gray-700/40 hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10 transition-colors"
                >
                  <td className="px-3 py-2 font-bold text-gray-800 dark:text-gray-100 whitespace-nowrap">
                    {r.symbol}
                    <span className="mr-1.5 text-[9px] font-normal text-gray-400 dark:text-gray-500">
                      {r.model_family === "general" ? "" : r.model_family}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    {r.industry}
                  </td>
                  <td className="px-3 py-2"><AxisCell a={r.q} axis="q" /></td>
                  <td className="px-3 py-2"><AxisCell a={r.v} axis="v" /></td>
                  <td className="px-3 py-2"><AxisCell a={r.t} axis="t" /></td>
                  <td className="px-3 py-2">
                    {r.all_three_eligible ? (
                      <Chip tone="ok">✓ هر سه محور</Chip>
                    ) : r.any_axis_eligible ? (
                      <Chip tone="off">—</Chip>
                    ) : (
                      <Chip tone="off">—</Chip>
                    )}
                  </td>
                  <td className="px-3 py-2">
                    {r.q.n_warnings + r.v.n_warnings + r.t.n_warnings > 0 ? (
                      <Chip
                        tone="warn"
                        title={[
                          ...(r.q.financial_warnings ?? []),
                          ...(r.v.financial_warnings ?? []),
                          ...(r.t.trading_warnings ?? []),
                          ...(r.t.financial_warnings ?? []),
                        ].join("\n")}
                      >
                        {r.q.n_warnings + r.v.n_warnings + r.t.n_warnings} هشدار
                      </Chip>
                    ) : (
                      <span className="text-[10px] text-gray-300 dark:text-gray-600">—</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* مرزهای قرارداد — پایین جدول */}
      <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-3">
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-400 dark:text-gray-500 space-y-0.5">
          {Object.values(summary.boundaries).map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      </div>

      {selected && (
        <DetailPanel
          companyId={selected.company_id}
          symbol={selected.symbol}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
};

export default QvtAnalysisPage;
