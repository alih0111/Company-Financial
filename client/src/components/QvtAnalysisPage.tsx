import { useEffect, useMemo, useState } from "react";
import {
  fetchQvtV2Detail,
  fetchQvtV2Discovery,
  fetchQvtV2Summary,
  type QvtAxisView,
  type QvtBoardAxisStatus,
  type QvtBoardEntry,
  type QvtConfidence,
  type QvtConfidenceDimension,
  type QvtDiscoveryCompany,
  type QvtDiscoveryModeName,
  type QvtDiscoveryResponse,
  type QvtDiscoveryRow,
  type QvtEvidenceChain,
  type QvtEvidenceItem,
  type QvtBundleIntegrity,
  type QvtPriceFreshness,
  type QvtPriceSourceMeta,
  type QvtRiskArea,
  type QvtRiskFinding,
  type QvtRiskGate,
  type QvtRiskGateStatus,
  type QvtShortlist,
  type QvtShortlistEntry,
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
//   * Data Confidence ارزیابی کیفی مستقل شواهد است (بدون عدد اطمینان) و
//     Risk Gate ارزیابی مستقل ریسک با قواعد صریح — فقط‌خواندنی، بدون تغییر امتیاز
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

const Chip: React.FC<{
  tone: "ok" | "off" | "neutral" | "warn" | "danger";
  children: React.ReactNode;
  title?: string;
}> = ({
  tone,
  children,
  title,
}) => {
  const tones = {
    ok: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/25",
    off: "bg-gray-100 dark:bg-gray-700/40 text-gray-500 dark:text-gray-400 ring-gray-400/20",
    neutral: "bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-sky-500/25",
    warn: "bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-amber-500/25",
    danger: "bg-red-500/10 text-red-700 dark:text-red-300 ring-red-500/25",
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
    return <span className="text-xs text-gray-500 dark:text-gray-400">بدون داده</span>;
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
        <span className="text-[10px] text-gray-500 dark:text-gray-400 tabular-nums">
          از {a.max_weight % 1 === 0 ? a.max_weight : fmt(a.max_weight, 1)}
        </span>
        <Chip tone={eligibleTone as "ok" | "off" | "warn"}>{eligibleText}</Chip>
      </div>
      <div className="flex items-center gap-1">
        <span
          className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400"
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
  confidence?: QvtConfidence;
  risk_gate?: QvtRiskGate;
  evidence_overlay?: OverlayCompany;
  evidence_overlay_meta?: OverlayMeta;
  evidence_chain?: QvtEvidenceChain;
  bundle_integrity?: QvtBundleIntegrity;
  validation_actions?: ValidationAction[];
};

const FactorRows: React.FC<{ factors: Record<string, any> }> = ({
  factors,
}) => {
  const ids = Object.keys(factors);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs border-separate border-spacing-y-1">
        <thead>
          <tr className="text-[10px] text-gray-500 dark:text-gray-400 text-right">
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
                  {/* آرتیفکت Q مقدار خام فاکتورها را صادر نمی‌کند — پیام صریح،
                      نه مقدار فرضی */}
                  {f.raw_value == null ? (
                    <span className="text-[10px] text-gray-500 dark:text-gray-400">
                      مقدار خام در خروجی موجود نیست
                    </span>
                  ) : (
                    fmtRaw(id, f.raw_value)
                  )}
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
      <p className="text-xs text-gray-500 dark:text-gray-400 px-1">
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
        <span className="text-[11px] tabular-nums text-gray-500 dark:text-gray-400">
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
          <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5">
            {data.limitations.map((l: string, i: number) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

// ── Data Confidence مستقل (ارزیابی کیفی شواهد — بدون عدد اطمینان) ───────────
// از هشدارها و متادیتای واقعی آرتیفکت‌ها می‌خواند؛ «بدون یافته» هرگز معادل
// تأیید داده نیست و Risk Gate همچنان «ارزیابی نشده» می‌ماند.
const DC_STATUS_TONE: Record<string, "ok" | "warn" | "off"> = {
  no_findings: "ok",
  findings: "warn",
  not_evaluable: "off",
};
const DC_STATUS_SHORT: Record<string, string> = {
  no_findings: "بدون یافته ثبت‌شده",
  findings: "دارای یافته",
  not_evaluable: "ارزیابی‌ناپذیر",
};

const ConfidenceBadge: React.FC<{ cf: QvtConfidence }> = ({ cf }) => {
  const serious = (cf.serious_warnings ?? []).length;
  const tone = cf.overall === "findings" ? "warn" : cf.overall === "not_evaluable" ? "off" : "ok";
  const title = [
    cf.overall_label,
    "",
    ...(cf.dimensions ?? []).map(
      (d) => `${d.title}: ${DC_STATUS_SHORT[d.status] ?? d.status}${(d.reasons ?? []).length ? ` — ${d.reasons.join(" | ")}` : ""}`
    ),
    "",
    cf.overall_note,
    serious > 0 ? `هشدارهای جدی ثبت‌شده: ${cf.serious_warnings.join("، ")}` : "",
    cf.serious_note,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className="flex flex-col items-start gap-1">
      <Chip tone={tone} title={title}>
        {cf.overall === "findings"
          ? `اطمینان داده: ${cf.dimension_counts.findings} بُعد دارای یافته`
          : cf.overall === "not_evaluable"
            ? "اطمینان داده: ارزیابی‌ناپذیر"
            : "اطمینان داده: بدون یافته ثبت‌شده"}
      </Chip>
      {serious > 0 && (
        <Chip
          tone="off"
          title={`${cf.serious_note}\n\nانواع هشدار جدی ثبت‌شده:\n${cf.serious_warnings.join("\n")}`}
        >
          {serious} هشدار جدی ثبت‌شده
        </Chip>
      )}
      {cf.dimension_counts.not_evaluable > 0 && (
        <Chip tone="off" title="ابعادی که شواهد کافی برای ارزیابی آن‌ها در آرتیفکت‌ها ثبت نشده است">
          {cf.dimension_counts.not_evaluable} بُعد ارزیابی‌ناپذیر
        </Chip>
      )}
    </div>
  );
};

const ConfidenceDetailBlock: React.FC<{ cf: QvtConfidence }> = ({ cf }) => (
  <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
    <p className="text-xs font-bold text-gray-600 dark:text-gray-300 mb-1">
      وضعیت اطمینان داده (ارزیابی کیفی مستقل شواهد — بدون عدد اطمینان)
    </p>
    <p className="text-[10px] leading-4 text-gray-500 dark:text-gray-400 mb-2">
      {cf.overall_label} — {cf.overall_note}
    </p>
    <div className="flex flex-col gap-2">
      {(cf.dimensions ?? []).map((d: QvtConfidenceDimension) => (
        <div
          key={d.key}
          className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-900/20 p-2"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={DC_STATUS_TONE[d.status] ?? "off"}>{DC_STATUS_SHORT[d.status] ?? d.status}</Chip>
            <b className="text-[11px] text-gray-700 dark:text-gray-200">{d.title}</b>
          </div>
          <p className="text-[10px] text-gray-500 dark:text-gray-400 mt-1 leading-4" dir="auto">
            منابع بررسی‌شده: {d.sources}
          </p>
          {(d.reasons ?? []).length > 0 ? (
            <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
              {d.reasons.map((r, i) => (
                <li key={i} dir="auto">{r}</li>
              ))}
            </ul>
          ) : (
            <p className="text-[10px] text-gray-300 dark:text-gray-600 mt-1">
              یافته‌ای ثبت نشده — این به معنی تأیید داده نیست.
            </p>
          )}
        </div>
      ))}
    </div>
    {(cf.serious_warnings ?? []).length > 0 && (
      <div className="mt-2 rounded-xl border border-red-200/60 dark:border-red-900/40 bg-red-50/50 dark:bg-red-900/10 p-2">
        <p className="text-[10px] font-bold text-red-600 dark:text-red-400">
          هشدارهای جدی ثبت‌شده: {cf.serious_warnings.join("، ")}
        </p>
        <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-0.5">{cf.serious_note}</p>
      </div>
    )}
    <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-2">
      دروازه ریسک به‌صورت مستقل در بلوک بعدی ارزیابی می‌شود؛ این بلوک هیچ ارزیابی ریسک یا
      امتیاز اطمینان عددی ارائه نمی‌دهد و هیچ امتیاز Q/V/T را تغییر نمی‌دهد.
    </p>
  </div>
);

// ── دروازه ریسک مستقل (گام ۲-ح-۱) — فقط‌خواندنی، با قواعد مسدودسازی صریح ────
// سه حوزه جدا: اعتبار داده / ریسک بنیادی و ارزندگی / ریسک بازار و ورود؛
// «بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن یا تأیید سرمایه‌گذاری نیست.
const RG_STATUS_TONE: Record<string, "ok" | "warn" | "off" | "neutral" | "danger"> = {
  blocked: "danger",
  review_required: "warn",
  insufficient_evidence: "neutral",
  no_verified_blocker: "ok",
};

const SEV_TONE: Record<string, "ok" | "off" | "neutral" | "warn" | "danger"> = {
  proven_data_error: "danger",
  suspected_data_issue: "warn",
  consistency_review: "warn",
  economic_risk: "warn",
  valuation_band: "neutral",
  market_structure: "neutral",
  provenance_note: "off",
  unknown: "warn",
};

const RiskGateBadge: React.FC<{ rg: QvtRiskGate }> = ({ rg }) => {
  const title = [
    `دروازه ریسک: ${rg.status_label}`,
    "",
    ...rg.areas.map(
      (a) =>
        `${a.title}: ${a.status_label}` +
        (a.findings.length ? ` — ${a.findings.map((f) => f.category).join("، ")}` : "") +
        (a.evidence_gaps.length ? ` — شکاف شواهد: ${a.evidence_gaps.length} مورد` : "")
    ),
    "",
    rg.status_note,
    rg.note,
  ]
    .filter(Boolean)
    .join("\n");
  return (
    <div className="flex flex-col items-start gap-1">
      <Chip tone={RG_STATUS_TONE[rg.status] ?? "off"} title={title}>
        {rg.status_label}
      </Chip>
      {rg.blockers.length > 0 && (
        <Chip
          tone="danger"
          title={rg.blockers
            .map((b) => `${b.category} — قاعده ${b.blocking_rule ?? "?"}\n${b.evidence.join("\n")}`)
            .join("\n——\n")}
        >
          {rg.blockers.length} مانع اثبات‌شده
        </Chip>
      )}
    </div>
  );
};

const RiskFindingRow: React.FC<{ f: QvtRiskFinding }> = ({ f }) => (
  <div className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-900/20 p-2">
    <div className="flex flex-wrap items-center gap-1.5">
      <Chip tone={SEV_TONE[f.severity] ?? "off"}>{f.severity_label}</Chip>
      <b className="text-[11px] text-gray-700 dark:text-gray-200">{f.category}</b>
      <Chip tone="off">محور {f.axis}</Chip>
      {f.blocking_rule && <Chip tone="danger">قاعده {f.blocking_rule}</Chip>}
    </div>
    <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-1">{f.reason}</p>
    <ul
      className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1"
      dir="auto"
    >
      {f.evidence.map((e, i) => (
        <li key={i}>{e}</li>
      ))}
    </ul>
  </div>
);

const RiskGateDetailBlock: React.FC<{ rg: QvtRiskGate }> = ({ rg }) => (
  <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
    <p className="text-xs font-bold text-gray-600 dark:text-gray-300 mb-1">
      دروازه ریسک (ارزیابی مستقل فقط‌خواندنی — بدون تغییر امتیاز Q/V/T)
    </p>
    <p className="text-[10px] leading-4 text-gray-500 dark:text-gray-400 mb-2">
      <b className="text-gray-600 dark:text-gray-300">{rg.status_label}</b> — {rg.status_note}
    </p>
    <div className="flex flex-col gap-2">
      {rg.areas.map((a: QvtRiskArea) => (
        <div
          key={a.key}
          className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-900/20 p-2"
        >
          <div className="flex flex-wrap items-center gap-2">
            <Chip tone={RG_STATUS_TONE[a.status] ?? "off"}>{a.status_label}</Chip>
            <b className="text-[11px] text-gray-700 dark:text-gray-200">{a.title}</b>
          </div>
          {a.findings.length > 0 ? (
            <div className="flex flex-col gap-1.5 mt-1.5">
              {a.findings.map((f, i) => (
                <RiskFindingRow key={i} f={f} />
              ))}
            </div>
          ) : (
            <p className="text-[10px] text-gray-300 dark:text-gray-600 mt-1">
              یافته‌ای در این حوزه ثبت نشده — این به معنی نبود ریسک نیست.
            </p>
          )}
          {a.evidence_gaps.length > 0 && (
            <div className="mt-1.5">
              <p className="text-[10px] font-semibold text-gray-500 dark:text-gray-400">
                شکاف شواهد (بررسی ناتمام — نه خطای اثبات‌شده):
              </p>
              <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-0.5">
                {a.evidence_gaps.map((g, i) => (
                  <li key={i} dir="auto">{g}</li>
                ))}
              </ul>
            </div>
          )}
          <details className="mt-1">
            <summary className="text-[10px] text-sky-600 dark:text-sky-400 cursor-pointer">
              بررسی‌های انجام‌شده این حوزه
            </summary>
            <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-0.5">
              {a.checks.map((c, i) => (
                <li key={i}>{c}</li>
              ))}
            </ul>
          </details>
        </div>
      ))}
    </div>
    <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-2">{rg.note}</p>
  </div>
);

// خلاصه کوتاه شواهد نامزد (گام ۲-ط-۱) — بازخوانی مکانیکی شواهد ثبت‌شده:
// قوت/ضعف مشاهده‌شده، پوشش و محدودیت‌ها، ریسک‌های ثبت‌شده، اعتبار تاریخ
// قیمت و شواهد مفقود. هیچ تحلیلی فراتر از داده تولید نمی‌شود؛ اگر مقدار
// یا نسبتی موجود نیست صریح گفته می‌شود.
const CandidateEvidenceBlock: React.FC<{ c: QvtShortlistEntry }> = ({ c }) => {
  const axes = [
    { key: "q", title: "Q", a: c.q, max: 40 },
    { key: "v", title: "V", a: c.v, max: 35 },
    { key: "t", title: "T", a: c.t, max: 25 },
  ] as const;
  const strengths = axes.filter((x) => x.a.points != null && x.a.coverage_threshold_met !== false);
  const weakAxes = axes.filter(
    (x) => x.a.points == null || x.a.coverage_threshold_met === false
  );
  const issues = axes.flatMap((x) =>
    (x.a.factor_issues ?? []).map((fi) => ({
      axis: x.title,
      factor: fi.factor,
      kind: fi.kind,
      reason: fi.reason,
    }))
  );
  const rgFindings = [
    ...(c.risk_gate?.blockers ?? []),
    ...(c.risk_gate?.review_findings ?? []),
  ]
    .sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9))
    .slice(0, 3);
  const gaps = (c.risk_gate?.evidence_gaps ?? []).slice(0, 4);
  const seriousKinds = c.confidence?.serious_warnings ?? [];
  const sub = (t: string) => (
    <p className="text-[10px] font-bold text-gray-600 dark:text-gray-300 mt-2 mb-0.5">{t}</p>
  );
  const none = <span className="text-[10px] text-gray-500 dark:text-gray-400">— ثبت‌شده‌ای نیست</span>;
  return (
    <div className="rounded-2xl border border-emerald-200/60 dark:border-emerald-900/40 bg-emerald-50/40 dark:bg-emerald-900/10 p-3">
      <p className="text-[11px] font-bold text-emerald-700 dark:text-emerald-300 mb-0.5">
        خلاصه شواهد نامزد — بازخوانی مکانیکی، نه تحلیل حدسی
      </p>
      <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4">
        جایگاه مقایسه‌ای: {c.reason}
      </p>

      {sub("نقاط قوت مشاهده‌شده")}
      {strengths.length === 0 ? (
        none
      ) : (
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-600 dark:text-gray-300 space-y-0.5">
          {strengths.map((x) => (
            <li key={x.key} className="tabular-nums">
              {x.title}: {fmt(x.a.points!)} امتیاز مشاهده‌شده از {x.max} — پوشش{" "}
              {fmtPct(x.a.coverage_ratio, 0)}
            </li>
          ))}
        </ul>
      )}

      {sub("نقاط ضعف مشاهده‌شده")}
      {weakAxes.length === 0 && issues.length === 0 ? (
        none
      ) : (
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-600 dark:text-gray-300 space-y-0.5">
          {weakAxes.map((x) => (
            <li key={x.key} className="tabular-nums">
              {x.title}:{" "}
              {x.a.points == null
                ? "امتیاز مشاهده‌شده ندارد (مفقود — صفر فرض نشده)"
                : `پوشش زیر آستانه (${fmtPct(x.a.coverage_ratio, 0)})`}
            </li>
          ))}
          {issues.length > 0 && (
            <li>
              فاکتورهای امتیازنگرفته یا با مقدار نامعتبر: {issues.length} مورد (فهرست در
              «محدودیت داده‌ها»)
            </li>
          )}
        </ul>
      )}

      {sub("پوشش و محدودیت داده‌ها")}
      {issues.length === 0 ? (
        <span className="text-[10px] text-gray-500 dark:text-gray-400">
          همه فاکتورهای موردنیاز امتیاز گرفته‌اند — نسبت یا مقدار خام مفقودی ثبت نشده
        </span>
      ) : (
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5">
          {issues.slice(0, 5).map((fi, i) => (
            <li key={i} dir="auto">
              {fi.axis} / {factorLabel(fi.factor)}: {fi.reason || "بدون توضیح ثبت‌شده"}
            </li>
          ))}
          {issues.length > 5 && <li>… و {issues.length - 5} مورد دیگر</li>}
        </ul>
      )}

      {sub("ریسک‌های ثبت‌شده (دروازه ریسک)")}
      <p className="text-[10px] text-gray-500 dark:text-gray-400">
        وضعیت: {c.risk_gate?.status_label ?? "—"}{" "}
        <span className="text-gray-500 dark:text-gray-400">
          (هیچ وضعیتی به معنی تأیید یا کم‌ریسک بودن نیست)
        </span>
      </p>
      {rgFindings.length === 0 ? (
        none
      ) : (
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-0.5">
          {rgFindings.map((f, i) => (
            <li key={i} dir="auto">
              {f.category} — {f.severity_label} ({f.axis})
            </li>
          ))}
        </ul>
      )}

      {sub("اعتبار تاریخ قیمت استفاده‌شده")}
      <PriceFreshnessCell pf={c.price_freshness} />

      {sub("شواهد مفقود و موارد نیازمند بررسی")}
      {gaps.length === 0 && seriousKinds.length === 0 ? (
        none
      ) : (
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5">
          {gaps.map((gp, i) => (
            <li key={`g${i}`} dir="auto">
              {gp}
            </li>
          ))}
          {seriousKinds.map((k, i) => (
            <li key={`s${i}`} dir="auto">
              هشدار جدی ثبت‌شده در اطمینان داده: {k}
            </li>
          ))}
        </ul>
      )}

      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-2">
        این خلاصه فقط از شواهد ثبت‌شده ساخته می‌شود و توصیه خرید/فروش نیست؛ Data
        Confidence و Risk Gate حق تغییر امتیازها یا لایه‌های پارتو را ندارند.
      </p>
    </div>
  );
};

// ── اعتبار منابع محاسبه (گام ۲-ی-۱) ──
// ردیابی فقط‌خواندنی ورودی‌های Q/V/T از منبع واقعی، با قرارداد چهار وضعیتی.
// هیچ امتیاز، رتبه یا درصد اطمینانی نمی‌سازد؛ «نبود داده» را با «خطای کنترل»
// (checked=false) جدا می‌کند و هیچ تاریخ یا منبعی را حدس نمی‌زند.
const EV_STATUS_TONE: Record<string, "ok" | "off" | "warn" | "danger"> = {
  verified_from_source: "ok",
  partially_verified: "warn",
  unverified: "off",
  conflicting: "danger",
};

// Overlay ممیزی مستقل (گام ۲-ک-۱) — payload آزاد از گزارش‌های provenance_v1
// است؛ فقط وقتی نمایش داده می‌شود که binding آن با hash همین snapshot یکی
// باشد (گزارش بک‌اند) — در غیر این صورت backend وضعیت absent می‌دهد.
type OverlayCompany = Record<string, any>;
type ValidationAction = { title: string; detail: string; priority: string };
type OverlayMeta = { status: "bound" | "absent"; files?: string[]; note?: string };

// وضعیت‌های اعتبارسنجی اقتصادی مستقل (۲-ک-۲) — مستقل از امتیازها و Risk Gate.
// غیبت وضعیت یعنی «ارزیابی نشده»، هرگز «تأییدشده».
const VAL_STATUS_TONE: Record<string, "ok" | "off" | "warn" | "danger"> = {
  independently_checked: "ok",
  consistent_but_not_independent: "warn",
  insufficient_evidence: "off",
  conflicting: "danger",
};
const VAL_STATUS_FA: Record<string, string> = {
  independently_checked: "بررسی مستقل کامل",
  consistent_but_not_independent: "سازگار اما غیرمستقل",
  insufficient_evidence: "شواهد ناکافی",
  conflicting: "تعارض",
};

const fmtRial = (v: any): string => {
  const n = Number(v);
  if (!Number.isFinite(n)) return "—";
  if (Math.abs(n) >= 1e12) return `${(n / 1e12).toFixed(2)} هزار میلیارد`;
  if (Math.abs(n) >= 1e9) return `${(n / 1e9).toFixed(2)} میلیارد`;
  if (Math.abs(n) >= 1e6) return `${(n / 1e6).toFixed(2)} میلیون`;
  return n.toLocaleString("fa-IR", { maximumFractionDigits: 0 });
};

// ── پرونده تصمیم‌یار سهم (گام ۲-ک-۳ P2) ──────────────────────────────────────
// پنج بخش فقط با شواهد آرتیفکت‌های نسخه‌دار همین snapshot (sidecar
// decision_dossier با گیت binding). هیچ امتیاز ترکیبی یا وزن پنهانی ندارد و
// هیچ جمله‌ای به داده وصل نیست نمایش داده نمی‌شود. جمع‌بندی سه‌پرسشی بالای
// پرونده می‌آید تا تحلیلگر اول «چرا / چه ریسکی / چه چیزی کم است» را ببیند.
const RELIABILITY_TONE: Record<string, "ok" | "off" | "warn"> = {
  reliable: "ok",
  time_limited: "warn",
  missing: "off",
};

const DossierSummaryCard: React.FC<{
  title: string;
  tone: string;
  items: string[];
  empty: string;
}> = ({ title, tone, items, empty }) => (
  <div className="rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
    <p className={`text-[10px] font-bold mb-1 ${tone}`}>{title}</p>
    <ul className="list-disc pr-4 space-y-1">
      {(items.length ? items : [empty]).map((s, i) => (
        <li key={i} className="text-[10px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
          {s}
        </li>
      ))}
    </ul>
  </div>
);

// ── گام ۲-ک-۵ P2 — «شاخص‌های بنیادی در حال اعتبارسنجی» ──────────────────────
// سه فاکتور فعلاً غیرفعال Q (roe_stability / margin_trend / earnings_growth)
// از sidecar نسخه‌دار q_factor_diagnostics با گیت binding. کاملاً تشخیصی:
// امتیاز رسمی Q، لایه‌بندی پارتو و Risk Gate را تغییر نمی‌دهد و هیچ توصیه‌ای
// نیست. کدام‌ها شواهد کافی دارند و کدام diagnostic/ناکافی‌اند صریح نمایش
// داده می‌شود؛ نبود داده پنهان نمی‌شود.
const DIAG_STATUS_TONE: Record<string, string> = {
  computed: "bg-emerald-100/70 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  computed_official: "bg-emerald-100/70 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  insufficient_evidence: "bg-amber-100/70 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  raw_missing: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  invalid: "bg-red-100/70 text-red-700 dark:bg-red-900/30 dark:text-red-300",
  not_applicable: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
};

const DIAG_VERDICT_FA: Record<string, string> = {
  ready_for_activation_proposal: "آمادهٔ پیشنهاد فعال‌سازی در مرحلهٔ بعد",
  conditional: "مشروط — فعلاً تشخیصی",
  keep_disabled: "غیرفعال بماند",
};

const QFactorCard: React.FC<{ f: any; verdict: any; egAudit?: any }> = ({ f, verdict, egAudit }) => {
  if (!f) return null;
  const fmt = (v: any, suffix: string) =>
    v == null ? null : `${Number(v).toFixed(1)}${suffix}`;
  return (
    <div className="rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5 mb-1">
        <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200">{f.fa ?? f.factor}</p>
        <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${DIAG_STATUS_TONE[f.status] ?? DIAG_STATUS_TONE.raw_missing}`}>
          {f.status_fa ?? f.status}
        </span>
        {verdict && (
          <span className="px-1.5 py-0.5 rounded text-[9px] bg-sky-100/70 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300">
            {DIAG_VERDICT_FA[verdict.verdict] ?? verdict.verdict}
          </span>
        )}
      </div>
      {/* مقدار تشخیصی — هرگز جزو امتیاز رسمی نیست */}
      {f.status === "computed" || f.status === "computed_official" ? (
        <p className="text-[10px] text-gray-600 dark:text-gray-300" dir="auto">
          {f.factor === "roe_stability" && f.value != null && (
            <>
              انحراف معیار ROE سالانه: <b>{fmt(f.value, " واحد درصد")}</b> · {f.n_valid_years} سال معتبر
              {Array.isArray(f.window) && f.window.length > 0 && ` (پنجرهٔ ${f.window[0]}–${f.window[f.window.length - 1]})`}
              {f.mean_roe_pct != null && ` · میانگین ROE ${Number(f.mean_roe_pct).toFixed(1)}٪`}
            </>
          )}
          {f.factor === "margin_trend" && f.value_pp != null && (
            <>تفاضل حاشیهٔ سود عملیاتی TTM نسبت به سال قبل: <b>{fmt(f.value_pp, " واحد درصد")}</b></>
          )}
          {f.factor === "earnings_growth" && f.blended_score_preserved != null && (
            <>امتیاز ترکیبی حفظ‌شدهٔ تشخیصی: <b>{(Number(f.blended_score_preserved) * 100).toFixed(0)}٪</b> (خارج از تجمیع رسمی)</>
          )}
          {f.factor === "earnings_growth" && f.blended_score_preserved == null && (
            <>اجزای حفظ‌شدهٔ تشخیصی: {(Object.entries(f.components ?? {}) as [string, any][])
              .map(([k, v]) => `${k === "net_profit_growth_pct" ? "سود خالص" : "سود عملیاتی"}: ${v.status === "valid" ? "معتبر" : "بدون مقدار معتبر"}`)
              .join(" · ")}</>
          )}
        </p>
      ) : (
        <p className="text-[10px] text-gray-500 dark:text-gray-400" dir="auto">
          مقدار محاسبه‌شدهٔ معتبری برای این شرکت وجود ندارد — هیچ عدد جایگزینی ساخته نشده است.
        </p>
      )}
      {(f.missing_reason || f.excluded_years?.length > 0) && (
        <p className="text-[9px] text-amber-700/90 dark:text-amber-400/80 mt-0.5" dir="auto">
          {f.missing_reason}
          {f.excluded_years?.length > 0 &&
            ` · سال‌های حذف‌شده: ${f.excluded_years.map((e: any) => `${e.fy} (${e.reason})`).join("، ")}`}
        </p>
      )}
      {verdict?.condition && (
        <p className="text-[9px] text-gray-500 dark:text-gray-400 mt-0.5" dir="auto">{verdict.condition}</p>
      )}
      {/* گام ۲-ک-۶ — نتیجهٔ ممیزی اقتصادی مستقل earnings_growth (کاملاً تشخیصی) */}
      {f.factor === "earnings_growth" && egAudit && (
        <EgAuditBlock audit={egAudit} />
      )}
    </div>
  );
};

// ── گام ۲-ک-۶ — بلوک ممیزی اقتصادی رشد سود ───────────────────────────────────
// دورهٔ مقایسه + مقدار خام هر جزء + وضعیت اعتبار + محدودیت‌ها/هشدارها؛
// تفکیک رسمی (ورود به تجمیع: ممنوع با policy exclusion ۲-ب-۶) و تشخیصی.
const EgAuditBlock: React.FC<{ audit: any }> = ({ audit }) => {
  if (!audit) return null;
  const fmtPct = (v: any) =>
    v == null ? "—" : `${Number(v) >= 1e6 ? Number(v).toExponential(2) : Number(v).toFixed(1)}٪`;
  const fmtRial = (v: any) =>
    v == null ? "—" : `${(Number(v) / 1e9).toFixed(1)} میلیارد ریال`;
  const tone = EG_VERDICT_TONE[audit.verdict] ?? EG_VERDICT_TONE.diagnostic_only;
  return (
    <div className="mt-1.5 pt-1.5 border-t border-gray-200/60 dark:border-gray-700/40 space-y-1">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={`px-1.5 py-0.5 rounded text-[9px] font-semibold ${tone}`}>
          ممیزی اقتصادی ۲-ک-۶: {audit.verdict_fa ?? audit.verdict}
        </span>
      </div>
      {(audit.components
        ? (Object.entries(audit.components) as [string, any][])
        : []).map(([k, c]) => (
        <p key={k} className="text-[10px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
          {k === "net_profit_growth_pct" ? "سود خالص" : "سود عملیاتی"}:{" "}
          {c.value_pct != null ? (
            <>
              <b>{fmtPct(c.value_pct)}</b> (TTM منتهی به {c.period_current ?? "—"} در برابر پایهٔ TTM منتهی به {c.period_base ?? "—"}: جاری {fmtRial(c.current_ttm)} / پایه {fmtRial(c.base)})
            </>
          ) : (
            <>{c.status_fa ?? c.status} — هیچ درصدی ساخته نشده</>
          )}
          {" · "}
          {c.value_match_with_engine === true
            ? "بازتولید مستقل: منطبق"
            : c.value_match_with_engine === false
              ? "بازتولید مستقل: مغایرت!"
              : "بازتولید مستقل: نا‌مقایسه (بدون مقدار معتبر)"}
        </p>
      ))}
      {Array.isArray(audit.warnings) && audit.warnings.length > 0 && (
        <div className="rounded-lg bg-amber-50/70 dark:bg-amber-900/10 p-1.5">
          <p className="text-[9px] font-bold text-amber-700 dark:text-amber-400 mb-0.5">
            ⚠ هشدار کیفی — رشد این شرکت را بدون دیدن این موارد «قابل‌دفاع» فرض نکنید:
          </p>
          <ul className="list-disc pr-4 space-y-0.5">
            {audit.warnings.map((w: string, i: number) => (
              <li key={i} className="text-[9px] leading-4 text-amber-700/90 dark:text-amber-400/80" dir="auto">{w}</li>
            ))}
          </ul>
        </div>
      )}
      {Array.isArray(audit.limitations) && audit.limitations.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[9px] text-gray-500 dark:text-gray-400 select-none">
            محدودیت‌های ثبت‌شده ({audit.limitations.length})
          </summary>
          <ul className="list-disc pr-4 mt-0.5 space-y-0.5">
            {audit.limitations.map((l: string, i: number) => (
              <li key={i} className="text-[9px] leading-4 text-gray-500 dark:text-gray-400" dir="auto">{l}</li>
            ))}
          </ul>
        </details>
      )}
      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
        {audit.in_official_composite
          ? "هر دو جزء معتبر است (ترکیب رسمی قابل‌تشکیل) — اما فاکتور با policy exclusion گام ۲-ب-۶ همچنان از تجمیع رسمی Q خارج است."
          : "ترکیب رسمی فاکتور برای این شرکت قابل‌تشکیل نیست (یک جزء بدون پایهٔ قابل‌اتکا) — هیچ درصد جایگزینی ساخته نشده."}
        {" "}این بلوک تشخیصی است و هیچ اثری روی امتیاز رسمی، پارتو و Risk Gate ندارد.
      </p>
    </div>
  );
};

const EG_VERDICT_TONE: Record<string, string> = {
  verified: "bg-emerald-100/70 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300",
  verified_with_limitation: "bg-sky-100/70 text-sky-800 dark:bg-sky-900/30 dark:text-sky-300",
  diagnostic_only: "bg-amber-100/70 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300",
  insufficient_evidence: "bg-gray-100 text-gray-600 dark:bg-gray-800/60 dark:text-gray-400",
  invalid: "bg-red-100/70 text-red-700 dark:bg-red-900/30 dark:text-red-300",
};

const DiagnosticQFactorsSection: React.FC<{ qd: any | null; egAudit?: any | null }> = ({ qd, egAudit }) => {
  if (!qd || !qd.factors) return null;
  // payload هر شرکت خودکفاست (activation_readiness و _meta داخل همان
  // payload می‌آیند)؛ خواندن سطح سند فقط fallback است
  const readiness = qd.activation_readiness
    ?? qd.factors_meta?.activation_readiness ?? {};
  const m = qd._meta ?? null;
  const qp = m ?? qd.quarantine_proof ?? null;
  const cons = m ?? qd.consistency_with_production_artifact ?? null;
  const repro = m?.independent_reproduction ?? qd.independent_reproduction ?? null;
  return (
    <div className="rounded-2xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/40 dark:bg-sky-900/10 p-3">
      <p className="text-[11px] font-bold text-sky-700 dark:text-sky-300">
        🔬 شاخص‌های بنیادی در حال اعتبارسنجی — فقط تشخیصی
      </p>
      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1" dir="auto">
        سه فاکتور فعلاً غیرفعال محور کیفیت با محاسبهٔ تشخیصی روی دادهٔ واقعی همین snapshot. این شاخص‌ها امتیاز رسمی Q،
        رتبه‌بندی پارتو و Risk Gate را تغییر نمی‌دهند و توصیهٔ خرید/فروش نیستند؛ فعال‌سازی هرکدام فقط با تصمیم مرحلهٔ بعد
        ممکن است.
      </p>
      <div className="grid md:grid-cols-3 gap-2 mt-2.5">
        <QFactorCard f={{ ...qd.factors.roe_stability, factor: "roe_stability" }} verdict={readiness.roe_stability} />
        <QFactorCard f={{ ...qd.factors.margin_trend, factor: "margin_trend" }} verdict={readiness.margin_trend} />
        <QFactorCard f={{ ...qd.factors.earnings_growth, factor: "earnings_growth" }} verdict={readiness.earnings_growth} egAudit={egAudit ?? null} />
      </div>
      {egAudit?._meta && (
        <div className="mt-2 rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
          <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200 mb-1">
            ممیزی اقتصادی مستقل رشد سود (گام ۲-ک-۶) — نتیجهٔ کل ۶۲ شرکت سه‌محوری
          </p>
          <p className="text-[9px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
            بازتولید مستقل: {egAudit._meta.reproduction_summary?.n_components_value_compared ?? "—"} جزء مقایسه‌شده،{" "}
            {egAudit._meta.reproduction_summary?.n_value_diff ?? "—"} مغایرت · طبقه‌بندی:{" "}
            {egAudit._meta.classification_counts?.verified ?? 0} تأییدشده،{" "}
            {egAudit._meta.classification_counts?.verified_with_limitation ?? 0} با محدودیت،{" "}
            {egAudit._meta.classification_counts?.insufficient_evidence ?? 0} بدون شواهد کافی · قرنطینه:{" "}
            {egAudit._meta.quarantine_leak_proof?.verdict === "quarantine_leak_free"
              ? `بدون نشت (${egAudit._meta.quarantine_leak_proof?.n_quarantined_components_checked} جزء بررسی‌شده)`
              : egAudit._meta.quarantine_leak_proof?.verdict}
          </p>
          <p className="text-[9px] leading-4 text-gray-500 dark:text-gray-400 mt-0.5" dir="auto">
            {egAudit._meta.economic_quality_note}
          </p>
          <p className="text-[9px] leading-4 text-gray-500 dark:text-gray-400 mt-0.5" dir="auto">
            {egAudit._meta.disclaimer}
          </p>
        </div>
      )}
      {qp && (
        <p className="text-[9px] text-gray-500 dark:text-gray-400 mt-2 leading-4" dir="auto">
          کنترل قرنطینهٔ سود: {qp.quarantine_verdict ?? qp.verdict} —{" "}
          {qp.quarantine_companies ?? qp.n_companies_with_quarantined_base} شرکت با پایهٔ قرنطینه‌شده،{" "}
          {qp.quarantine_leaks ?? qp.n_valid_despite_quarantine} نشت به مقدار معتبر · سرشماری ردیف‌های سنتیل:{" "}
          {qp.sentinel_rows_total} {qp.sentinel_check ? `(${qp.sentinel_check})` : ""}
        </p>
      )}
      {repro && (
        <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
          بازتولید مستقل با SQL خام (۱۶ نامزد): {repro.n_years_compared} سال مقایسه — {repro.n_match} تطبیق،{" "}
          {repro.n_mismatch} مغایرت
        </p>
      )}
      {cons && (
        <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
          تطبیق با آرتیفکت تولیدی: {(cons.consistency_verdict ?? cons.verdict) === "recomputed_matches_production_artifact"
            ? `کامل — ${cons.consistency_scores_checked ?? cons.n_company_factor_scores_checked} امتیاز شرکت-فاکتور بدون مغایرت`
            : (cons.consistency_verdict ?? cons.verdict)}
        </p>
      )}
    </div>
  );
};

const DecisionDossierSection: React.FC<{ dd: any | null }> = ({ dd }) => {
  if (!dd || !dd.sections) return null;
  const q = dd.sections.quality ?? {};
  const v = dd.sections.value ?? {};
  const m = dd.sections.market ?? {};
  const ev = dd.sections.evidence ?? {};
  const sum = dd.sections.summary ?? {};
  const px = m.price ?? {};
  return (
    <div className="rounded-2xl border border-violet-200/60 dark:border-violet-900/40 bg-violet-50/40 dark:bg-violet-900/10 p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <p className="text-[11px] font-bold text-violet-700 dark:text-violet-300">
          🗂️ پرونده تصمیم‌یار سهم — پنج بخش فقط از شواهد نسخه‌دار همین snapshot
        </p>
      </div>
      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1">
        این پرونده ابزار بررسی و مقایسه است؛ هیچ توصیهٔ خرید/فروش، هدف قیمتی یا امتیاز نهایی
        از ۱۰۰ نیست و «ارزندگی» هرگز از پایین‌بودن یک نسبت به‌تنهایی استنباط نمی‌شود.
      </p>

      {/* بخش ۵ — جمع‌بندی توضیح‌پذیر */}
      <div className="grid md:grid-cols-3 gap-2 mt-2.5">
        <DossierSummaryCard
          title="۱) چرا ارزش بررسی بیشتر دارد؟"
          tone="text-emerald-700 dark:text-emerald-300"
          items={sum.why_review ?? []}
          empty="دلیل ثبت‌شده‌ای در شواهد نیست."
        />
        <DossierSummaryCard
          title="۲) مهم‌ترین ریسک یا ابهام؟"
          tone="text-amber-700 dark:text-amber-300"
          items={sum.main_risk ?? []}
          empty="هیچ هشدار ثبت‌شده‌ای نیست — «بی‌هشدار» یعنی «بی‌ریسک» نیست."
        />
        <DossierSummaryCard
          title="۳) چه شواهدی هنوز لازم است؟"
          tone="text-sky-700 dark:text-sky-300"
          items={sum.needed_evidence ?? []}
          empty="اقدام بازدارنده‌ای ثبت نشده؛ پایش گزارش‌های بعدی کافی است."
        />
      </div>

      {/* بخش ۱ — کیفیت بنیادی */}
      <div className="mt-3 grid md:grid-cols-2 gap-2">
        <div className="rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
          <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200 mb-1">
            ۱. کیفیت بنیادی (Q) — عوامل مثبت و منفی واقعی
          </p>
          {(q.strengths ?? []).length > 0 && (
            <ul className="space-y-0.5 mb-1.5">
              {(q.strengths ?? []).map((r: any) => (
                <li key={r.factor} className="text-[10px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
                  <span className="text-emerald-600 dark:text-emerald-400 font-semibold">＋</span>{" "}
                  {r.fa} — صدک {(r.score * 100).toFixed(0)}٪ خانواده · {Number(r.contribution).toFixed(1)} امتیاز از {r.weight}
                  {(r.warnings ?? []).length > 0 && (
                    <span className="text-amber-600/90 dark:text-amber-400/80"> ⚠ {r.warnings[0]}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {(q.weaknesses ?? []).length > 0 && (
            <ul className="space-y-0.5">
              {(q.weaknesses ?? []).map((r: any) => (
                <li key={r.factor} className="text-[10px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
                  <span className="text-red-500 font-semibold">−</span>{" "}
                  {r.fa} — صدک {(r.score * 100).toFixed(0)}٪ خانواده · {Number(r.contribution).toFixed(1)} امتیاز از {r.weight}
                </li>
              ))}
            </ul>
          )}
          {(q.excluded_diagnostic ?? []).length > 0 && (
            <details className="mt-1.5">
              <summary className="cursor-pointer text-[10px] text-gray-500 dark:text-gray-400 select-none">
                فاکتورهای تشخیصی/غیرفعال ({(q.excluded_diagnostic ?? []).length}) — هرگز به‌عنوان عامل اثبات‌شده معرفی نمی‌شوند
              </summary>
              <ul className="list-disc pr-4 mt-1 space-y-0.5">
                {(q.excluded_diagnostic ?? []).map((x: any) => (
                  <li key={x.factor} className="text-[10px] text-gray-500 dark:text-gray-400" dir="auto">
                    {x.fa}: {x.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5">
            پوشش وزنی Q: {Number(q.coverage?.covered_weight ?? 0).toFixed(1)} از ۴۰
            {(q.coverage?.missing_weight ?? 0) > 0 &&
              ` · مفقود: ${Number(q.coverage.missing_weight).toFixed(1)} (هیچ وزن مفقودی بازتوزیع نشده)`}
            {" · "}
            {q.evidence_note}
          </p>
        </div>

        {/* بخش ۲ — ارزندگی */}
        <div className="rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
          <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200 mb-1">
            ۲. ارزندگی (V) — نسبت‌های معتبر در برابر هم‌صنعت/هم‌خانواده
          </p>
          <table className="w-full text-[10px]">
            <thead>
              <tr className="text-gray-500 dark:text-gray-400 text-right">
                <th className="font-semibold px-1 py-0.5">نسبت</th>
                <th className="font-semibold px-1 py-0.5">مقدار</th>
                <th className="font-semibold px-1 py-0.5">جایگاه در همتا</th>
                <th className="font-semibold px-1 py-0.5">قابلیت اتکا</th>
              </tr>
            </thead>
            <tbody>
              {(v.ratios ?? []).map((r: any) => (
                <tr key={r.name} className="border-t border-gray-100/70 dark:border-gray-700/30">
                  <td className="px-1 py-1 text-gray-700 dark:text-gray-200 whitespace-nowrap">{r.fa}</td>
                  <td className="px-1 py-1 tabular-nums text-gray-700 dark:text-gray-200">
                    {r.raw_value != null ? Number(r.raw_value).toFixed(2) : "—"}
                    {!r.included && <span className="text-gray-400"> (خارج از جمع)</span>}
                  </td>
                  <td className="px-1 py-1 text-gray-600 dark:text-gray-300">
                    {r.peer_rank ? `${r.peer_rank} از ${r.n_peers}` : "—"}
                  </td>
                  <td className="px-1 py-1">
                    <Chip tone={RELIABILITY_TONE[r.reliability] ?? "off"} title={(r.warnings ?? []).join("\n")}>
                      {r.reliability_fa}
                    </Chip>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <ul className="list-disc pr-4 mt-1.5 space-y-0.5">
            {(v.caveats ?? []).map((c: string, i: number) => (
              <li key={i} className="text-[9px] leading-4 text-gray-500 dark:text-gray-400" dir="auto">
                {c}
              </li>
            ))}
          </ul>
        </div>
      </div>

      {/* بخش ۳ — وضعیت بازار و ورود */}
      <div className="mt-2 rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
        <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200 mb-1">
          ۳. وضعیت بازار و ورود (T) — با زبان ساده
        </p>
        <div className="flex flex-wrap gap-1.5">
          {(m.factors ?? []).map((r: any) => (
            <Chip key={r.factor} tone={(r.score ?? 0) >= 0.55 ? "ok" : (r.score ?? 0) <= 0.45 ? "warn" : "off"}
              title={`صدک ${(r.score * 100).toFixed(0)}٪ · ${Number(r.contribution ?? 0).toFixed(1)} امتیاز از ${r.weight}${(r.warnings ?? []).length ? "\n" + r.warnings.join("\n") : ""}`}>
              {r.fa}: {r.plain ?? Number(r.raw_value ?? 0).toFixed(2)}
            </Chip>
          ))}
        </div>
        <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5" dir="auto">
          قیمت استفاده‌شده: {px.price_rial != null ? `${Number(px.price_rial).toLocaleString("fa-IR")} ریال` : "—"}
          {" · "}تاریخ قیمت: {px.trade_date ?? "—"}
          {px.market_cap_rial != null && ` · ارزش بازار: ${fmtRial(px.market_cap_rial)} ریال`}
          {" · "}منبع سهام: <span dir="ltr">{px.share_source ?? "—"}</span>
        </p>
        <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-0.5" dir="auto">
          {px.note} — {m.adjustment_status}
        </p>
      </div>

      {/* بخش ۴ — شواهد و ریسک */}
      <div className="mt-2 rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2.5">
        <p className="text-[10px] font-bold text-gray-700 dark:text-gray-200 mb-1">
          ۴. شواهد و ریسک — بدون تغییر قراردادهای قبلی
        </p>
        <div className="flex flex-wrap items-center gap-1.5">
          <Chip tone={VAL_STATUS_TONE[ev.independent_validation?.status] ?? "off"}
            title={ev.independent_validation?.status_definition}>
            اعتبارسنجی مستقل: {ev.independent_validation?.status_label}
          </Chip>
          {(ev.effective_dates?.winner_publish_at) && (
            <Chip tone="off">
              گزارش مؤثر: پایان دورهٔ {ev.effective_dates.winner_period_end} · انتشار{" "}
              {String(ev.effective_dates.winner_publish_at).slice(0, 10)}
              {ev.effective_dates.winner_tracing_no ? ` · TracingNo ${ev.effective_dates.winner_tracing_no}` : ""}
            </Chip>
          )}
          {(ev.effective_dates?.price_trade_date) && (
            <Chip tone="off">تاریخ قیمت: {ev.effective_dates.price_trade_date}</Chip>
          )}
          {(ev.risk_gate?.financial_warnings ?? []).length > 0 && (
            <Chip tone="warn" title={(ev.risk_gate?.financial_warnings ?? []).join("\n")}>
              {ev.risk_gate.financial_warnings.length} هشدار مالی ثبت‌شده
            </Chip>
          )}
        </div>
        {(ev.capital_events ?? []).map((ce: any, i: number) => (
          <div key={i} className="mt-1.5 rounded-lg bg-amber-50/80 dark:bg-amber-900/20 ring-1 ring-amber-300/50 dark:ring-amber-800/40 px-2 py-1.5">
            <p className="text-[10px] font-bold text-amber-700 dark:text-amber-300" dir="auto">
              ⚠ رویداد سرمایه (تعیین‌شده): {ce.outcome}
            </p>
            <p className="text-[10px] text-gray-600 dark:text-gray-300 leading-4 mt-0.5" dir="auto">
              حق‌تقدم با ex-date {ce.ex_date} — از {Number(ce.old_shares).toLocaleString("fa-IR")} به{" "}
              {Number(ce.new_shares).toLocaleString("fa-IR")} سهم
              {(ce.funding_tags ?? []).length > 0 && ` (${(ce.funding_tags ?? []).join(" + ")})`}
              {ce.codal_reference && ` · ارجاع کدال: ${ce.codal_reference}`}
              {" · "}فاصلهٔ پایهٔ ضمنی EPS با سرمایهٔ ثبت‌شده:{" "}
              {(Number(ce.implied_vs_recorded_rel_diff) * 100).toFixed(3)}٪ (گردشدن EPS)
            </p>
            {(ce.ratio_classification as Record<string, string> | undefined) && (
              <p className="text-[10px] text-gray-600 dark:text-gray-300 leading-4 mt-0.5" dir="auto">
                اثر رویداد روی نسبت‌ها (کنترل ۲-ک-۴): {ce.ratio_classification.pe} ·{" "}
                {ce.ratio_classification.ps} · {ce.ratio_classification.pb}
              </p>
            )}
            <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-0.5" dir="auto">
              {ce.caveat}
            </p>
          </div>
        ))}
        <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5">
          Data Confidence و Risk Gate همان قرارداد قبلی‌اند و حق تغییر امتیاز یا لایهٔ پارتو ندارند؛
          این پرونده فقط شواهد را کنار هم می‌گذارد.
        </p>
      </div>
    </div>
  );
};


// IndependentValidationSection (۲-ک-۲): وضعیت ۴گانهٔ مستقل از امتیازها برای
// هر نامزد — با شواهد ردیفی (ردیابی سلول Q تا TracingNo/تاریخ انتشار،
// بازتولید مستقل P/E و P/S و P/B، کنترل تغییر سرمایه و پوشش رویدادها).
// مرز مهم: این وضعیت کیفیت شواهد است، نه تأیید قطعی صحت اقتصادی،
// مناسب‌بودن سرمایه‌گذاری یا مجوز ورود — و verified_from_source هم معنای
// «تأیید کامل منشأ خارجی» ندارد.
const IndependentValidationSection: React.FC<{ iv: any | null }> = ({ iv }) => {
  if (!iv || !iv.status) return null;
  const checks = iv.checks ?? {};
  const trace: any[] = Array.isArray(checks.q_cell_trace) ? checks.q_cell_trace : [];
  const cmp = checks.independent_valuation?.compare ?? {};
  const mkt = checks.independent_market ?? {};
  const eps = checks.eps_cross_check ?? null;
  const cov = checks.event_coverage ?? {};
  const tcmp = checks.t_probe?.compare ?? {};
  const ratioPct = (a: any, b: any) => {
    const x = Number(a), y = Number(b);
    if (!Number.isFinite(x) || !Number.isFinite(y) || y === 0) return null;
    const d = Math.abs(x - y) / Math.max(Math.abs(x), Math.abs(y));
    return d <= 1e-6 ? null : d;
  };
  return (
    <div className="mt-2 rounded-xl bg-white/60 dark:bg-gray-900/30 ring-1 ring-violet-200/60 dark:ring-violet-800/40 px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-bold text-violet-700 dark:text-violet-300">
          اعتبارسنجی اقتصادی مستقل
        </span>
        <Chip
          tone={VAL_STATUS_TONE[iv.status] ?? "off"}
          title={iv.status_definition}
        >
          {iv.status_label ?? VAL_STATUS_FA[iv.status] ?? iv.status}
        </Chip>
        {(mkt.share_source || mkt.price != null) && (
          <Chip tone="off"
            title="بازتولید مستقل از market.price_observations و منابع سهام — بدون فراخوانی توابع valuation موتور">
            بازار مستقل: {fmtRial(mkt.price)} × {mkt.shares != null ? Number(mkt.shares).toLocaleString("en-US") : "—"}
            {mkt.share_source ? ` (${mkt.share_source})` : ""}
          </Chip>
        )}
        {cov.snapshot_history && (
          <Chip
            tone={cov.steps_without_events > 0 ? "warn" : "off"}
            title="تغییرات تعداد سهام قابل‌مشاهده در اسنپ‌شات‌ها؛ نبود رویداد ثبت‌شده اثبات نبود تغییر سرمایه نیست"
          >
            پوشش رویداد: {cov.share_count_steps ?? 0} گام / {cov.steps_without_events ?? 0} بدون رویداد
          </Chip>
        )}
      </div>
      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1">
        این وضعیت کیفیت شواهد است — نه تأیید قطعی صحت اقتصادی، مناسب‌بودن
        سرمایه‌گذاری یا مجوز ورود؛ «verified_from_source» هم تأیید کامل منشأ
        خارجی اطلاعات نیست.
      </p>
      {(iv.reasons ?? []).length > 0 && (
        <ul className="list-disc pr-4 text-[10px] text-amber-700/90 dark:text-amber-300/80 space-y-0.5 mt-1">
          {(iv.reasons as string[]).map((r, i) => (
            <li key={i} dir="auto">{r}</li>
          ))}
        </ul>
      )}
      {trace.length > 0 && (
        <div className="mt-1.5 overflow-x-auto">
          <table className="text-[9px] w-full" dir="rtl">
            <thead>
              <tr className="text-gray-500 dark:text-gray-400">
                <th className="text-right font-medium px-1">سلول مؤثر بر Q</th>
                <th className="text-right font-medium px-1">نسخه</th>
                <th className="text-right font-medium px-1">TracingNo</th>
                <th className="text-right font-medium px-1">تاریخ انتشار واقعی</th>
              </tr>
            </thead>
            <tbody>
              {trace.map((t, i) => (
                <tr key={i} className="border-t border-gray-200/50 dark:border-gray-700/40">
                  <td className="px-1 py-0.5">{t.cell === "winner" ? "برنده (جدیدترین)" : "سال قبل"}</td>
                  <td className="px-1 py-0.5" dir="ltr">{t.version_no ?? "—"}</td>
                  <td className="px-1 py-0.5 font-mono" dir="ltr">{t.tracing_no ?? "—"}</td>
                  <td className="px-1 py-0.5" dir="ltr">
                    {t.publish_at ? String(t.publish_at).slice(0, 10) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1 text-[10px] text-gray-600 dark:text-gray-300">
        {(["pe", "ps", "pb"] as const).map((k) => {
          const c = cmp[k];
          if (!c) return null;
          const dev = ratioPct(c.mine, c.artifact);
          return (
            <span key={k}>
              {k.toUpperCase()}: موتور {c.artifact != null ? Number(c.artifact).toFixed(2) : "—"} | مستقل {c.mine != null ? Number(c.mine).toFixed(2) : "—"}
              {dev != null ? (
                <span className="text-red-600 dark:text-red-400"> (انحراف {(dev * 100).toFixed(2)}%)</span>
              ) : (
                <span className="text-emerald-600 dark:text-emerald-400"> ✓</span>
              )}
            </span>
          );
        })}
        {eps && (
          <span>
            کنترل سرمایه (EPS↔سهام فعلی):
            {eps.flag ? (
              <span className="text-amber-700 dark:text-amber-300">
                {" "}ناهم‌خوان — نسبت {Number(eps.used_vs_implied_ratio).toFixed(2)}x
              </span>
            ) : (
              <span className="text-emerald-600 dark:text-emerald-400"> هم‌خوان ✓</span>
            )}
          </span>
        )}
        {Object.keys(tcmp).length > 0 && (
          <span>
            پروب مستقل T:{" "}
            {Object.entries(tcmp).map(([k, v]: [string, any]) => (
              <span key={k} className={v?.match ? "text-emerald-600 dark:text-emerald-400" : "text-red-600 dark:text-red-400"}>
                {k}{" "}{v?.match ? "✓" : "✗"}{" "}
              </span>
            ))}
          </span>
        )}
      </div>
    </div>
  );
};

const OverlayEvidenceSection: React.FC<{
  overlay: OverlayCompany | null;
  meta: OverlayMeta | null;
  actions: ValidationAction[];
}> = ({ overlay, meta, actions }) => {
  const pr = (overlay?.publish_recovery ?? null) as any;
  const va = (overlay?.valuation_audit ?? null) as any;
  const bound = meta?.status === "bound";
  const verifiedRows = Array.isArray(pr?.scoring_rows)
    ? pr.scoring_rows.filter(
        (r: any) => r?.resolved?.status === "verified_publication_date"
      ).length
    : 0;
  const totalRows = Array.isArray(pr?.scoring_rows) ? pr.scoring_rows.length : 0;
  const dates = Array.isArray(pr?.scoring_rows)
    ? pr.scoring_rows
        .filter((r: any) => r?.resolved?.publish_at)
        .map((r: any) => String(r.resolved.publish_at).slice(0, 10))
    : [];
  const uniqueDates = Array.from(new Set(dates)).slice(0, 3);
  return (
    <div className="mt-2 rounded-xl bg-white/60 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 px-2 py-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[10px] font-bold text-gray-600 dark:text-gray-300">
          ممیزی مستقل provenance_v1
        </span>
        <Chip
          tone={bound ? "ok" : "off"}
          title={meta?.note}
        >
          {bound ? "متصل به همین snapshot" : "بدون overlay متصل — ادغام نمی‌شود"}
        </Chip>
        {pr && (
          <Chip tone={verifiedRows === totalRows && totalRows > 0 ? "ok" : "warn"}
            title={`تاریخ انتشار بازیابی‌شده برای ردیف‌های امتیازساز (publish_recovery)`}>
            تاریخ انتشار بازیابی‌شده: {verifiedRows}/{totalRows} ردیف
          </Chip>
        )}
        {va && va.verdict_label && (
          <Chip tone={String(va.verdict).startsWith("MATCH") ? "ok" : "warn"}
            title={`ممیزی سهام/ارزندگی: ${va.verdict_label}`}>
            سازگاری سهام↔قیمت: {String(va.verdict_label).slice(0, 44)}
            {String(va.verdict_label).length > 44 ? "…" : ""}
          </Chip>
        )}
        {uniqueDates.length > 0 && (
          <span className="text-[9px] text-gray-500 dark:text-gray-400" dir="ltr">
            {uniqueDates.join(" · ")}
          </span>
        )}
      </div>
      {pr && typeof pr.q_origin_before === "string" && typeof pr.q_origin_after === "string" && (
        <p className="text-[10px] text-gray-600 dark:text-gray-300 mt-1" dir="auto">
          منشأ مالی Q: {pr.q_origin_before} ← {pr.q_origin_after}
          {pr.codal_symbol ? ` (نماد کدال: ${pr.codal_symbol})` : ""}
        </p>
      )}
      {actions.length > 0 && (
        <div className="mt-1.5">
          <p className="text-[10px] font-bold text-amber-700 dark:text-amber-300">
            اقدامات لازم برای اعتبارسنجی (هیچ‌کدام خودکار اجرا نمی‌شود)
          </p>
          <ul className="list-disc pr-4 text-[10px] text-gray-600 dark:text-gray-300 space-y-0.5 mt-0.5">
            {actions.map((a, i) => (
              <li key={i} dir="auto">
                <span className="font-mono text-[9px] text-amber-700/90 dark:text-amber-300/80">
                  {a.priority}
                </span>{" "}
                <span className="font-semibold">{a.title}</span> — {a.detail}
              </li>
            ))}
          </ul>
        </div>
      )}
      {meta?.files && meta.files.length > 0 && (
        <p className="text-[9px] text-gray-500 dark:text-gray-400 mt-1" dir="ltr">
          {meta.files.join(" · ")}
        </p>
      )}
    </div>
  );
};

const EvidenceSourcesBlock: React.FC<{
  chain: QvtEvidenceChain;
  integrity?: QvtBundleIntegrity | null;
  overlay?: OverlayCompany | null;
  overlayMeta?: OverlayMeta | null;
  actions?: ValidationAction[];
}> = ({ chain, integrity, overlay, overlayMeta, actions }) => {
  const evItemView = (it: QvtEvidenceItem) => (
    <li key={it.key} className="leading-4">
      <span className="inline-flex items-center gap-1.5 flex-wrap">
        <span className="font-semibold text-gray-700 dark:text-gray-200">{it.label}</span>
        <Chip tone={EV_STATUS_TONE[it.status] ?? "off"} title={it.status_label}>
          {it.status_label}
          {!it.checked && " — کنترل ممکن نشد"}
        </Chip>
      </span>
      {it.summary && (
        <p className="text-[10px] text-gray-600 dark:text-gray-300 mt-0.5" dir="auto">
          {it.summary}
        </p>
      )}
      {(it.fields?.length ?? 0) > 0 && (
        <div className="mt-1 rounded-lg bg-white/60 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 px-2 py-1">
          {it.fields!.map((f, i) => (
            <p key={i} className="text-[10px] text-gray-600 dark:text-gray-300 leading-4" dir="auto">
              <span className="text-gray-500 dark:text-gray-400">{f.k}: </span>
              {f.v}
            </p>
          ))}
        </div>
      )}
      {(it.limitations?.length ?? 0) > 0 && (
        <ul className="list-disc pr-4 text-[10px] text-amber-700/90 dark:text-amber-300/80 space-y-0.5 mt-1">
          {it.limitations!.map((l, i) => (
            <li key={i} dir="auto">{l}</li>
          ))}
        </ul>
      )}
      {(it.conflicts?.length ?? 0) > 0 && (
        <ul className="list-disc pr-4 text-[10px] text-red-600 dark:text-red-400 space-y-0.5 mt-1">
          {it.conflicts!.map((c, i) => (
            <li key={i} dir="auto">{c}</li>
          ))}
        </ul>
      )}
    </li>
  );

  return (
    <div className="rounded-2xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/40 dark:bg-sky-900/10 p-3">
      <p className="text-[11px] font-bold text-sky-700 dark:text-sky-300 mb-0.5">
        اعتبار منابع محاسبه — ردیابی فقط‌خواندنی ورودی‌های Q/V/T
      </p>
      <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
        <Chip tone={EV_STATUS_TONE[chain.overall] ?? "off"} title={chain.overall_label}>
          جمع‌بندی: {chain.overall_label}
        </Chip>
        {chain.axes.map((ax) => (
          <Chip
            key={ax.axis}
            tone={EV_STATUS_TONE[ax.status] ?? "off"}
            title={`${ax.axis_label}\n${ax.items
              .filter((i) => !i.structural)
              .map((i) => `${i.label}: ${i.status_label}`)
              .join("\n")}`}
          >
            {ax.axis}: {ax.status_label.replace(" — محدودیت مشخص", "")}
          </Chip>
        ))}
      </div>
      <p className="text-[9px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5">
        {chain.notes[0]}
      </p>

      <OverlayEvidenceSection
        overlay={overlay ?? null}
        meta={overlayMeta ?? null}
        actions={actions ?? []}
      />

      <IndependentValidationSection
        iv={(overlay as any)?.independent_validation ?? null}
      />

      <details className="mt-2 group">
        <summary className="cursor-pointer text-[10px] font-bold text-sky-700 dark:text-sky-300 select-none">
          جزئیات شواهد هر محور ({chain.axes.reduce((n, a) => n + a.items.length, 0)} کنترل)
        </summary>
        <div className="flex flex-col gap-2.5 mt-2">
          {chain.axes.map((ax) => (
            <div key={ax.axis}>
              <p className="text-[10px] font-bold text-gray-600 dark:text-gray-300">
                {ax.axis_label} — {ax.status_label}
              </p>
              <ul className="list-disc pr-4 text-[10px] text-gray-600 dark:text-gray-300 space-y-1.5 mt-1">
                {ax.items.map(evItemView)}
              </ul>
            </div>
          ))}
        </div>
      </details>

      {integrity && (
        <details className="mt-1.5">
          <summary className="cursor-pointer text-[10px] font-bold text-sky-700 dark:text-sky-300 select-none">
            یکپارچگی snapshot سه آرتیفکت
          </summary>
          <div className="text-[10px] text-gray-600 dark:text-gray-300 space-y-1 mt-1.5" dir="auto">
            <p>
              پیوند زنجیره Q→V→T (پوینترهای upstream):{" "}
              <Chip tone={EV_STATUS_TONE[integrity.chain_linkage.status] ?? "off"}>
                {integrity.chain_linkage.status_label}
              </Chip>
            </p>
            <p>
              هش فایل‌ها (sha256):{" "}
              <span dir="ltr" className="font-mono text-[9px]">
                Q {integrity.artifact_files.q.sha256.slice(0, 12)} · V{" "}
                {integrity.artifact_files.v.sha256.slice(0, 12)} · T{" "}
                {integrity.artifact_files.t.sha256.slice(0, 12)}
              </span>
            </p>
            <p className="text-gray-500 dark:text-gray-400">
              {integrity.run_identity.limitation}
            </p>
            <p className="text-gray-500 dark:text-gray-400">
              انتشار در نویسنده: {integrity.publication_atomicity.writer}
            </p>
            <p className="text-gray-500 dark:text-gray-400">
              محافظ خواننده: {integrity.publication_atomicity.reader_mitigation}
            </p>
            <p className="text-gray-500 dark:text-gray-400">
              طرح اصلاح حداقلی: {integrity.run_identity.fix_plan}
            </p>
          </div>
        </details>
      )}
    </div>
  );
};

const DetailPanel: React.FC<{
  companyId: string;
  symbol: string;
  candidate?: QvtShortlistEntry | null;
  onClose: () => void;
}> = ({ companyId, symbol, candidate, onClose }) => {  const [detail, setDetail] = useState<QvtDetail | null>(null);
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
            <p className="text-[11px] text-gray-500 dark:text-gray-400 mt-0.5">
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
        <p className="text-sm text-gray-500 dark:text-gray-400 py-6 text-center">
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
            {detail.confidence ? (
              (() => {
                const cf = detail.confidence;
                const tone =
                  cf.overall === "findings" ? "warn" : cf.overall === "not_evaluable" ? "off" : "ok";
                return <Chip tone={tone} title={cf.overall_note}>اطمینان داده: {cf.overall_label}</Chip>;
              })()
            ) : (
              <Chip tone="neutral">Data Confidence: ارزیابی نشده</Chip>
            )}
            {detail.risk_gate ? (
              (() => {
                const rg = detail.risk_gate;
                return (
                  <Chip
                    tone={RG_STATUS_TONE[rg.status] ?? "off"}
                    title={`${rg.status_label}\n\n${rg.status_note}\n\n${rg.areas
                      .map((a) => `${a.title}: ${a.status_label}`)
                      .join("\n")}`}
                  >
                    دروازه ریسک: {rg.status_label}
                  </Chip>
                );
              })()
            ) : (
              <Chip tone="neutral">Risk Gate: ارزیابی نشده</Chip>
            )}
            <Chip tone="off">snapshot {detail.as_of}</Chip>
          </div>

          {(detail.evidence_overlay as any)?.decision_dossier && (
            <DecisionDossierSection
              dd={(detail.evidence_overlay as any).decision_dossier}
            />
          )}

          {(detail.evidence_overlay as any)?.q_factor_diagnostics && (
            <DiagnosticQFactorsSection
              qd={(detail.evidence_overlay as any).q_factor_diagnostics}
              egAudit={(detail.evidence_overlay as any)?.eg_economic_audit ?? null}
            />
          )}

          {candidate && <CandidateEvidenceBlock c={candidate} />}
          {detail.evidence_chain && (
            <EvidenceSourcesBlock
              chain={detail.evidence_chain}
              integrity={detail.bundle_integrity ?? null}
              overlay={detail.evidence_overlay ?? null}
              overlayMeta={detail.evidence_overlay_meta ?? null}
              actions={detail.validation_actions ?? []}
            />
          )}
          {detail.confidence && <ConfidenceDetailBlock cf={detail.confidence} />}
          {detail.risk_gate && <RiskGateDetailBlock rg={detail.risk_gate} />}

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

// ── نمای «کشف فرصت‌ها» ───────────────────────────────────────────────────────
// چهار حالت کشف روی همان snapshot واقعی سه آرتیفکت. این خروجی فقط «کاندیدای
// بررسی بیشتر» است، نه توصیه خرید؛ ترتیب نمایش سراسری در حالت‌های تک‌محوری
// «رتبه بنیادی معتبر» بین صنایع نیست — رتبه معتبر فقط داخل گروه مقایسه‌پذیر
// (خانواده + صنعت + پوشش فاکتور یکسان) تعریف می‌شود و لایه‌های پارتو فقط
// ابزار کشف‌اند. تعدادها از داده واقعی بازشماری می‌شوند، نه hardcode.

const DISC_MODES: { id: QvtDiscoveryModeName; label: string; hint: string }[] = [
  {
    id: "balanced",
    label: "متوازن",
    hint: "برتری چندمحوری با لایه‌های پارتو — فقط داخل گروه‌های مقایسه‌پذیر با پوشش فاکتور یکسان؛ گروه کمتر از ۵ همتا رتبه‌بندی متوازن ندارد",
  },
  {
    id: "quality",
    label: "بنیادی قوی",
    hint: "اولویت نمایش با Q مشاهده‌شده بالاتر؛ V و T کنار آن نمایش داده می‌شوند",
  },
  {
    id: "value",
    label: "ارزنده‌تر",
    hint: "اولویت نمایش با V مشاهده‌شده بالاتر؛ محدودیت‌های P/E و P/B و P/S و داده مفقود پنهان نمی‌شوند",
  },
  {
    id: "timing",
    label: "ورود مناسب‌تر",
    hint: "اولویت نمایش با T مشاهده‌شده بالاتر؛ هشدارهای نقدشوندگی و داده ناکامل حفظ می‌شوند",
  },
];

type DiscSortKey = "mode" | "q" | "v" | "t";

const DISC_PAGE_SIZE = 12;

// ── مقایسه کنارهم نامزدهای هم‌گروه (۲-ک-۳ P3) ────────────────────────────────
// برای هر نمادِ انتخاب‌شده، جزئیات واقعی همان snapshot خوانده می‌شود (شامل
// پرونده تصمیم‌یار با گیت binding) و ستون‌به‌ستون نمایش داده می‌شود. هیچ
// امتیاز ترکیبی، وزن پنهان یا رتبه‌بندی بین صنایع ساخته نمی‌شود؛ اگر داده
// ناکامل باشد، همان محدودیت در ستون همان سهم دیده می‌شود.
const ShortlistComparePanel: React.FC<{
  items: { company_id: string; symbol: string; group: string }[];
  onRemove: (companyId: string) => void;
  onClear: () => void;
}> = ({ items, onRemove, onClear }) => {
  const [cols, setCols] = useState<Record<string, any>>({});
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    Promise.all(
      items.map((it) =>
        fetchQvtV2Detail(it.company_id)
          .then((d) => [it.company_id, d] as const)
          .catch((e) => [it.company_id, { __error: e?.message || "خطا" }] as const)
      )
    )
      .then((pairs) => {
        if (!alive) return;
        setCols(Object.fromEntries(pairs));
      })
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [items.map((i) => i.company_id).join(",")]);

  const cell = (cid: string, pick: (d: any) => React.ReactNode) => {
    const d = cols[cid];
    if (!d) return <span className="text-gray-300">…</span>;
    if (d.__error) return <span className="text-red-500 text-[10px]">{d.__error}</span>;
    return pick(d);
  };

  return (
    <div className="mt-2 rounded-xl border border-violet-300/60 dark:border-violet-800/50 bg-white/80 dark:bg-gray-900/40 p-2.5">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <p className="text-[11px] font-bold text-violet-700 dark:text-violet-300">
          ⚖️ مقایسه کنارهم — {items.length} نماد از «{items[0]?.group}»
        </p>
        <span className="text-[9px] text-gray-500 dark:text-gray-400">
          فقط شواهد همان گروه؛ هیچ امتیاز ترکیبی یا رتبه‌بندی بین گروه‌ها/صنایع ساخته نمی‌شود
        </span>
        <button
          onClick={onClear}
          className="ms-auto h-6 px-2 rounded-lg text-[10px] ring-1 ring-gray-300/60 dark:ring-gray-700/50 text-gray-500 dark:text-gray-400 hover:bg-gray-100/70 dark:hover:bg-gray-800/60"
        >
          پاک کردن مقایسه
        </button>
      </div>
      {loading && <p className="text-[10px] text-gray-400 mt-2">در حال بارگذاری شواهد…</p>}
      {!loading && (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-[10px] border-separate border-spacing-x-2">
            <thead>
              <tr>
                <th className="text-right text-gray-500 dark:text-gray-400 font-semibold w-28">محور مقایسه</th>
                {items.map((it) => (
                  <th key={it.company_id} className="text-right">
                    <span className="inline-flex items-center gap-1">
                      <button
                        onClick={() => onRemove(it.company_id)}
                        className="text-gray-400 hover:text-red-500"
                        title="حذف از مقایسه"
                      >
                        ✕
                      </button>
                      <b className="text-gray-800 dark:text-gray-100">{it.symbol}</b>
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              <CompareRow label="Q / V / T (از ۴۰/۳۵/۲۵)">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-700 dark:text-gray-200">
                    {cell(it.company_id, (d) => {
                      const ax = d?.company?.axes ?? {};
                      const f = (x: any) => {
                        const p = x?.q_observed_points ?? x?.v_observed_points ??
                          x?.t_observed_points ?? x?.points;
                        return p != null ? Number(p).toFixed(1) : "—";
                      };
                      return (
                        <span dir="ltr" className="tabular-nums">
                          {f(ax.q)} / {f(ax.v)} / {f(ax.t)}
                        </span>
                      );
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="قوی‌ترین فاکتور کیفیت">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-600 dark:text-gray-300">
                    {cell(it.company_id, (d) => {
                      const s = d?.evidence_overlay?.decision_dossier?.sections?.quality?.strengths?.[0];
                      return s
                        ? `${s.fa} — صدک ${(s.score * 100).toFixed(0)}٪`
                        : "—";
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="ضعیف‌ترین فاکتور کیفیت">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-600 dark:text-gray-300">
                    {cell(it.company_id, (d) => {
                      const s = d?.evidence_overlay?.decision_dossier?.sections?.quality?.weaknesses?.[0];
                      return s ? `${s.fa} — صدک ${(s.score * 100).toFixed(0)}٪` : "—";
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="P/E · P/B · P/S (جایگاه در هم‌صنعت)">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-700 dark:text-gray-200">
                    {cell(it.company_id, (d) => {
                      const rs = d?.evidence_overlay?.decision_dossier?.sections?.value?.ratios ?? [];
                      const one = (r: any) =>
                        r.raw_value != null
                          ? `${Number(r.raw_value).toFixed(1)}${r.peer_rank ? ` (#${r.peer_rank}/${r.n_peers})` : ""}`
                          : "—";
                      return (
                        <span dir="ltr" className="tabular-nums">
                          {one(rs.find((x: any) => x.name === "pe"))} ·{" "}
                          {one(rs.find((x: any) => x.name === "pb"))} ·{" "}
                          {one(rs.find((x: any) => x.name === "ps"))}
                        </span>
                      );
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="مومنتوم ۶ماههٔ نسبی">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-700 dark:text-gray-200">
                    {cell(it.company_id, (d) => {
                      const r = (d?.evidence_overlay?.decision_dossier?.sections?.market?.factors ?? []).find(
                        (x: any) => x.factor === "momentum_6m_rel"
                      );
                      return r?.plain ?? "—";
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="اعتبارسنجی مستقل / رویداد سرمایه">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-600 dark:text-gray-300">
                    {cell(it.company_id, (d) => {
                      const dd = d?.evidence_overlay?.decision_dossier;
                      const st = dd?.sections?.evidence?.independent_validation?.status;
                      const ce = dd?.sections?.evidence?.capital_events ?? [];
                      return (
                        <>
                          <Chip tone={VAL_STATUS_TONE[st] ?? "off"}>{VAL_STATUS_FA[st] ?? "ارزیابی نشده"}</Chip>
                          {ce.length > 0 && (
                            <span className="ms-1 text-amber-600/90 dark:text-amber-400/80">
                              حق‌تقدم {ce[0].ex_date} ({Number(ce[0].old_shares) / 1e9}→
                              {Number(ce[0].new_shares) / 1e9} میلیارد سهم)
                            </span>
                          )}
                        </>
                      );
                    })}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="چرا ارزش بررسی بیشتر دارد؟">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-600 dark:text-gray-300">
                    {cell(it.company_id, (d) =>
                      (d?.evidence_overlay?.decision_dossier?.sections?.summary?.why_review ?? [])
                        .slice(0, 2)
                        .map((s: string, i: number) => <p key={i} dir="auto" className="leading-4">• {s}</p>
                        )
                    )}
                  </td>
                ))}
              </CompareRow>
              <CompareRow label="مهم‌ترین ریسک/ابهام">
                {items.map((it) => (
                  <td key={it.company_id} className="align-top text-gray-600 dark:text-gray-300">
                    {cell(it.company_id, (d) =>
                      (d?.evidence_overlay?.decision_dossier?.sections?.summary?.main_risk ?? [])
                        .slice(0, 2)
                        .map((s: string, i: number) => (
                          <p key={i} dir="auto" className="leading-4">• {s}</p>
                        ))
                    )}
                  </td>
                ))}
              </CompareRow>
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};

const CompareRow: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <tr className="border-t border-gray-100/70 dark:border-gray-700/30">
    <td className="py-1.5 font-semibold text-gray-500 dark:text-gray-400 align-top">{label}</td>
    {children}
  </tr>
);

// ── فهرست کوتاه کاربردی (گام ۲-ط-۱) ──────────────────────────────────────────
// «نامزدهای اولویت‌دار برای بررسی»: فقط گروه‌های مقایسه‌پذیر معتبر حالت
// متوازن، به تفکیک صنعتِ واقعی از داده (اگر در snapshot بعدی گروه‌ها عوض
// شوند همین بخش با داده جدید پر می‌شود — هیچ نام گروهی hardcode نیست).
// اعضای لایه ۱ پارتو ابتدا نمایش داده می‌شوند؛ مرتب‌سازی بر اساس Q/V/T فقط
// داخل همان گروه مجاز است؛ لایه ۱ نه سیگنال خرید است و نه «بهترین سهم
// بازار»؛ تاریخ قیمت استفاده‌شده از کنترل مستقل منبع قیمت می‌آید.

const SEV_RANK: Record<string, number> = {
  proven_policy_violation: 0,
  proven_data_error: 1,
  suspected_data_issue: 2,
  consistency_review: 3,
  economic_risk: 4,
  valuation_band: 5,
  market_structure: 6,
  provenance_note: 7,
  unknown: 8,
};

// سلول «تاریخ قیمت استفاده‌شده و تازگی آن» — فقط از کنترل مستقل واقعی؛
// اگر منبع در دسترس نباشد صریح گفته می‌شود و هیچ عددی جایگزین نمی‌شود.
const PriceFreshnessCell: React.FC<{ pf: QvtPriceFreshness | null }> = ({ pf }) => {
  if (!pf) return <span className="text-[10px] text-gray-500 dark:text-gray-400">—</span>;
  if (!pf.available)
    return (
      <span
        className="block text-[10px] leading-4 text-gray-500 dark:text-gray-400"
        title={pf.note}
      >
        کنترل مستقل تازگی ممکن نشد
      </span>
    );
  if (!pf.row_found)
    return (
      <span
        className="block text-[10px] leading-4 text-gray-500 dark:text-gray-400"
        title={pf.note}
      >
        ردیف قیمتی در منبع یافت نشد
      </span>
    );
  const viol = pf.violation === true;
  return (
    <div className="flex flex-col items-start gap-0.5">
      <span className="text-[10px] tabular-nums text-gray-600 dark:text-gray-300" dir="ltr">
        {pf.last_trade_date}
      </span>
      <span className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
        {pf.age_days} روز قبل از snapshot
      </span>
      <Chip
        tone={viol ? "danger" : "ok"}
        title={`${pf.note}\nمنبع: ${pf.source}\nپنجره PIT: ${pf.window_rule}\nسیاست: ${pf.policy_days} روز (${pf.policy_basis})`}
      >
        {viol
          ? `نقض سیاست ${pf.policy_days} روز — مانع B1`
          : `در محدوده سیاست ${pf.policy_days} روز`}
      </Chip>
    </div>
  );
};

const PriorityCandidatesSection: React.FC<{
  shortlist: QvtShortlist;
  priceSource: QvtPriceSourceMeta;
  onOpenDetail: (
    companyId: string,
    symbol: string,
    candidate: QvtShortlistEntry | null
  ) => void;
}> = ({ shortlist, priceSource, onOpenDetail }) => {
  // مرتب‌سازی دلخواه هر گروه مستقل است: «پیش‌فرض» = لایه ۱ پارتو ابتدا؛
  // Q/V/T = امتیاز مشاهده‌شده نزولی فقط بین همان اعضای گروه — مقایسه‌ای
  // بین گروه‌ها یا صنایع مختلف هرگز انجام نمی‌شود.
  const [sorts, setSorts] = useState<Record<string, "default" | "q" | "v" | "t">>({});
  // فیلتر کفایت شواهد (۲-ک-۲) — مستقل از امتیازها؛ «بررسی‌نشده» یعنی
  // وضعیت هنوز ارزیابی نشده و در فیلتر «نیازمند بررسی» نمی‌آید
  const [valFilter, setValFilter] = useState<"all" | "checked" | "review" | "unevaluated">("all");
  const filteredEntries = (entries: QvtShortlistEntry[]) => {
    if (valFilter === "all") return entries;
    return entries.filter((e) => {
      if (valFilter === "checked") return e.validation_status === "independently_checked";
      if (valFilter === "review") return e.validation_needs_review === true;
      return !e.validation_status; // unevaluated
    });
  };
  const nChecked = shortlist.groups.reduce(
    (a, g) => a + g.entries.filter((e) => e.validation_status === "independently_checked").length, 0);
  const nReview = shortlist.groups.reduce(
    (a, g) => a + g.entries.filter((e) => e.validation_needs_review).length, 0);
  const nUnev = shortlist.groups.reduce(
    (a, g) => a + g.entries.filter((e) => !e.validation_status).length, 0);
  // مقایسه درون‌گروهی (۲-ک-۳ P3): حداکثر ۳ نماد از «یک» گروه مقایسه‌پذیر
  // کنار هم — هیچ امتیاز ترکیبی یا وزن پنهانی ساخته نمی‌شود؛ فقط شواهد هر
  // سهم از پرونده تصمیم‌یار و همان اعضای همان گروه نمایش داده می‌شود.
  const [compareIds, setCompareIds] = useState<
    { company_id: string; symbol: string; group: string }[]
  >([]);
  const toggleCompare = (e: QvtShortlistEntry) => {
    setCompareIds((prev) => {
      const exists = prev.find((x) => x.company_id === e.company_id);
      if (exists) return prev.filter((x) => x.company_id !== e.company_id);
      if (prev.length >= 3) return prev;
      if (prev.length > 0 && prev[0].group !== e.group_label) return prev; // فقط همان گروه
      return [...prev, { company_id: e.company_id, symbol: e.symbol, group: e.group_label }];
    });
  };
  const compareGroup = compareIds.length > 0 ? compareIds[0].group : null;
  const sortedEntries = (label: string, entries: QvtShortlistEntry[]) => {
    const s = sorts[label] ?? "default";
    if (s === "default") return entries;
    const out = [...entries];
    out.sort((a, b) => {
      const pa = a[s].points;
      const pb = b[s].points;
      if (pa != null && pb != null && pa !== pb) return pb - pa;
      if (pa != null && pb == null) return -1;
      if (pa == null && pb != null) return 1;
      return a.symbol < b.symbol ? -1 : 1;
    });
    return out;
  };
  // مهم‌ترین هشدارهای هر نامزد: blockers سپس یافته‌های بررسی، به ترتیب شدت
  const topFindings = (e: QvtShortlistEntry): QvtRiskFinding[] => {
    const all = [
      ...(e.risk_gate?.blockers ?? []),
      ...(e.risk_gate?.review_findings ?? []),
    ];
    return all
      .sort((a, b) => (SEV_RANK[a.severity] ?? 9) - (SEV_RANK[b.severity] ?? 9))
      .slice(0, 2);
  };
  if (shortlist.counts.companies === 0) return null;
  return (
    <div className="rounded-2xl border border-emerald-200/60 dark:border-emerald-900/40 bg-emerald-50/40 dark:bg-emerald-900/10 p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-xs font-bold text-emerald-700 dark:text-emerald-300">
          ⭐ {shortlist.title}: {shortlist.counts.companies} شرکت در{" "}
          {shortlist.counts.groups} گروه مقایسه‌پذیر
        </h3>
        <span className="text-[10px] text-gray-500 dark:text-gray-400 leading-4">
          {shortlist.basis}
        </span>
      </div>
      <p className="text-[10px] text-amber-600/90 dark:text-amber-400/80 leading-4 mt-1">
        {shortlist.not_a_signal}
      </p>
      {/* فیلتر کفایت شواهد (۲-ک-۲) — مستقل از امتیازها؛ برای انتخاب سریع‌تر
          نامزدهای دارای شواهد قابل‌اتکا برای تحلیل عمیق */}
      <div className="flex flex-wrap items-center gap-1.5 mt-1.5">
        <span className="text-[10px] font-bold text-gray-600 dark:text-gray-300">
          کفایت شواهد:
        </span>
        {([
          ["all", `همه (${shortlist.counts.companies})`, "بدون فیلتر"],
          ["checked", `بررسی مستقل کامل (${nChecked})`, "فقط نامزدهایی که همه اجزای مؤثرشان با پیاده‌سازی مستقل بازتولید و به گزارش/تاریخ انتشار متصل شده است"],
          ["review", `نیازمند بررسی (${nReview})`, "سازگار اما غیرمستقل / شواهد ناکافی / تعارض — حداقل یک حلقه اثبات‌نشده دارند"],
          ["unevaluated", `بررسی‌نشده (${nUnev})`, "هنوز در ممیزی مستقل ارزیابی نشده‌اند — ارزیابی‌نشده هرگز معنای تأییدشده ندارد"],
        ] as const).map(([k, label, tip]) => (
          <button
            key={k}
            onClick={() => setValFilter(k as typeof valFilter)}
            className={`rounded-lg px-2 py-0.5 text-[10px] ring-1 transition-colors ${
              valFilter === k
                ? "bg-violet-500/15 text-violet-700 dark:text-violet-300 ring-violet-500/30 font-bold"
                : "bg-white/60 dark:bg-gray-900/30 text-gray-500 dark:text-gray-400 ring-gray-200/60 dark:ring-gray-700/40 hover:bg-violet-500/5"
            }`}
            title={tip}
          >
            {label}
          </button>
        ))}
      </div>
      <p
        className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-1"
        title={`${priceSource.source}\nپنجره PIT: ${priceSource.window_rule}\nسیاست: ${priceSource.policy_source}\n${priceSource.read_only}`}
      >
        تاریخ قیمت استفاده‌شده هر نامزد از کنترل مستقل{" "}
        <b>{priceSource.available ? "منبع واقعی" : "منبعی که در دسترس نیست"}</b> می‌آید
        {priceSource.note ? ` — ${priceSource.note}` : ""} · شرکت‌های فاقد رتبه متوازن (
        {shortlist.non_ranked.n} شرکت): {shortlist.non_ranked.note}
      </p>

      {/* مقایسه کنارهم (۲-ک-۳ P3) — فقط داخل یک گروه، بدون امتیاز ترکیبی */}
      {compareIds.length > 0 && (
        <ShortlistComparePanel
          items={compareIds}
          onRemove={(cid) => setCompareIds((p) => p.filter((x) => x.company_id !== cid))}
          onClear={() => setCompareIds([])}
        />
      )}
      {compareIds.length > 0 && compareIds.length < 2 && (
        <p className="text-[10px] text-violet-600/90 dark:text-violet-300/80 mt-1">
          برای مقایسه کنار هم، {2 - compareIds.length} نماد دیگر از همین گروه را انتخاب کنید (حداکثر ۳).
        </p>
      )}

      {shortlist.groups.map((g) => {
        const shown = filteredEntries(g.entries);
        if (shown.length === 0 && valFilter !== "all") return null;
        return (
        <div
          key={g.group_label}
          className="mt-3 rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-white/70 dark:bg-gray-800/40 overflow-hidden"
        >
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 pt-2">
            <b className="text-[11px] text-gray-700 dark:text-gray-200">{g.group_label}</b>
            <span className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
              {shown.length} نامزد{valFilter !== "all" ? ` از ${g.entries.length}` : ""} · {g.group_size} همتای مقایسه‌پذیر
            </span>
            <select
              value={sorts[g.group_label] ?? "default"}
              onChange={(ev) =>
                setSorts((p) => ({ ...p, [g.group_label]: ev.target.value as "default" | "q" | "v" | "t" }))
              }
              className="h-7 rounded-lg border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/60 px-2 text-[10px] text-gray-600 dark:text-gray-300 focus:outline-none"
              title="مرتب‌سازی فقط داخل همین گروه مقایسه‌پذیر — هیچ مقایسه بین گروه‌ها یا صنایع انجام نمی‌شود"
            >
              <option value="default">ترتیب: لایه ۱ پارتو ابتدا</option>
              <option value="q">مرتب‌سازی بر اساس Q (نزولی)</option>
              <option value="v">مرتب‌سازی بر اساس V (نزولی)</option>
              <option value="t">مرتب‌سازی بر اساس T (نزولی)</option>
            </select>
          </div>
          <div className="mt-1.5 overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-100/95 dark:bg-gray-800/95 text-[10px] text-gray-500 dark:text-gray-400">
                <tr className="text-right">
                  <th className="px-2 py-1.5 font-semibold" title="انتخاب حداکثر ۳ نماد از همین گروه برای مقایسه کنارهم">
                    مقایسه / نماد / لایه پارتو
                  </th>
                  <th className="px-2 py-1.5 font-semibold">Q / پوشش از ۴۰</th>
                  <th className="px-2 py-1.5 font-semibold">V / پوشش از ۳۵</th>
                  <th className="px-2 py-1.5 font-semibold">T / پوشش از ۲۵</th>
                  <th className="px-2 py-1.5 font-semibold">تاریخ قیمت و تازگی</th>
                  <th className="px-2 py-1.5 font-semibold">اطمینان داده</th>
                  <th className="px-2 py-1.5 font-semibold">دروازه ریسک</th>
                  <th className="px-2 py-1.5 font-semibold">مهم‌ترین هشدارها</th>
                  <th className="px-2 py-1.5 font-semibold">دلیل لایه</th>
                  <th className="px-2 py-1.5 font-semibold"></th>
                </tr>
              </thead>
              <tbody>
                {sortedEntries(g.group_label, shown).map((e) => (
                  <tr
                    key={e.company_id}
                    className="border-t border-gray-100/80 dark:border-gray-700/40 align-top"
                  >
                    <td className="px-2 py-1.5 whitespace-nowrap">
                      <label
                        className="inline-flex items-center gap-1 cursor-pointer"
                        title={
                          compareGroup && compareGroup !== g.group_label
                            ? "انتخاب فقط داخل یک گروه مقایسه‌پذیر مجاز است — ابتدا انتخاب‌های گروه دیگر را پاک کنید"
                            : compareIds.length >= 3 &&
                                !compareIds.find((x) => x.company_id === e.company_id)
                              ? "حداکثر ۳ نماد در هر مقایسه"
                              : "افزودن به مقایسه کنارهم (فقط همین گروه)"
                        }
                      >
                        <input
                          type="checkbox"
                          className="accent-violet-600 w-3.5 h-3.5"
                          checked={!!compareIds.find((x) => x.company_id === e.company_id)}
                          disabled={
                            (compareGroup != null && compareGroup !== g.group_label) ||
                            (compareIds.length >= 3 &&
                              !compareIds.find((x) => x.company_id === e.company_id))
                          }
                          onChange={() => toggleCompare(e)}
                        />
                      </label>
                      <span className="font-bold text-gray-800 dark:text-gray-100 mr-1">{e.symbol}</span>
                      <span
                        className={`ms-1 inline-block rounded-md px-1.5 py-0.5 text-[9px] font-bold ring-1 ${
                          e.pareto_layer === 1
                            ? "bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-sky-500/25"
                            : "bg-gray-500/10 text-gray-500 dark:text-gray-400 ring-gray-500/20"
                        }`}
                        title={
                          e.pareto_layer === 1
                            ? "لایه ۱: هیچ همتای گروهی در هیچ‌یک از سه محور بر آن غالب نیست — نه سیگنال خرید"
                            : `لایه ${e.pareto_layer}: برخی همتایان گروه بر آن غالبند`
                        }
                      >
                        لایه {e.pareto_layer}
                      </span>
                      {e.validation_status && (
                        <span
                          className={`ms-1 inline-block rounded-md px-1.5 py-0.5 text-[9px] font-bold ring-1 ${
                            e.validation_status === "independently_checked"
                              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/25"
                              : e.validation_status === "conflicting"
                              ? "bg-red-500/10 text-red-700 dark:text-red-300 ring-red-500/25"
                              : e.validation_needs_review
                              ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-amber-500/25"
                              : "bg-gray-500/10 text-gray-500 dark:text-gray-400 ring-gray-500/20"
                          }`}
                          title={`${e.validation_status_label}\nمستقل از امتیازها و Risk Gate\n${e.validation_reason ?? ""}`}
                        >
                          شواهد: {e.validation_status_label}
                        </span>
                      )}
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300 whitespace-nowrap">
                      {e.q.points == null ? "—" : fmt(e.q.points, 1)}
                      <span className="text-[9px] text-gray-500 dark:text-gray-400">
                        {" "}
                        ({fmtPct(e.q.coverage_ratio, 0)})
                      </span>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300 whitespace-nowrap">
                      {e.v.points == null ? "—" : fmt(e.v.points, 1)}
                      <span className="text-[9px] text-gray-500 dark:text-gray-400">
                        {" "}
                        ({fmtPct(e.v.coverage_ratio, 0)})
                      </span>
                    </td>
                    <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300 whitespace-nowrap">
                      {e.t.points == null ? "—" : fmt(e.t.points, 1)}
                      <span className="text-[9px] text-gray-500 dark:text-gray-400">
                        {" "}
                        ({fmtPct(e.t.coverage_ratio, 0)})
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <PriceFreshnessCell pf={e.price_freshness} />
                    </td>
                    <td className="px-2 py-1.5">
                      {e.confidence ? <ConfidenceBadge cf={e.confidence} /> : "—"}
                    </td>
                    <td className="px-2 py-1.5">
                      {e.risk_gate ? <RiskGateBadge rg={e.risk_gate} /> : "—"}
                    </td>
                    <td className="px-2 py-1.5 max-w-[220px]">
                      {topFindings(e).length === 0 ? (
                        <span className="text-[10px] text-gray-500 dark:text-gray-400" title="به معنی نبود ریسک یا تأیید کامل نیست">
                          بدون یافته ثبت‌شده
                        </span>
                      ) : (
                        <div className="flex flex-col gap-1">
                          {topFindings(e).map((f, i) => (
                            <Chip
                              key={i}
                              tone={SEV_TONE[f.severity] ?? "neutral"}
                              title={`${f.severity_label}\n${f.reason}\n${(f.evidence ?? []).join("\n")}`}
                            >
                              {f.category}
                            </Chip>
                          ))}
                        </div>
                      )}
                    </td>
                    <td className="px-2 py-1.5 max-w-[260px]">
                      <span className="block text-[10px] leading-4 text-gray-500 dark:text-gray-400" title={e.reason}>
                        {e.reason}
                      </span>
                    </td>
                    <td className="px-2 py-1.5">
                      <button
                        onClick={() => onOpenDetail(e.company_id, e.symbol, e)}
                        className="h-6 px-2 rounded-lg text-[10px] font-bold bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-1 ring-sky-500/25 hover:bg-sky-500/20 transition"
                      >
                        جزئیات
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
        );
      })}

      <details className="mt-2">
        <summary className="text-[10px] text-emerald-600 dark:text-emerald-400 cursor-pointer">
          قرارداد فهرست کوتاه (مبنای مقایسه، لایه‌ها، منبع تاریخ قیمت، مسیر شرکت‌های بدون رتبه)
        </summary>
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
          <li dir="auto">منبع تاریخ قیمت: {priceSource.source}</li>
          <li dir="auto">پنجره خواندن: {priceSource.window_rule}</li>
          <li dir="auto">مبنای سن قیمت: {priceSource.policy_basis}</li>
          <li dir="auto">منبع سیاست تازگی: {priceSource.policy_source}</li>
          <li dir="auto">{priceSource.independent_of_warning_text}</li>
          <li dir="auto">{priceSource.security_selection}</li>
        </ul>
      </details>
    </div>
  );
};

const DiscoveryAxisCell: React.FC<{ a: QvtDiscoveryCompany["q"] }> = ({ a }) => (
  <div className="flex flex-col gap-0.5">
    <div className="flex items-baseline gap-1">
      <span className="text-sm font-bold tabular-nums text-gray-800 dark:text-gray-100">
        {a.points == null ? "—" : fmt(a.points)}
      </span>
      <span className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
        از {a.max_weight}
      </span>
    </div>
    <span className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
      پوشش {a.covered_weight == null ? "—" : fmt(a.covered_weight, 1)} (
      {fmtPct(a.coverage_ratio, 0)})
    </span>
  </div>
);

// ── ۲-ک-۴ P3: نامزدهای قابل بررسی با محدودیت مقایسه ─────────────────────
// شرکت‌های دارای شواهد سه‌محوری که در گروه مقایسهٔ معتبر (حداقل ۵ همتای
// هم‌صنعت/هم‌خانواده با پوشش فاکتور یکسان) قرار نمی‌گیرند: بدون لایه پارتو،
// بدون رتبه گروه و بدون هیچ رتبهٔ مصنوعی جایگزین. شمارش‌ها همه از پاسخ
// واقعی discovery می‌آید؛ این بخش نه امتیاز ترکیبی می‌سازد و نه سیگنال
// خرید است — فقط غربالگری برای باز کردن تحلیل جزئیات.
const ReviewableWithLimitsSection: React.FC<{
  data: QvtDiscoveryResponse;
  byId: Map<string, QvtDiscoveryCompany>;
  onOpenDetail: (
    companyId: string,
    symbol: string,
    candidate: QvtShortlistEntry | null
  ) => void;
}> = ({ data, byId, onOpenDetail }) => {
  const balanced = data.modes?.balanced;
  const [kind, setKind] = useState<"all" | "small_group" | "missing_scores">("all");
  const [tripleOnly, setTripleOnly] = useState(true);
  const [query, setQuery] = useState("");
  const [rgF, setRgF] = useState<string>("all");
  const [axSort, setAxSort] = useState<"mode" | "q" | "v" | "t">("mode");

  const rows = useMemo(() => {
    const out: { row: QvtDiscoveryRow; c: QvtDiscoveryCompany }[] = [];
    for (const row of balanced?.rows ?? []) {
      if (row.comparability === "comparable") continue; // رتبه‌پذیرها در فهرست کوتاه‌اند
      const c = byId.get(row.company_id);
      if (!c) continue;
      out.push({ row, c });
    }
    return out;
  }, [balanced, byId]);

  const hasTriple = (c: QvtDiscoveryCompany) =>
    c.q.points != null && c.v.points != null && c.t.points != null;

  const rgOptions = useMemo(() => {
    const s = new Set<string>();
    rows.forEach(({ c }) => c.risk_gate?.status && s.add(c.risk_gate.status));
    return Array.from(s).sort();
  }, [rows]);

  const filtered = useMemo(() => {
    const q = query.trim();
    const out = rows.filter(({ row, c }) => {
      if (kind !== "all" && row.comparability !== kind) return false;
      if (tripleOnly && !hasTriple(c)) return false;
      if (rgF !== "all" && c.risk_gate?.status !== rgF) return false;
      if (q && !(c.symbol.includes(q) || c.industry.includes(q))) return false;
      return true;
    });
    if (axSort === "mode") {
      out.sort((a, b) => a.row.display_order - b.row.display_order);
    } else {
      out.sort((a, b) => {
        const pa = a.c[axSort].points;
        const pb = b.c[axSort].points;
        if (pa != null && pb != null && pa !== pb) return pb - pa;
        if (pa == null) return 1;
        if (pb == null) return -1;
        return a.c.symbol < b.c.symbol ? -1 : 1;
      });
    }
    return out;
  }, [rows, kind, tripleOnly, rgF, query, axSort]);

  if (rows.length === 0) return null;
  const nTriple = rows.filter(({ c }) => hasTriple(c)).length;
  const nSmall = rows.filter(({ row }) => row.comparability === "small_group").length;
  const nMissing = rows.length - nSmall;

  return (
    <div className="rounded-2xl border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/40 dark:bg-amber-900/10 p-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h3 className="text-xs font-bold text-amber-700 dark:text-amber-300">
          🔎 نامزدهای قابل بررسی با محدودیت مقایسه: {rows.length} شرکت
        </h3>
        <span className="text-[10px] tabular-nums text-gray-500 dark:text-gray-400">
          دارای شواهد سه‌محوری: {nTriple} · گروه کوچک (&lt;۵ همتا): {nSmall} · بدون
          امتیاز مشاهده‌شده: {nMissing} — از مجموع {data.universe.n_triple_eligible}{" "}
          واجد شرایط هر سه محور، {data.shortlist.counts.companies} شرکت در گروه
          مقایسهٔ معتبر رتبه‌پذیر شده‌اند
        </span>
      </div>
      <p className="text-[10px] text-amber-600/90 dark:text-amber-400/80 leading-4 mt-1">
        تفاوت با نامزد قابل‌رتبه‌بندی: این شرکت‌ها لایه پارتو و رتبهٔ گروه
        ندارند — چون گروه همتای معتبر (حداقل ۵ همتا) برایشان تشکیل نمی‌شود؛ و
        عمداً هیچ رتبهٔ نسبی مصنوعی جایگزین هم ساخته نمی‌شود. این بخش فهرست
        غربالگری است، نه امتیاز ترکیبی و نه توصیهٔ خرید.
      </p>
      <div className="flex flex-wrap items-center gap-2 mt-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="جست‌وجوی نماد یا صنعت…"
          className="h-7 w-44 rounded-lg border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-2 text-[11px] text-gray-700 dark:text-gray-200 placeholder:text-gray-400 focus:outline-none"
        />
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as typeof kind)}
          className="h-7 rounded-lg border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-2 text-[11px] text-gray-600 dark:text-gray-300 focus:outline-none"
          title="نوع محدودیت مقایسه"
        >
          <option value="all">محدودیت: همه ({rows.length})</option>
          <option value="small_group">گروه کوچک ({nSmall})</option>
          <option value="missing_scores">بدون امتیاز مشاهده‌شده ({nMissing})</option>
        </select>
        <select
          value={rgF}
          onChange={(e) => setRgF(e.target.value)}
          className="h-7 rounded-lg border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-2 text-[11px] text-gray-600 dark:text-gray-300 focus:outline-none"
          title="فیلتر دروازه ریسک — هیچ وضعیتی به معنی تأیید یا کم‌ریسک بودن نیست"
        >
          <option value="all">دروازه ریسک: همه</option>
          {rgOptions.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select
          value={axSort}
          onChange={(e) => setAxSort(e.target.value as typeof axSort)}
          className="h-7 rounded-lg border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-2 text-[11px] text-gray-600 dark:text-gray-300 focus:outline-none"
          title="ترتیب نمایش — مرتب‌سازی بر امتیاز یک محور «رتبهٔ بنیادی» نیست و بین گروه‌های پوشش/صنعت متفاوت معنا ندارد"
        >
          <option value="mode">ترتیب: پیش‌فرض گروه‌ها</option>
          <option value="q">نمایش بر اساس Q (نزولی)</option>
          <option value="v">نمایش بر اساس V (نزولی)</option>
          <option value="t">نمایش بر اساس T (نزولی)</option>
        </select>
        <label className="flex items-center gap-1 text-[11px] text-gray-600 dark:text-gray-300 select-none">
          <input
            type="checkbox"
            checked={tripleOnly}
            onChange={(e) => setTripleOnly(e.target.checked)}
          />
          فقط دارای شواهد سه‌محوری کامل
        </label>
      </div>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-gray-100/95 dark:bg-gray-800/95 text-[10px] text-gray-500 dark:text-gray-400">
            <tr className="text-right">
              <th className="px-2 py-1.5 font-semibold">نماد</th>
              <th className="px-2 py-1.5 font-semibold">گروه</th>
              <th className="px-2 py-1.5 font-semibold">Q / پوشش از ۴۰</th>
              <th className="px-2 py-1.5 font-semibold">V / پوشش از ۳۵</th>
              <th className="px-2 py-1.5 font-semibold">T / پوشش از ۲۵</th>
              <th className="px-2 py-1.5 font-semibold">اطمینان داده</th>
              <th className="px-2 py-1.5 font-semibold">دروازه ریسک</th>
              <th className="px-2 py-1.5 font-semibold">محدودیت مقایسه (دلیل نداشتن رتبهٔ متوازن)</th>
              <th className="px-2 py-1.5 font-semibold"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={9} className="px-3 py-6 text-center text-gray-500 dark:text-gray-400">
                  شرکتی با این فیلترها یافت نشد
                </td>
              </tr>
            )}
            {filtered.map(({ row, c }) => (
              <tr
                key={row.company_id}
                className="border-t border-gray-100/80 dark:border-gray-700/40 hover:bg-amber-50/50 dark:hover:bg-amber-900/10 transition-colors align-top"
              >
                <td className="px-2 py-1.5 font-bold text-gray-800 dark:text-gray-100 whitespace-nowrap">
                  {c.symbol}
                </td>
                <td className="px-2 py-1.5 text-[10px] text-gray-500 dark:text-gray-400 whitespace-nowrap">
                  {row.group_label}
                  <span className="block text-gray-500 dark:text-gray-400">
                    {row.group_size} عضو گروه ·{" "}
                    {row.group_valid ? "گروه معتبر" : "گروه کمتر از حداقل"}
                  </span>
                </td>
                <td className="px-2 py-1.5"><DiscoveryAxisCell a={c.q} /></td>
                <td className="px-2 py-1.5"><DiscoveryAxisCell a={c.v} /></td>
                <td className="px-2 py-1.5"><DiscoveryAxisCell a={c.t} /></td>
                <td className="px-2 py-1.5">
                  {c.confidence ? (
                    <ConfidenceBadge cf={c.confidence} />
                  ) : (
                    <Chip tone="off">ارزیابی نشده</Chip>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  {c.risk_gate ? (
                    <RiskGateBadge rg={c.risk_gate} />
                  ) : (
                    <Chip tone="off">ارزیابی نشده</Chip>
                  )}
                </td>
                <td className="px-2 py-1.5 text-[10px] text-gray-500 dark:text-gray-400 leading-4">
                  {row.reason}
                  {!hasTriple(c) && (
                    <span className="block text-amber-600/90 dark:text-amber-400/80">
                      شواهد سه‌محوری کامل نیست — یکی از محورها امتیاز مشاهده‌شده ندارد.
                    </span>
                  )}
                </td>
                <td className="px-2 py-1.5">
                  <button
                    onClick={() => onOpenDetail(row.company_id, c.symbol, null)}
                    className="rounded-lg px-2 py-1 text-[10px] font-bold bg-white/70 dark:bg-gray-800/60 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-300/50 dark:ring-emerald-700/40 hover:bg-emerald-500/10 transition"
                    title="باز کردن تحلیل جزئیات بنیادی، ارزندگی و بازار همین شرکت"
                  >
                    جزئیات
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const DiscoveryView: React.FC<{
  onOpenDetail: (
    companyId: string,
    symbol: string,
    candidate: QvtShortlistEntry | null
  ) => void;
}> = ({ onOpenDetail }) => {
  const [data, setData] = useState<QvtDiscoveryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const [mode, setMode] = useState<QvtDiscoveryModeName>("balanced");
  const [query, setQuery] = useState("");
  const [industry, setIndustry] = useState("all");
  const [family, setFamily] = useState("all");
  const [cov, setCov] = useState<{ q: string; v: string; t: string }>({
    q: "all",
    v: "all",
    t: "all",
  });
  const [sortKey, setSortKey] = useState<DiscSortKey>("mode");
  const [sortDir, setSortDir] = useState<"desc" | "asc">("desc");
  const [page, setPage] = useState(1);
  // فیلتر وضعیت ارزیابی اطمینان داده — «بدون هشدار جدی» به معنی نبود ریسک
  // یا تأیید کامل داده نیست؛ فقط یعنی چنین هشداری در آرتیفکت ثبت نشده است.
  const [dcFilter, setDcFilter] = useState<
    "all" | "findings" | "no_findings" | "not_evaluable" | "no_serious" | "serious"
  >("all");
  // فیلتر دروازه ریسک — «بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن یا تأیید
  // سرمایه‌گذاری نیست؛ فقط یعنی در محدوده بررسی‌های انجام‌شده مانعی یافت نشد.
  const [rgFilter, setRgFilter] = useState<"all" | QvtRiskGateStatus>("all");

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetchQvtV2Discovery()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || "خطا در دریافت کشف فرصت‌ها"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  const byId = useMemo(() => {
    const m = new Map<string, QvtDiscoveryCompany>();
    data?.companies.forEach((c) => m.set(c.company_id, c));
    return m;
  }, [data]);

  // نامزدهای فهرست کوتاه بر اساس شناسه — باز کردن جزئیات از هر جدولی، خلاصه
  // شواهد نامزد را هم همراه می‌آورد
  const shortlistById = useMemo(() => {
    const m = new Map<string, QvtShortlistEntry>();
    (data?.shortlist.groups ?? []).forEach((g) =>
      g.entries.forEach((e) => m.set(e.company_id, e))
    );
    return m;
  }, [data]);

  const industries = useMemo(
    () =>
      Array.from(new Set((data?.companies ?? []).map((c) => c.industry))).sort(),
    [data]
  );
  const families = useMemo(
    () =>
      Array.from(new Set((data?.companies ?? []).map((c) => c.model_family))).sort(),
    [data]
  );

  // گزینه‌های فیلتر پوشش از داده واقعی محاسبه می‌شوند — تا سقف پوشش واقعی موجود
  const covOptions = useMemo(() => {
    const opts: Record<"q" | "v" | "t", { value: number; n: number }[]> = {
      q: [],
      v: [],
      t: [],
    };
    (data?.companies ?? []).forEach((c) => {
      (["q", "v", "t"] as const).forEach((ax) => {
        const w = c[ax].covered_weight;
        if (w == null) return;
        let o = opts[ax].find((x) => x.value === w);
        if (!o) {
          o = { value: w, n: 0 };
          opts[ax].push(o);
        }
        o.n++;
      });
    });
    (["q", "v", "t"] as const).forEach((ax) =>
      opts[ax].sort((a, b) => b.value - a.value)
    );
    return opts;
  }, [data]);

  // خلاصه واقعی وضعیت اطمینان داده از همان companies[] بازشماری می‌شود
  const dcSummary = useMemo(() => {
    let serious = 0;
    let noSerious = 0;
    const kinds = new Set<string>();
    (data?.companies ?? []).forEach((c) => {
      (c.confidence?.serious_warnings ?? []).forEach((k) => kinds.add(k));
      if ((c.confidence?.serious_warnings ?? []).length > 0) serious++;
      else noSerious++;
    });
    return { serious, noSerious, kinds: Array.from(kinds).sort() };
  }, [data]);

  // خلاصه واقعی دروازه ریسک + سرشماری انواع هشدار (برای «مشاهده نوع هشدار»)
  const rgSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    const kinds = new Map<string, number>();
    (data?.companies ?? []).forEach((c) => {
      const rg = c.risk_gate;
      if (!rg) return;
      counts[rg.status] = (counts[rg.status] ?? 0) + 1;
      rg.review_findings?.forEach((f) => kinds.set(f.kind, (kinds.get(f.kind) ?? 0) + 1));
      rg.blockers?.forEach((f) => kinds.set(f.kind, (kinds.get(f.kind) ?? 0) + 1));
    });
    return { counts, kinds: Array.from(kinds.entries()).sort((a, b) => b[1] - a[1]) };
  }, [data]);

  // متادیتای انواع هشدار از جدول طبقه‌بندی منتشرشده سرور
  const kindMeta = useMemo(() => {
    const m = new Map<string, { category?: string; severity_label?: string }>();
    const rows = (data?.risk_gate_rules as any)?.warning_kind_map as
      | { kind: string; category: string; severity_label: string }[]
      | undefined;
    (rows ?? []).forEach((r) => m.set(r.kind, r));
    return m;
  }, [data]);

  const modeResult = data?.modes?.[mode];

  const filtered = useMemo(() => {
    if (!modeResult) return [];
    const q = query.trim();
    const out: { row: QvtDiscoveryRow; c: QvtDiscoveryCompany }[] = [];
    for (const row of modeResult.rows) {
      const c = byId.get(row.company_id);
      if (!c) continue;
      if (industry !== "all" && c.industry !== industry) continue;
      if (family !== "all" && c.model_family !== family) continue;
      if (cov.q !== "all" && c.q.covered_weight !== Number(cov.q)) continue;
      if (cov.v !== "all" && c.v.covered_weight !== Number(cov.v)) continue;
      if (cov.t !== "all" && c.t.covered_weight !== Number(cov.t)) continue;
      if (q && !(c.symbol.includes(q) || c.industry.includes(q))) continue;
      if (dcFilter !== "all") {
        const cf = c.confidence;
        const hasSerious = (cf?.serious_warnings ?? []).length > 0;
        if (dcFilter === "serious" && !hasSerious) continue;
        if (dcFilter === "no_serious" && hasSerious) continue;
        if (dcFilter === "findings" && cf?.overall !== "findings") continue;
        if (dcFilter === "no_findings" && cf?.overall !== "no_findings_recorded") continue;
        if (dcFilter === "not_evaluable" && cf?.overall !== "not_evaluable") continue;
      }
      if (rgFilter !== "all" && c.risk_gate?.status !== rgFilter) continue;
      out.push({ row, c });
    }
    return out;
  }, [modeResult, byId, query, industry, family, cov, dcFilter, rgFilter]);

  const sorted = useMemo(() => {
    const arr = [...filtered];
    if (sortKey === "mode") {
      arr.sort((a, b) => a.row.display_order - b.row.display_order);
      return arr;
    }
    const pts = (x: (typeof arr)[number]) => x.c[sortKey].points;
    arr.sort((a, b) => {
      const pa = pts(a);
      const pb = pts(b);
      if (pa != null && pb != null && pa !== pb)
        return sortDir === "desc" ? pb - pa : pa - pb;
      if (pa == null) return 1; // بدون امتیاز مشاهده‌شده همیشه انتهای فهرست
      if (pb == null) return -1;
      return a.c.symbol < b.c.symbol ? -1 : 1;
    });
    return arr;
  }, [filtered, sortKey, sortDir]);

  useEffect(() => {
    setPage(1);
  }, [mode, query, industry, family, cov, sortKey, sortDir, dcFilter, rgFilter]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / DISC_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageRows = sorted.slice(
    (safePage - 1) * DISC_PAGE_SIZE,
    safePage * DISC_PAGE_SIZE
  );

  const clickSort = (key: Exclude<DiscSortKey, "mode">) => {
    if (sortKey !== key) {
      setSortKey(key);
      setSortDir("desc");
    } else if (sortDir === "desc") {
      setSortDir("asc");
    } else {
      setSortKey("mode");
    }
  };

  const sortArrow = (key: Exclude<DiscSortKey, "mode">) =>
    sortKey === key ? (sortDir === "desc" ? " ↓" : " ↑") : "";

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh] text-gray-500 dark:text-gray-400">
        <span className="text-sm font-medium">
          در حال بارگذاری کشف فرصت‌ها از خروجی واقعی…
        </span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-red-200/70 dark:border-red-900/40 bg-red-50/70 dark:bg-red-900/10 p-5 text-sm text-red-600 dark:text-red-400">
        {error}
      </div>
    );
  }
  if (!data || !modeResult) return null;
  const mc = modeResult.counts;

  const selectCls =
    "h-9 rounded-xl border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-2 text-xs text-gray-600 dark:text-gray-300 focus:outline-none focus:ring-2 focus:ring-emerald-500/30";

  return (
    <div className="animate-fade-in-up flex flex-col gap-3" style={{ animationDelay: "60ms" }}>
      {/* انتخاب حالت کشف */}
      <div className="flex flex-col gap-2">
        <div className="flex flex-wrap gap-2">
          {DISC_MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={`h-9 px-4 rounded-xl text-xs font-bold ring-1 transition ${
                mode === m.id
                  ? "bg-emerald-500 text-white ring-emerald-600 shadow-sm shadow-emerald-500/25"
                  : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-emerald-400/50"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <p className="text-[11px] text-gray-500 dark:text-gray-400 leading-5">
          {DISC_MODES.find((m) => m.id === mode)?.hint}
        </p>
      </div>

      {/* جعبه شفافیت: قواعد و شمارش واقعی */}
      <div className="rounded-2xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/50 dark:bg-sky-900/10 p-3">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-gray-600 dark:text-gray-300">
          <b className="text-gray-700 dark:text-gray-200">{modeResult.title}</b>
          <span className="tabular-nums">
            شرکت‌های این نما: <b>{mc.companies}</b> (واجد شرایط هر سه محور از{" "}
            {data.universe.n_all_artifacts} شرکت)
          </span>
          <span className="tabular-nums">
            رتبه‌بندی‌شده: <b>{mc.ranked}</b> · بدون رتبه: {mc.not_ranked}
          </span>
          <span className="tabular-nums">
            گروه‌های مقایسه معتبر: <b>{mc.groups_valid}</b> از {mc.groups_total}
          </span>
          <span className="tabular-nums">
            هشدار جدی ثبت‌شده: <b>{dcSummary.serious}</b> شرکت · بدون هشدار جدی ثبت‌شده:{" "}
            {dcSummary.noSerious} شرکت
            <span className="text-gray-500 dark:text-gray-400"> (≠ بدون ریسک / ≠ تأیید داده)</span>
          </span>
          <span className="tabular-nums">
            دروازه ریسک — نیازمند بررسی: <b>{rgSummary.counts.review_required ?? 0}</b> · مسدود:{" "}
            {rgSummary.counts.blocked ?? 0} · شواهد ناکافی:{" "}
            {rgSummary.counts.insufficient_evidence ?? 0} · بدون مانع اثبات‌شده:{" "}
            {rgSummary.counts.no_verified_blocker ?? 0}
            <span className="text-gray-500 dark:text-gray-400">
              {" "}
              (هیچ‌کدام به معنی تأیید یا کم‌ریسک بودن نیست)
            </span>
          </span>
          <span
            className="tabular-nums"
            title={data.snapshot_consistency?.note}
          >
            سازگاری snapshot سه فایل:{" "}
            <b>{data.snapshot_consistency?.consistent ? "هم‌خوان ✓" : "ناهم‌خوان ✗"}</b>
            <span className="text-gray-500 dark:text-gray-400">
              {" "}
              (سطح فایل — جدا از اعتبار زمانی داده داخلی هر شرکت)
            </span>
          </span>
        </div>
        <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5">
          {modeResult.order_note}
        </p>
        <details className="mt-1.5">
          <summary className="text-[10px] text-sky-600 dark:text-sky-400 cursor-pointer">
            قواعد کامل مقایسه (گروه‌بندی، حداقل همتا، غلبه پارتو، tie-break)
          </summary>
          <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
            {Object.values(data.mode_rules).map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </details>
        <details className="mt-1.5">
          <summary className="text-[10px] text-sky-600 dark:text-sky-400 cursor-pointer">
            قرارداد وضعیت اطمینان داده (ابعاد، منابع هر بُعد، تعریف «هشدار جدی»)
          </summary>
          <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
            {[
              data.confidence_rules?.what_it_is,
              data.confidence_rules?.no_numeric_score,
              data.confidence_rules?.recalibrated,
              data.confidence_rules?.unknown_warning_rule,
              data.confidence_rules?.serious_rule,
              data.confidence_rules?.risk_gate_unchanged,
              data.confidence_rules?.no_score_change,
              dcSummary.kinds.length > 0
                ? `انواع هشدار جدی طبقه‌بندی‌شده در این snapshot: ${dcSummary.kinds.join("، ")}`
                : undefined,
            ]
              .filter(Boolean)
              .map((r, i) => (
                <li key={i} dir="auto">{r as string}</li>
              ))}
          </ul>
        </details>
        <details className="mt-1.5">
          <summary className="text-[10px] text-sky-600 dark:text-sky-400 cursor-pointer">
            قرارداد دروازه ریسک (وضعیت‌ها، قواعد مسدودسازی، تفکیک هشدار ارزندگی/داده/ورود، جدول طبقه‌بندی)
          </summary>
          <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5 mt-1">
            {[
              data.risk_gate_rules?.what_it_is,
              data.risk_gate_rules?.read_only,
              data.risk_gate_rules?.status_precedence,
              data.risk_gate_rules?.never_blocks,
              data.risk_gate_rules?.evidence_gap_rule,
              data.risk_gate_rules?.unknown_warning_rule,
              data.risk_gate_rules?.snapshot_consistency_rule,
              data.risk_gate_rules?.no_score_change,
            ]
              .filter(Boolean)
              .map((r, i) => (
                <li key={i} dir="auto">{r as string}</li>
              ))}
            {((data.risk_gate_rules as any)?.blocking_rules ?? []).map((b: any, i: number) => (
              <li key={`b${i}`} dir="auto">
                قاعده {b.id}: {b.rule} — شواهد لازم: {b.evidence_required} {b.note ? `(${b.note})` : ""}
              </li>
            ))}
            {rgSummary.kinds.map(([k, n]) => {
              const meta = kindMeta.get(k);
              return (
                <li key={`k${k}`} dir="auto">
                  {k}: {n} شرکت — {meta?.category ?? "نوع طبقه‌بندی‌نشده"} ({meta?.severity_label ?? "—"})
                </li>
              );
            })}
          </ul>
        </details>
      </div>

      {/* نامزدهای اولویت‌دار برای بررسی — فهرست کوتاه کاربردی به تفکیک گروه
          مقایسه‌پذیر معتبر (گام ۲-ط-۱): لایه ۱ پارتو ابتدا، مرتب‌سازی فقط
          داخل گروه، وضعیت اطمینان داده/دروازه ریسک و کنترل مستقل تاریخ قیمت */}
      <PriorityCandidatesSection
        shortlist={data.shortlist}
        priceSource={data.price_source}
        onOpenDetail={(companyId, symbol, candidate) =>
          onOpenDetail(companyId, symbol, candidate)
        }
      />

      {/* ۲-ک-۴ P3: نامزدهای قابل بررسی با محدودیت مقایسه — شرکت‌های سه‌محوری
          بیرون از گروه‌های رتبه‌پذیر؛ بدون هیچ رتبه مصنوعی */}
      <ReviewableWithLimitsSection
        data={data}
        byId={byId}
        onOpenDetail={(companyId, symbol, candidate) =>
          onOpenDetail(companyId, symbol, candidate)
        }
      />

      {/* جست‌وجو و فیلترها */}
      <div className="flex flex-wrap items-center gap-2">
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="جست‌وجوی نماد یا صنعت…"
          className="h-9 w-56 rounded-xl border border-gray-200/80 dark:border-gray-700/60 bg-white/80 dark:bg-gray-800/50 px-3 text-sm text-gray-700 dark:text-gray-200 placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-emerald-500/30 focus:border-emerald-500 transition"
        />
        <select value={industry} onChange={(e) => setIndustry(e.target.value)} className={selectCls}>
          <option value="all">صنعت: همه</option>
          {industries.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        <select value={family} onChange={(e) => setFamily(e.target.value)} className={selectCls}>
          <option value="all">خانواده: همه</option>
          {families.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>
        {(["q", "v", "t"] as const).map((ax) => (
          <select
            key={ax}
            value={cov[ax]}
            onChange={(e) => setCov((p) => ({ ...p, [ax]: e.target.value }))}
            className={selectCls}
            title="فیلتر پوشش وزن واقعی همین محور"
          >
            <option value="all">پوشش {ax.toUpperCase()}: همه</option>
            {covOptions[ax].map((o) => (
              <option key={o.value} value={String(o.value)}>
                = {fmt(o.value, 1)} ({o.n} شرکت)
              </option>
            ))}
          </select>
        ))}
        <select
          value={dcFilter}
          onChange={(e) => setDcFilter(e.target.value as typeof dcFilter)}
          className={selectCls}
          title="وضعیت ارزیابی اطمینان داده (کیفی، بدون عدد) — «بدون هشدار جدی ثبت‌شده» به معنی نبود ریسک یا تأیید کامل داده نیست"
        >
          <option value="all">اطمینان داده: همه</option>
          <option value="findings">دارای یافته ثبت‌شده</option>
          <option value="no_findings">بدون یافته ثبت‌شده (≠ تأیید)</option>
          <option value="not_evaluable">ارزیابی‌ناپذیر</option>
          <option value="no_serious">فقط بدون هشدار جدی ثبت‌شده (≠ بدون ریسک)</option>
          <option value="serious">دارای هشدار جدی ثبت‌شده</option>
        </select>
        <select
          value={rgFilter}
          onChange={(e) => setRgFilter(e.target.value as typeof rgFilter)}
          className={selectCls}
          title="وضعیت دروازه ریسک — «بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن یا تأیید سرمایه‌گذاری نیست؛ شواهد ناکافی یعنی تصمیم قطعی ممکن نشده"
        >
          <option value="all">دروازه ریسک: همه</option>
          <option value="blocked">مسدود — مانع اثبات‌شده</option>
          <option value="review_required">نیازمند بررسی</option>
          <option value="insufficient_evidence">شواهد ناکافی برای تصمیم</option>
          <option value="no_verified_blocker">بدون مانع اثبات‌شده (≠ تأیید)</option>
        </select>
        <span className="text-[11px] text-gray-500 dark:text-gray-400">
          {sorted.length} شرکت در نمایش
        </span>
      </div>

      {/* جدول کشف */}
      <div className="rounded-3xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="bg-gray-100/95 dark:bg-gray-800/95 text-[10px] text-gray-500 dark:text-gray-400">
              <tr className="text-right">
                <th className="px-2.5 py-2.5 font-semibold">#</th>
                <th className="px-2.5 py-2.5 font-semibold">شرکت (نماد)</th>
                <th className="px-2.5 py-2.5 font-semibold">صنعت</th>
                <th className="px-2.5 py-2.5 font-semibold">
                  <button onClick={() => clickSort("q")} className="hover:text-emerald-600 dark:hover:text-emerald-400 transition">
                    Q مشاهده‌شده / پوشش از ۴۰{sortArrow("q")}
                  </button>
                </th>
                <th className="px-2.5 py-2.5 font-semibold">
                  <button onClick={() => clickSort("v")} className="hover:text-emerald-600 dark:hover:text-emerald-400 transition">
                    V مشاهده‌شده / پوشش از ۳۵{sortArrow("v")}
                  </button>
                </th>
                <th className="px-2.5 py-2.5 font-semibold">
                  <button onClick={() => clickSort("t")} className="hover:text-emerald-600 dark:hover:text-emerald-400 transition">
                    T مشاهده‌شده / پوشش از ۲۵{sortArrow("t")}
                  </button>
                </th>
                <th className="px-2.5 py-2.5 font-semibold">وضعیت مقایسه‌پذیری</th>
                <th className="px-2.5 py-2.5 font-semibold">وضعیت اطمینان داده</th>
                <th className="px-2.5 py-2.5 font-semibold">دروازه ریسک</th>
                <th className="px-2.5 py-2.5 font-semibold">هشدارها و محدودیت‌ها</th>
                <th className="px-2.5 py-2.5 font-semibold">دلیل حضور در نتیجه</th>
                <th className="px-2.5 py-2.5 font-semibold"></th>
              </tr>
            </thead>
            <tbody>
              {pageRows.length === 0 && (
                <tr>
                  <td colSpan={12} className="px-3 py-8 text-center text-gray-500 dark:text-gray-400">
                    شرکتی با این فیلترها یافت نشد
                  </td>
                </tr>
              )}
              {pageRows.map(({ row, c }, i) => (
                <tr
                  key={row.company_id}
                  className="border-t border-gray-100/80 dark:border-gray-700/40 hover:bg-emerald-50/40 dark:hover:bg-emerald-900/10 transition-colors align-top"
                >
                  <td className="px-2.5 py-2 tabular-nums text-gray-500 dark:text-gray-400">
                    {(safePage - 1) * DISC_PAGE_SIZE + i + 1}
                  </td>
                  <td className="px-2.5 py-2 font-bold text-gray-800 dark:text-gray-100 whitespace-nowrap">
                    {c.symbol}
                  </td>
                  <td className="px-2.5 py-2 text-gray-500 dark:text-gray-400 whitespace-nowrap">
                    {c.industry}
                  </td>
                  <td className="px-2.5 py-2"><DiscoveryAxisCell a={c.q} /></td>
                  <td className="px-2.5 py-2"><DiscoveryAxisCell a={c.v} /></td>
                  <td className="px-2.5 py-2"><DiscoveryAxisCell a={c.t} /></td>
                  <td className="px-2.5 py-2">
                    {c.confidence ? (
                      <ConfidenceBadge cf={c.confidence} />
                    ) : (
                      <Chip tone="off">ارزیابی نشده</Chip>
                    )}
                  </td>
                  <td className="px-2.5 py-2">
                    {c.risk_gate ? (
                      <RiskGateBadge rg={c.risk_gate} />
                    ) : (
                      <Chip tone="off">ارزیابی نشده</Chip>
                    )}
                  </td>
                  <td className="px-2.5 py-2">
                    <div className="flex flex-col items-start gap-1">
                      {row.comparability === "comparable" && (
                        <Chip tone="ok" title={row.group_label}>
                          گروه معتبر · {row.group_size} همتا
                        </Chip>
                      )}
                      {row.comparability === "small_group" && (
                        <Chip tone="warn" title={row.group_label}>
                          گروه کوچک · {row.group_size} همتا
                        </Chip>
                      )}
                      {row.comparability === "missing_scores" && (
                        <Chip tone="off" title={row.group_label}>
                          بدون امتیاز مشاهده‌شده
                        </Chip>
                      )}
                      {row.pareto_layer != null && (
                        <Chip
                          tone="neutral"
                          title={
                            row.pareto_layer === 1
                              ? "هیچ همتای گروهی در هیچ‌یک از سه محور بر این شرکت غالب نیست — این فقط ابزار کشف است، نه بهترین فرصت خرید و نه ارزیابی ریسک"
                              : `در لایه ${row.pareto_layer} پارتو گروه قرار دارد؛ لایه‌ها فقط ابزار کشف‌اند، نه رتبه خرید`
                          }
                        >
                          {row.pareto_layer === 1
                            ? "نامغلوب در گروه قابل‌مقایسه"
                            : `لایه پارتو ${row.pareto_layer}`}
                        </Chip>
                      )}
                      {row.group_rank != null && (
                        <Chip
                          tone="neutral"
                          title={
                            row.group_valid
                              ? "رتبه داخل گروه مقایسه‌پذیر"
                              : "رتبه اطلاعی — گروه کمتر از ۵ همتای قابل‌مقایسه دارد"
                          }
                        >
                          رتبه گروه {row.group_rank}
                          {row.group_valid ? "" : " (اطلاعی)"}
                        </Chip>
                      )}
                    </div>
                  </td>
                  <td className="px-2.5 py-2">
                    <div className="flex flex-col items-start gap-1">
                      {c.warnings.n > 0 && (
                        <Chip
                          tone="warn"
                          title={[...(c.warnings.financial ?? []), ...(c.warnings.trading ?? [])].join("\n")}
                        >
                          {c.warnings.n} هشدار
                        </Chip>
                      )}
                      {(() => {
                        const issues = [
                          ...(c.q.factor_issues ?? []),
                          ...(c.v.factor_issues ?? []),
                          ...(c.t.factor_issues ?? []),
                        ];
                        if (issues.length === 0)
                          return <span className="text-[10px] text-gray-300 dark:text-gray-600">—</span>;
                        return (
                          <Chip
                            tone="off"
                            title={issues
                              .map((is) => `${factorLabel(is.factor)} — ${is.reason || is.kind}`)
                              .join("\n")}
                          >
                            {issues.length} محدودیت فاکتور
                          </Chip>
                        );
                      })()}
                    </div>
                  </td>
                  <td className="px-2.5 py-2 max-w-[240px]">
                    <span
                      className="block text-[10px] leading-4 text-gray-500 dark:text-gray-400 truncate"
                      title={row.reason}
                    >
                      {row.reason}
                    </span>
                  </td>
                  <td className="px-2.5 py-2">
                    <button
                      onClick={() =>
                        onOpenDetail(c.company_id, c.symbol, shortlistById.get(c.company_id) ?? null)
                      }
                      className="h-7 px-2.5 rounded-lg text-[10px] font-bold bg-sky-500/10 text-sky-700 dark:text-sky-300 ring-1 ring-sky-500/25 hover:bg-sky-500/20 transition"
                    >
                      جزئیات
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* صفحه‌بندی */}
      <div className="flex items-center justify-between text-[11px] text-gray-500 dark:text-gray-400">
        <span className="tabular-nums">
          صفحه {safePage} از {totalPages} — {sorted.length} شرکت
        </span>
        <div className="flex gap-1.5">
          <button
            disabled={safePage <= 1}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            className="h-8 px-3 rounded-xl ring-1 ring-gray-300/60 dark:ring-gray-700/50 bg-white/70 dark:bg-gray-800/40 disabled:opacity-40 hover:ring-emerald-400/50 transition"
          >
            قبلی
          </button>
          <button
            disabled={safePage >= totalPages}
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            className="h-8 px-3 rounded-xl ring-1 ring-gray-300/60 dark:ring-gray-700/50 bg-white/70 dark:bg-gray-800/40 disabled:opacity-40 hover:ring-emerald-400/50 transition"
          >
            بعدی
          </button>
        </div>
      </div>

      {/* خط صداقت مخصوص کشف فرصت‌ها */}
      <div className="rounded-2xl border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10 p-3">
        <p className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 leading-4">
          این فهرست فقط «کاندیدای بررسی بیشتر» است، نه توصیه خرید؛ هیچ امتیاز کل از ۱۰۰
          وجود ندارد، وزن مفقود بازتوزیع نمی‌شود و مفقود صفر فرض نشده است. «وضعیت اطمینان
          داده» ارزیابی کیفی شواهد ثبت‌شده است — بدون عدد اطمینان؛ «دروازه ریسک» با قواعد
          صریح وضعیت می‌دهد، فقط‌خواندنی است و هیچ امتیازی را تغییر نمی‌دهد؛ هشدارهای
          ارزندگی، داده و شرایط ورود از هم جدا ارزیابی می‌شوند و ریسک اقتصادی واقعی
          الزاماً مسدودکننده نیست. «بدون یافته ثبت‌شده»، «بدون هشدار جدی ثبت‌شده» و «بدون
          مانع اثبات‌شده» به معنی کم‌ریسک بودن، تأیید داده یا نبود ریسک نیست و شرکت با
          شواهد ناکافی هرگز «تأییدشده» معرفی نمی‌شود.
        </p>
      </div>
    </div>
  );
};


// ── گام ۲-ک-۷ + ۲-ک-۸ — «فرصت‌های قابل بررسی بازار» (نمای سادهٔ پیش‌فرض) ────
// چهار گروه تصمیم‌محور. همهٔ متن‌ها از موتور سمت backend (opportunity.go +
// opportunity_decision.go — قواعد نسخهٔ ۲) با اعداد قابل ردیابی می‌آیند؛
// اینجا هیچ متن کلی یا عددی ساخته نمی‌شود. «جزئیات بیشتر» همان پروندهٔ مالی
// موجود همین snapshot را باز می‌کند. صفر نامزد جذاب ممکن و صادقانه است.
const BOARD_AXIS_FA: Record<string, string> = {
  q: "کیفیت Q",
  v: "ارزندگی V",
  t: "ورود T",
};

const BOARD_NOT_ATT_FA: Record<string, string> = {
  ok: "در گروه جذاب",
  risk_gate_blocked: "مانع اثبات‌شده در دروازه ریسک",
  missing_scores: "امتیاز مشاهده‌شده مفقود",
  weak_no_case: "بدون پروندهٔ قابل دفاع (بنیادی ضعیف و ارزندگی نامشخص)",
  apparent_value_weak_fundamentals: "ارزان‌نما با بنیادی ضعیف",
  small_group: "گروه مقایسه کمتر از ۵ همتا",
  price_freshness_unverified: "تازگی قیمت تأیید نشد",
  decision_value_not_defensible: "ارزندگی قابل دفاع نبود",
  decision_entry_not_ok: "شرایط ورود مناسب نبود",
  conditional_quality_caveat: "قید کیفیت اقتصادی (تبدیل نقد/سود عملیاتی)",
};

const BOARD_BLOCKED_FA: Record<string, string> = {
  risk_gate_blocked: "مانع اثبات‌شده در دروازه ریسک",
  missing_scores: "امتیاز مشاهده‌شده مفقود",
  no_defensible_case: "بدون پروندهٔ قابل دفاع در شواهد فعلی",
};

const BoardAxisChip: React.FC<{ axis: "q" | "v" | "t"; s: QvtBoardAxisStatus }> = ({ axis, s }) => {
  if (s.status !== "computed" || s.points == null) {
    return (
      <Chip tone="off" title="امتیاز مشاهده‌شده در دسترس نیست — هیچ مقدار جایگزینی ساخته نشده است">
        {BOARD_AXIS_FA[axis]}: مفقود
      </Chip>
    );
  }
  const cov = s.coverage_ratio != null ? `${Math.round(s.coverage_ratio * 100)}٪` : null;
  return (
    <Chip
      tone="neutral"
      title={`${s.n_scored_factors} فاکتور امتیازگرفته · بیشینهٔ وزن ${s.max}${s.n_factor_issues > 0 ? ` · ${s.n_factor_issues} محدودیت فاکتور` : ""}`}
    >
      {BOARD_AXIS_FA[axis]}: {s.points.toFixed(1)}/{s.max}
      {cov ? ` · پوشش ${cov}` : ""}
    </Chip>
  );
};

const BOARD_FUND_TONE: Record<string, "ok" | "neutral" | "warn" | "danger" | "off"> = {
  strong: "ok",
  acceptable: "neutral",
  weak: "danger",
  insufficient: "off",
};

const BOARD_ENTRY_TONE: Record<string, "ok" | "neutral" | "warn" | "danger" | "off"> = {
  ok: "ok",
  neutral: "warn",
  hostile: "danger",
  insufficient: "off",
};

const BoardFreshnessTone = (label: string): "ok" | "warn" | "danger" =>
  label.includes("تأیید شد") ? "ok" : label.includes("نقض") ? "danger" : "warn";

// چیپ‌های لایهٔ تصمیم ۲-ک-۹: بنیادی/ارزندگی/ورود — هر عدد صریحاً «پرسنتایل»
// برچسب می‌خورد تا با نسبت مالی خام اشتباه نشود (نسبت خام در جزئیات آمده).
const BoardDecisionChips: React.FC<{ e: QvtBoardEntry }> = ({ e }) => (
  <div className="flex flex-wrap gap-1">
    <Chip
      tone={BOARD_FUND_TONE[e.fundamental] ?? "off"}
      title={e.fundamental_note.join(" · ") || e.fundamental_label}
    >
      بنیادی: {e.fundamental_label}
      {e.roe_pct != null ? ` · پرسنتایل roe ${e.roe_pct.toFixed(2)}` : ""}
      {e.cash_conversion_pct != null ? ` · تبدیل نقد ${e.cash_conversion_pct.toFixed(2)}` : ""}
    </Chip>
    <Chip
      tone={e.value_defensible ? "ok" : e.value_cheap ? "warn" : "off"}
      title={e.value_note.join(" · ") || e.value_label}
    >
      ارزندگی: {e.value_label}
      {e.value_mean != null ? ` · میانگین پرسنتایل ${e.value_mean.toFixed(2)}` : ""}
    </Chip>
    <Chip tone={BOARD_ENTRY_TONE[e.entry] ?? "off"} title={e.entry_note.join(" · ") || e.entry_label}>
      ورود: {e.entry_label}
    </Chip>
    {e.conditional && (
      <Chip
        tone="warn"
        title={(e.conditional_reasons ?? []).join(" · ") || "قید کیفیت اقتصادی ثبت‌شده"}
      >
        مشروط — قید کیفیت ثبت‌شده
      </Chip>
    )}
  </div>
);

const BoardThreeQuestions: React.FC<{ e: QvtBoardEntry }> = ({ e }) => (
  <div className="grid md:grid-cols-3 gap-2 mt-1">
    {[
      { title: "چرا این نماد؟", items: e.why, tone: "text-emerald-700 dark:text-emerald-300" },
      { title: "چرا ممکن است انتخاب خوبی نباشد؟", items: e.careful, tone: "text-amber-700 dark:text-amber-300" },
      { title: "چه زمانی ارزش بررسی مجدد دارد؟", items: e.review_when, tone: "text-sky-700 dark:text-sky-300" },
    ].map((sec) => (
      <div key={sec.title} className="rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2">
        <p className={`text-[10px] font-bold mb-1 ${sec.tone}`}>{sec.title}</p>
        <ul className="list-disc pr-4 space-y-0.5">
          {(sec.items.length ? sec.items : ["مورد ثبت‌شده‌ای در شواهد نیست."]).map((s, i) => (
            <li key={i} className="text-[10px] leading-4 text-gray-600 dark:text-gray-300" dir="auto">
              {s}
            </li>
          ))}
        </ul>
      </div>
    ))}
  </div>
);

const BoardCandidateCard: React.FC<{
  e: QvtBoardEntry;
  rankShown: boolean;
  onOpenDetail: (companyId: string, symbol: string) => void;
}> = ({ e, rankShown, onOpenDetail }) => {
  const px = e.price_freshness;
  return (
    <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3 flex flex-col gap-1.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-xs font-bold text-gray-800 dark:text-gray-100">{e.symbol}</span>
        <Chip tone="off">{e.industry}</Chip>
        {e.group === "attractive_candidates" && e.pareto_layer != null && (
          <Chip tone="off" title="جایگاه درون گروه مقایسه‌پذیر — ابزار کشف، نه رتبه بازار">
            لایه پارتو {e.pareto_layer} در گروه {e.group_size} همتا
          </Chip>
        )}
        {e.validation_status === "independently_checked" && (
          <Chip tone="ok" title={e.validation_status_label}>اعتبارسنجی اقتصادی مستقل: بازتولید کامل</Chip>
        )}
        <span
          className={`mr-auto px-2 py-0.5 rounded-lg text-[10px] font-bold ring-1 ${
            e.group === "attractive_candidates"
              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/25"
              : e.group === "fundamentals_waiting"
              ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-amber-500/25"
              : e.group === "apparent_value_risk"
              ? "bg-red-500/10 text-red-700 dark:text-red-300 ring-red-500/25"
              : "bg-gray-100 dark:bg-gray-700/40 text-gray-500 dark:text-gray-400 ring-gray-400/20"
          }`}
        >
          {rankShown && e.group === "attractive_candidates" ? `${e.display_rank}. ` : ""}
          {e.conclusion}
        </span>
      </div>
      <p className="text-[10px] text-gray-600 dark:text-gray-300 leading-4" dir="auto">
        {e.group_reason}
      </p>
      <div className="flex flex-wrap gap-1">
        <BoardAxisChip axis="q" s={e.q} />
        <BoardAxisChip axis="v" s={e.v} />
        <BoardAxisChip axis="t" s={e.t} />
      </div>
      <BoardDecisionChips e={e} />
      <div className="flex flex-wrap gap-1">
        <Chip
          tone={BoardFreshnessTone(e.freshness_label)}
          title={px?.last_trade_date ? `آخرین معامله: ${px.last_trade_date} · منبع: ${px.source ?? "—"}` : e.freshness_label}
        >
          تازگی قیمت: {e.freshness_label}
        </Chip>
        <Chip tone="neutral" title="ارزیابی کیفی شواهد — بدون عدد اطمینان؛ معادل تأیید کامل داده نیست">
          اعتبار داده: {e.confidence_label}
        </Chip>
        <Chip
          tone={e.risk_gate_status === "blocked" ? "danger" : e.risk_gate_status === "no_verified_blocker" ? "neutral" : "warn"}
          title="فقط‌خواندنی؛ «بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن نیست"
        >
          دروازه ریسک: {e.risk_gate_label}
        </Chip>
      </div>
      <BoardThreeQuestions e={e} />
      <button
        onClick={() => onOpenDetail(e.company_id, e.symbol)}
        className="self-start h-7 px-3 rounded-xl text-[10px] font-bold ring-1 ring-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/20 transition"
      >
        جزئیات بیشتر — پروندهٔ مالی همین snapshot
      </button>
    </div>
  );
};

const BoardCompactRow: React.FC<{
  e: QvtBoardEntry;
  onOpenDetail: (companyId: string, symbol: string) => void;
}> = ({ e, onOpenDetail }) => (
  <details className="rounded-xl bg-white/60 dark:bg-gray-800/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2">
    <summary className="cursor-pointer flex flex-wrap items-center gap-1.5 select-none">
      <span className="text-[11px] font-bold text-gray-700 dark:text-gray-200">{e.symbol}</span>
      <Chip tone="off">{e.industry}</Chip>
      <span className="text-[10px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
        {e.group_reason}
      </span>
    </summary>
    <div className="mt-1.5">
      <BoardDecisionChips e={e} />
      <BoardThreeQuestions e={e} />
      <button
        onClick={() => onOpenDetail(e.company_id, e.symbol)}
        className="mt-1.5 h-7 px-3 rounded-xl text-[10px] font-bold ring-1 ring-emerald-400/40 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-500/20 transition"
      >
        جزئیات بیشتر — پروندهٔ مالی همین snapshot
      </button>
    </div>
  </details>
);

const POLICY_FA: Record<string, string> = {
  q_strong_roe: "آستانهٔ سودآوری قوی — پرسنتایل roe_level",
  q_weak_roe: "آستانهٔ بنیادی ضعیف — پرسنتایل roe_level",
  q_strong_margin: "آستانهٔ حاشیهٔ سود برای حکم «قوی»",
  q_safety_min: "آستانهٔ ساختار سرمایه (اهرم یا پوشش بهره)",
  q_weak_factor: "آستانهٔ «فاکتور ضعیف»",
  q_weak_factor_n: "حداقل تعداد فاکتور ضعیف برای حکم ضعف بنیادی",
  q_cash_min: "کف پرسنتایل تبدیل نقد (cash_conversion) — زیر آن «قید کیفیت» ثبت می‌شود",
  v_cheap: "آستانهٔ ارزانی نسبی — میانگین پرسنتایل P/E·P/B·P/S",
  v_expensive: "آستانهٔ گران نسبی",
  v_multiple_min: "حداقل پرسنتایل P/E یا P/B برای «ارزندگی قابل دفاع»",
  v_min_sector_support: "حداقل هم‌صنعت معتبر برای چندگانهٔ پشتیبان ارزندگی",
  t_momentum_ok: "آستانهٔ ورود مناسب — پرسنتایل مومنتوم ۶ماههٔ نسبی",
  t_momentum_hostile: "آستانهٔ مومنتوم نامساعد",
  t_rs_hostile: "آستانهٔ قدرت نسبی نامساعد",
  t_liq_floor_rial: "کف مطلق نقدشوندگی (میلیارد ریال در روز)",
};

const OpportunityBoardView: React.FC<{
  onOpenDetail: (companyId: string, symbol: string) => void;
  onSwitchToDiscover: () => void;
}> = ({ onOpenDetail, onSwitchToDiscover }) => {
  const [data, setData] = useState<QvtDiscoveryResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showAllAtt, setShowAllAtt] = useState(false);
  const [showWait, setShowWait] = useState(false);
  const [showCheap, setShowCheap] = useState(false);
  const [showBlocked, setShowBlocked] = useState(false);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    fetchQvtV2Discovery()
      .then((d) => alive && setData(d))
      .catch((e) => alive && setError(e?.message || "خطا در دریافت فرصت‌های قابل بررسی"))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, []);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[30vh] text-gray-500 dark:text-gray-400">
        <span className="text-sm font-medium">در حال محاسبهٔ فرصت‌های قابل بررسی از شواهد واقعی…</span>
      </div>
    );
  }
  if (error) {
    return (
      <div className="rounded-2xl border border-red-200/70 dark:border-red-900/40 bg-red-50/70 dark:bg-red-900/10 p-4 text-sm text-red-600 dark:text-red-400">
        {error}
      </div>
    );
  }
  const board = data?.opportunity_board ?? null;
  if (!board) {
    return (
      <div className="rounded-2xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/60 dark:bg-amber-900/10 p-4 text-xs text-amber-700 dark:text-amber-300 leading-6">
        برد «فرصت‌های قابل بررسی بازار» در پاسخ backend در دسترس نیست — نسخهٔ backend قدیمی است؛ هیچ جایگزینی ساخته نمی‌شود.
      </div>
    );
  }
  const att = board.attractive_candidates;
  const visibleAtt = showAllAtt ? att : att.slice(0, board.default_visible);
  const nia = board.counts.not_in_attractive_reasons ?? {};
  // قرارداد صریح شمارش (گام ۲-ک-۱۰): گروه‌ها (متباین و مجموع‌بخش) جدا از
  // صفت‌ها. سازگاری پس‌رو با backend قدیمی که این تفکیک را ندارد حفظ شده است.
  const c = board.counts;
  const g = c.groups ?? {
    attractive_candidates: c.attractive_candidates ?? 0,
    fundamentals_waiting: c.fundamentals_waiting ?? 0,
    apparent_value_risk: c.apparent_value_risk ?? 0,
    blocked_or_insufficient: c.blocked_or_insufficient ?? 0,
    total: c.n_triple_universe ?? 0,
    universe: c.n_triple_universe ?? 0,
    mutually_exclusive: true,
    reconciles: true,
  };
  const at = c.attributes ?? {
    conditional_total: c.conditional_candidates ?? 0,
    conditional_in_waiting: c.conditional_candidates ?? 0,
    conditional_blocking: c.n_conditional_blocking ?? 0,
    negative_operating_profit: 0,
    risk_review_required: c.n_risk_review_required ?? 0,
    price_freshness_verified: c.n_price_freshness_verified ?? 0,
  };

  return (
    <div className="flex flex-col gap-3">
      {/* سربرگ نمای ساده */}
      <div className="rounded-3xl border border-emerald-200/60 dark:border-emerald-900/40 bg-gradient-to-l from-emerald-50/70 to-teal-50/40 dark:from-emerald-900/10 dark:to-teal-900/5 p-4">
        <p className="text-sm font-bold text-emerald-800 dark:text-emerald-300">🎯 {board.title}</p>
        <p className="text-[11px] text-gray-600 dark:text-gray-300 leading-5 mt-1" dir="auto">
          {board.subtitle}
        </p>
        <p className="text-[10px] text-amber-700/90 dark:text-amber-400/80 leading-4 mt-1" dir="auto">
          {board.not_a_signal}
        </p>
        <div className="flex flex-wrap gap-1.5 mt-2">
          <Chip tone="off">snapshot {board.as_of}</Chip>
          <Chip tone="neutral" title={board.engine_note}>
            موتور تصمیم قاعده‌محور — بدون امتیاز از ۱۰۰
          </Chip>
          <Chip tone="off">جامعهٔ سه‌محوری: {board.counts.n_triple_universe} شرکت</Chip>
          <Chip
            tone={g.reconciles ? "neutral" : "danger"}
            title="چهار گروه تصمیم متباین‌اند و مجموعشان دقیقاً جامعهٔ سه‌محوری است (صفت‌ها مثل «مشروط» به این جمع افزوده نمی‌شوند)"
          >
            گروه‌ها: {g.attractive_candidates}+{g.fundamentals_waiting}+{g.apparent_value_risk}+{g.blocked_or_insufficient} = {g.total}
            {g.reconciles ? "" : " ⚠"}
          </Chip>
          {typeof at.price_freshness_verified === "number" && (
            <Chip tone="neutral" title="کنترل مستقل تازگی قیمت در پنجره PIT برای همهٔ اعضای جامعه (صفت مستقل از گروه)">
              تازگی قیمت تأییدشده: {at.price_freshness_verified}/
              {board.counts.n_triple_universe}
            </Chip>
          )}
          {typeof at.risk_review_required === "number" && at.risk_review_required > 0 && (
            <Chip tone="warn" title="review_required یک قید جهانی snapshot است (نه گروه و نه رد قطعی) — یافته‌های ثبت‌شدهٔ هر شرکت در کارت آن است">
              دروازه ریسک نیازمند بررسی: {at.risk_review_required}/
              {board.counts.n_triple_universe}
            </Chip>
          )}
          {typeof at.conditional_total === "number" && at.conditional_total > 0 && (
            <Chip tone="warn" title="صفت مستقل از گروه: واجد آستانه‌ها اما با قید کیفیت اقتصادی ثبت‌شده — «جذاب بدون قید اختصاصی» نیستند">
              نامزد مشروط (قید کیفیت، صفت): {at.conditional_total}
            </Chip>
          )}
          {board.decision_policy && (
            <Chip tone="off" title={board.decision_policy.note}>
              سیاست تصمیم: {board.decision_policy.version}
            </Chip>
          )}
        </div>
        {Array.isArray(board.systemic_caveats) && board.systemic_caveats.length > 0 && (
          <div className="mt-2 rounded-2xl border border-amber-300/50 dark:border-amber-900/50 bg-amber-50/60 dark:bg-amber-900/10 p-2">
            <p className="text-[10px] font-bold text-amber-800 dark:text-amber-300 mb-1">
              قیدهای جهانی این snapshot — همهٔ نامزدها را هم‌زمان تحت‌تأثیر می‌گذارند و در تصمیم هر شرکت لحاظ شده‌اند:
            </p>
            <ul className="list-disc pr-4 space-y-0.5">
              {board.systemic_caveats.map((c, i) => (
                <li key={i} className="text-[10px] leading-4 text-amber-800/90 dark:text-amber-300/90" dir="auto">
                  {c}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>

      {/* گروه ۱ — نامزدهای جذاب برای بررسی جدی */}
      <section className="rounded-3xl border border-emerald-200/60 dark:border-emerald-900/40 bg-emerald-50/40 dark:bg-emerald-900/10 p-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <p className="text-[12px] font-bold text-emerald-700 dark:text-emerald-300">
            ۱) نامزدهای جذاب برای بررسی جدی ({g.attractive_candidates} نامزد)
          </p>
          <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
            گیت‌های شواهد + ترکیب قابل دفاع بنیادی/ارزندگی/ورود با آستانه‌های اعلامی سیاست تصمیم. داشتن دادهٔ معتبر به‌تنهایی جذابیت نیست؛ صفر نامزد هم نتیجهٔ صادقانه است.
          </p>
        </div>
        {att.length === 0 ? (
          <div className="rounded-2xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/60 dark:bg-amber-900/10 p-3 text-[11px] text-amber-700 dark:text-amber-300 leading-5" dir="auto">
            {board.empty_note || "با آستانه‌های سیاست تصمیم، نامزد جذاب قابل دفاعی پیدا نشد."}
          </div>
        ) : (
          <>
            <div className="grid lg:grid-cols-2 gap-2">
              {visibleAtt.map((e) => (
                <BoardCandidateCard key={e.company_id} e={e} rankShown={true} onOpenDetail={onOpenDetail} />
              ))}
            </div>
            {att.length > board.default_visible && (
              <button
                onClick={() => setShowAllAtt((v) => !v)}
                className="self-start h-8 px-3 rounded-xl text-[11px] font-bold ring-1 ring-emerald-400/40 bg-white/70 dark:bg-gray-800/40 text-emerald-700 dark:text-emerald-300 hover:ring-emerald-400/70 transition"
              >
                {showAllAtt ? "نمایش کمتر" : `نمایش همهٔ ${att.length} نامزد جذاب`}
              </button>
            )}
          </>
        )}
      </section>

      {/* چرا بقیهٔ جامعه جذاب نشدند — شمارش موانع اصلی */}
      <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-2.5">
        <p className="text-[10px] font-bold text-gray-500 dark:text-gray-400 mb-1">
          چرا بقیهٔ جامعهٔ {board.counts.n_triple_universe} شرکتی در گروه جذاب نیست؟ (مانع اصلی هر شرکت — شمارش از داده)
        </p>
        <div className="flex flex-wrap gap-1">
          {Object.entries(nia)
            .filter(([k, v]) => k !== "ok" && v > 0)
            .map(([k, v]) => (
              <Chip key={k} tone="off">
                {BOARD_NOT_ATT_FA[k] ?? k}: {v}
              </Chip>
            ))}
        </div>
      </div>

      {/* گروه ۲ — بنیادی مناسب، منتظر شرایط بهتر */}
      <section className="rounded-3xl border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/40 dark:bg-amber-900/10 p-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <p className="text-[12px] font-bold text-amber-700 dark:text-amber-300">
            ۲) بنیادی مناسب، منتظر شرایط بهتر ({g.fundamentals_waiting} شرکت
            {typeof at.conditional_in_waiting === "number" && at.conditional_in_waiting > 0
              ? ` — از این میان ${at.conditional_in_waiting} «نامزد مشروط» با قید کیفیت ثبت‌شده (صفت مستقل، نه گروه)`
              : ""}
            )
          </p>
          <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
            ویژگی بنیادی مثبت ثبت‌شده دارند اما ارزندگی قابل دفاع، شرایط ورود، گروه همتای معتبر، تازگی قیمت یا قید کیفیت اقتصادی (تبدیل نقد ضعیف / سود عملیاتی منفی) مانع ارتقاست — مانع مشخص هر شرکت با عدد همراهش آمده است.
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          {(showWait ? board.fundamentals_waiting : board.fundamentals_waiting.slice(0, 6)).map((e) => (
            <BoardCompactRow key={e.company_id} e={e} onOpenDetail={onOpenDetail} />
          ))}
        </div>
        {board.fundamentals_waiting.length > 6 && (
          <button
            onClick={() => setShowWait((v) => !v)}
            className="self-start h-8 px-3 rounded-xl text-[11px] font-bold ring-1 ring-amber-400/40 bg-white/70 dark:bg-gray-800/40 text-amber-700 dark:text-amber-300 hover:ring-amber-400/70 transition"
          >
            {showWait ? "نمایش کمتر" : `نمایش همهٔ ${board.fundamentals_waiting.length} شرکت منتظر`}
          </button>
        )}
      </section>

      {/* گروه ۳ — ارزان به نظر می‌رسند، اما ریسک دارند */}
      <section className="rounded-3xl border border-red-200/60 dark:border-red-900/40 bg-red-50/30 dark:bg-red-900/10 p-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <p className="text-[12px] font-bold text-red-700 dark:text-red-300">
            ۳) ارزان به نظر می‌رسند، اما ریسک دارند ({g.apparent_value_risk} شرکت)
          </p>
          <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
            ارزندگی ظاهری (پرسنتایل بالای P/E·P/B·P/S) همراه با بنیادی ضعیف یا شواهد ناکافی — همان الگوی value trap؛ هرگز در پیشنهاد اولیه نمی‌آیند.
          </p>
        </div>
        <div className="flex flex-col gap-1.5">
          {(showCheap ? board.apparent_value_risk : board.apparent_value_risk.slice(0, 6)).map((e) => (
            <BoardCompactRow key={e.company_id} e={e} onOpenDetail={onOpenDetail} />
          ))}
          {board.apparent_value_risk.length === 0 && (
            <p className="text-[10px] text-gray-500 dark:text-gray-400">الگوی «ارزان‌نمای پرریسک» در جامعهٔ فعلی ثبت نشده است.</p>
          )}
        </div>
        {board.apparent_value_risk.length > 6 && (
          <button
            onClick={() => setShowCheap((v) => !v)}
            className="self-start h-8 px-3 rounded-xl text-[11px] font-bold ring-1 ring-red-400/40 bg-white/70 dark:bg-gray-800/40 text-red-700 dark:text-red-300 hover:ring-red-400/70 transition"
          >
            {showCheap ? "نمایش کمتر" : `نمایش همهٔ ${board.apparent_value_risk.length} مورد`}
          </button>
        )}
      </section>

      {/* گروه ۴ — شواهد ناکافی یا دارای مانع */}
      <section className="rounded-3xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-3 flex flex-col gap-2">
        <div className="flex flex-wrap items-baseline gap-2">
          <p className="text-[12px] font-bold text-gray-600 dark:text-gray-300">
            ۴) شواهد ناکافی یا دارای مانع ({g.blocked_or_insufficient} شرکت)
          </p>
          <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4" dir="auto">
            این‌ها بدون رفع محدودیت وارد پیشنهاد اولیه نمی‌شوند؛ دلیل دقیق هر شرکت همراهش است. سایر شرکت‌های خارج از جامعهٔ سه‌محوری در نمای «همه شرکت‌ها» با همان قواعد قابل مشاهده‌اند.
          </p>
        </div>
        <div className="flex flex-wrap gap-1">
          {Object.entries(board.counts.blocked_breakdown ?? {})
            .filter(([, v]) => v > 0)
            .map(([k, v]) => (
              <Chip key={k} tone="off">
                {BOARD_BLOCKED_FA[k] ?? k}: {v}
              </Chip>
            ))}
        </div>
        <div className="flex flex-col gap-1.5">
          {(showBlocked ? board.blocked_or_insufficient : board.blocked_or_insufficient.slice(0, 6)).map((e) => (
            <BoardCompactRow key={e.company_id} e={e} onOpenDetail={onOpenDetail} />
          ))}
          {board.blocked_or_insufficient.length === 0 && (
            <p className="text-[10px] text-gray-500 dark:text-gray-400">موردی با مانع یا شواهد ناکافی در جامعهٔ سه‌محوری نیست.</p>
          )}
        </div>
        {board.blocked_or_insufficient.length > 6 && (
          <button
            onClick={() => setShowBlocked((v) => !v)}
            className="self-start h-8 px-3 rounded-xl text-[11px] font-bold ring-1 ring-gray-400/40 bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 hover:ring-gray-400/70 transition"
          >
            {showBlocked ? "نمایش کمتر" : `نمایش همهٔ ${board.blocked_or_insufficient.length} مورد`}
          </button>
        )}
      </section>

      {/* قواعد و سیاست تصمیم قابل ممیزی */}
      <details className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-3">
        <summary className="cursor-pointer text-[11px] font-bold text-gray-600 dark:text-gray-300 select-none">
          قواعد و آستانه‌های موتور — شفاف، نسخه‌دار و قابل بازتولید
        </summary>
        {board.decision_policy && (
          <div className="mt-2 rounded-xl bg-white/70 dark:bg-gray-900/30 ring-1 ring-gray-200/60 dark:ring-gray-700/40 p-2">
            <p className="text-[10px] font-bold text-gray-600 dark:text-gray-300 mb-1">
              سیاست تصمیم {board.decision_policy.version} — همهٔ آستانه‌ها آشکار
            </p>
            <div className="grid sm:grid-cols-2 gap-x-4 gap-y-0.5">
              {Object.entries(board.decision_policy)
                .filter(([k]) => POLICY_FA[k])
                .map(([k, v]) => (
                  <p key={k} className="text-[10px] leading-4 text-gray-500 dark:text-gray-400" dir="auto">
                    <b className="text-gray-600 dark:text-gray-300">{POLICY_FA[k]}:</b>{" "}
                    {k === "t_liq_floor_rial" ? `${(Number(v) / 1e9).toFixed(0)}` : String(v)}
                  </p>
                ))}
            </div>
            <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-1" dir="auto">
              {board.decision_policy.note}
            </p>
          </div>
        )}
        <ul className="list-disc pr-5 mt-1.5 space-y-1">
          {Object.entries(board.rules).map(([k, v]) => (
            <li key={k} className="text-[10px] leading-4 text-gray-500 dark:text-gray-400" dir="auto">
              <b className="text-gray-600 dark:text-gray-300">{k}:</b> {v}
            </li>
          ))}
        </ul>
        <p className="text-[10px] text-gray-500 dark:text-gray-400 leading-4 mt-1.5" dir="auto">
          {board.engine_note}
        </p>
      </details>

      {/* خط صداقت مخصوص برد فرصت‌ها */}
      <div className="rounded-2xl border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/50 dark:bg-amber-900/10 p-3">
        <p className="text-[10px] font-semibold text-amber-700 dark:text-amber-300 leading-4">
          این فهرست فقط «کاندیدای بررسی بیشتر» است، نه توصیه خرید؛ هیچ امتیاز کل از ۱۰۰ وجود ندارد، وزن مفقود بازتوزیع نمی‌شود
          و مفقود صفر فرض نشده است. آستانه‌های گروه‌بندی سیاست آزمایشی اعلامی این گام‌اند — نه اثبات آماری سودآوری. «بدون یافتهٔ
          ثبت‌شده»، «بدون هشدار جدی» و «بدون مانع اثبات‌شده» به معنی کم‌ریسک بودن، تأیید داده یا نبود ریسک نیست و شرکت با شواهد
          ناکافی هرگز «تأییدشده» معرفی نمی‌شود.
        </p>
      </div>

      <button
        onClick={onSwitchToDiscover}
        className="self-start h-8 px-3 rounded-xl text-[11px] font-bold ring-1 ring-emerald-400/40 bg-white/70 dark:bg-gray-800/40 text-emerald-700 dark:text-emerald-300 hover:ring-emerald-400/70 transition"
      >
        نمای پیشرفته: کشف فرصت‌ها با لایه‌های پارتو و جدول کامل ←
      </button>
    </div>
  );
};

// ── صفحه اصلی ────────────────────────────────────────────────────────────────
const QvtAnalysisPage: React.FC = () => {
  const [summary, setSummary] = useState<QvtV2Summary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  // سه نمای قابل انتخاب؛ «فرصت‌های قابل بررسی بازار» (گام ۲-ک-۷) پیش‌فرض است
  const [view, setView] = useState<"board" | "discover" | "all">("board");
  const [query, setQuery] = useState("");
  const [onlyTriple, setOnlyTriple] = useState(false);
  // فیلتر کفایت شواهد (۲-ک-۲) برای نمای همه شرکت‌ها — مستقل از امتیازها
  const [valFilterAll, setValFilterAll] = useState<"all" | "shortlist" | "checked" | "review">("all");
  const [selected, setSelected] = useState<{
    company_id: string;
    symbol: string;
    candidate?: QvtShortlistEntry | null;
  } | null>(null);

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
      if (valFilterAll === "shortlist" && !r.shortlisted) return false;
      if (valFilterAll === "checked" && r.validation_status !== "independently_checked") return false;
      if (valFilterAll === "review" && r.validation_needs_review !== true) return false;
      if (!q) return true;
      return (
        r.symbol.includes(q) ||
        r.industry.includes(q) ||
        r.model_family.includes(q) ||
        r.company_id.toLowerCase().includes(q.toLowerCase())
      );
    });
  }, [summary, query, onlyTriple, valFilterAll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[50vh] text-gray-500 dark:text-gray-400">
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
        <p className="text-xs text-gray-500 dark:text-gray-400 mt-3 leading-5">
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
          <Chip tone="neutral">Data Confidence: ارزیابی کیفی شواهد — بدون عدد اطمینان</Chip>
          <Chip tone="neutral">Risk Gate: ارزیابی مستقل ریسک — فقط‌خواندنی، بدون تغییر امتیاز</Chip>
          <Chip tone="off">snapshot {summary.as_of}</Chip>
          <Chip tone="off" title={`cutoff: ${summary.cutoff}`}>
            سه محور Q و V و T مستقل‌اند — هیچ امتیاز کل از ۱۰۰ وجود ندارد
          </Chip>
        </div>
      </div>

      {/* انتخاب نما: فرصت‌های قابل بررسی (پیش‌فرض ساده) / کشف فرصت‌ها / همه شرکت‌ها */}
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => setView("board")}
          className={`h-10 px-4 rounded-2xl text-xs font-bold ring-1 transition ${
            view === "board"
              ? "bg-emerald-500 text-white ring-emerald-600 shadow-sm shadow-emerald-500/25"
              : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-emerald-400/50"
          }`}
        >
          🎯 فرصت‌های قابل بررسی بازار
        </button>
        <button
          onClick={() => setView("discover")}
          className={`h-10 px-4 rounded-2xl text-xs font-bold ring-1 transition ${
            view === "discover"
              ? "bg-emerald-500 text-white ring-emerald-600 shadow-sm shadow-emerald-500/25"
              : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-emerald-400/50"
          }`}
        >
          🔎 کشف فرصت‌ها (پیشرفته)
        </button>
        <button
          onClick={() => setView("all")}
          className={`h-10 px-4 rounded-2xl text-xs font-bold ring-1 transition ${
            view === "all"
              ? "bg-emerald-500 text-white ring-emerald-600 shadow-sm shadow-emerald-500/25"
              : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-emerald-400/50"
          }`}
        >
          همه شرکت‌ها ({summary.counts.n_total})
        </button>
        <span className="text-[11px] text-gray-500 dark:text-gray-400">
          {view === "board"
            ? "نمای پیش‌فرض ساده — چند نامزد قابل‌دفاع با دلیل و ریسک هرکدام، از شواهد واقعی همین snapshot"
            : view === "discover"
            ? "نمای پیشرفته — فهرست کاندیدای بررسی بیشتر از میان شرکت‌های واجد شرایط هر سه محور"
            : "نمایش کامل همه شرکت‌های آرتیفکت با قابلیت‌های قبلی"}
        </span>
      </div>

      {view === "board" ? (
        <OpportunityBoardView
          onOpenDetail={(companyId, symbol) => setSelected({ company_id: companyId, symbol })}
          onSwitchToDiscover={() => setView("discover")}
        />
      ) : view === "discover" ? (
        <DiscoveryView
          onOpenDetail={(companyId, symbol, candidate) =>
            setSelected({ company_id: companyId, symbol, candidate })
          }
        />
      ) : (
        <>
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
            <p className="text-[10px] text-gray-500 dark:text-gray-400">{s.label}</p>
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
        <span className="inline-flex items-center gap-1.5">
          <span className="text-[10px] font-bold text-violet-700 dark:text-violet-300">کفایت شواهد:</span>
          {([
            ["all", "همه", ""],
            ["shortlist", `نامزدها (${summary.companies.filter((r) => r.shortlisted).length})`, "فقط ۱۶ نامزد فهرست کوتاه"],
            ["checked", `بررسی مستقل کامل (${c.validation?.independently_checked ?? 0})`, "نامزدهایی که همه اجزای مؤثرشان بازتولید مستقل و ردیابی کامل دارد"],
            ["review", `نیازمند بررسی (${(c.validation?.consistent_but_not_independent ?? 0) + (c.validation?.insufficient_evidence ?? 0) + (c.validation?.conflicting ?? 0)})`, "نامزدهایی با حداقل یک حلقه اثبات‌نشده یا تعارض"],
          ] as const).map(([k, label, tip]) => (
            <button
              key={k}
              onClick={() => setValFilterAll(k as typeof valFilterAll)}
              className={`h-9 px-2.5 rounded-xl text-[11px] font-semibold ring-1 transition ${
                valFilterAll === k
                  ? "bg-violet-500 text-white ring-violet-600 shadow-sm shadow-violet-500/25"
                  : "bg-white/70 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-gray-300/60 dark:ring-gray-700/50 hover:ring-violet-400/50"
              }`}
              title={tip}
            >
              {label}
            </button>
          ))}
        </span>
        <span className="text-[11px] text-gray-500 dark:text-gray-400">
          {rows.length} شرکت در نمایش
        </span>
        <span className="mr-auto text-[10px] text-gray-500 dark:text-gray-400" dir="ltr">
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
                  <td colSpan={7} className="px-3 py-8 text-center text-gray-500 dark:text-gray-400">
                    شرکتی با این جست‌وجو/فیلتر یافت نشد
                  </td>
                </tr>
              )}
              {rows.map((r) => (
                <tr
                  key={r.company_id}
                  onClick={() =>
                    setSelected({ company_id: r.company_id, symbol: r.symbol })
                  }
                  className="cursor-pointer border-t border-gray-100/80 dark:border-gray-700/40 hover:bg-emerald-50/50 dark:hover:bg-emerald-900/10 transition-colors"
                >
                  <td className="px-3 py-2 font-bold text-gray-800 dark:text-gray-100 whitespace-nowrap">
                    {r.symbol}
                    <span className="mr-1.5 text-[9px] font-normal text-gray-500 dark:text-gray-400">
                      {r.model_family === "general" ? "" : r.model_family}
                    </span>
                    {r.validation_status && (
                      <span
                        className={`ms-1 inline-block rounded-md px-1.5 py-0.5 text-[9px] font-bold ring-1 ${
                          r.validation_status === "independently_checked"
                            ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-emerald-500/25"
                            : r.validation_status === "conflicting"
                            ? "bg-red-500/10 text-red-700 dark:text-red-300 ring-red-500/25"
                            : r.validation_needs_review
                            ? "bg-amber-500/10 text-amber-700 dark:text-amber-300 ring-amber-500/25"
                            : "bg-gray-500/10 text-gray-500 dark:text-gray-400 ring-gray-500/20"
                        }`}
                        title={`اعتبارسنجی اقتصادی مستقل — ${r.validation_status_label}\n${r.validation_reason_preview ?? ""}`}
                      >
                        {r.validation_status_label}
                      </span>
                    )}
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
        <ul className="list-disc pr-5 text-[10px] leading-4 text-gray-500 dark:text-gray-400 space-y-0.5">
          {Object.values(summary.boundaries).map((b, i) => (
            <li key={i}>{b}</li>
          ))}
        </ul>
      </div>
        </>
      )}

      {selected && (
        <DetailPanel
          companyId={selected.company_id}
          symbol={selected.symbol}
          candidate={selected.candidate ?? null}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
};

export default QvtAnalysisPage;
