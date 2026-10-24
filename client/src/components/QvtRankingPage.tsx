import { Fragment, useEffect, useMemo, useState } from "react";
import { jwtDecode } from "jwt-decode";
import QvtPaperPanel from "./QvtPaperPanel";
import {
  fetchQvtV2Ranking,
  fetchQvtV2Paper,
  type QvtPaperSummary,
  getPortfolio,
  type PortfolioSummary,
  type QvtRankedStock,
  type QvtRankAxis,
  type QvtRankingResponse,
  type QvtUnscoredStock,
} from "../utils/api";

// ─────────────────────────────────────────────────────────────────────────────
// صفحهٔ سادهٔ «رتبه‌بندی سهام» (گام ۲-ک-۱۱)
//
// هدف: کاربر صفحه را باز کند، بهترین سهم‌ها را بالای جدول ببیند و با یک نگاه
// بفهمد چرا ارزش بررسی دارند.
//
// اصول:
//   * امتیاز ۰..۱۰۰ فقط برای نمادهایی که هر سه محور Q/V/T آن‌ها دادهٔ کافی و
//     معتبر دارند؛ بقیه بدون امتیاز و با دلیل دقیق نمایش داده می‌شوند.
//   * فرمول رسمی Q/V/T و وزن‌ها دست‌نخورده است؛ امتیاز مجموع سه امتیاز
//     مشاهده‌شدهٔ رسمی است (بدون تقسیم بر پوشش و بدون بازتوزیع وزن).
//   * ریسک بحرانی/قید کیفیت هم‌ردیف امتیاز نمایش داده می‌شود و پشت آن پنهان
//     نمی‌شود.
//   * جزئیات فنی با کلیک باز می‌شود و در نمای اصلی شلوغی ایجاد نمی‌کند.
// ─────────────────────────────────────────────────────────────────────────────

const FALLBACK_DISCLAIMER =
  "نسخه آزمایشی — اعتبار تاریخی اطلاعات مالی و قیمت‌ها به‌طور کامل تأیید نشده است. نتایج توصیه خرید و فروش نیستند.";

const briefRisk = (stock: QvtRankedStock) => {
  if (stock.critical) return "مانع جدی یا تعارض شواهد؛ جزئیات را بررسی کنید.";
  const text = stock.main_risk || "ریسک مشخصی در این خلاصه ثبت نشده است.";
  if (text.includes("cash_conversion")) return "تبدیل سود به جریان نقد ضعیف است.";
  if (text.includes("share_snapshot_older_than_price")) return "هماهنگی تعداد سهام و قیمت نیاز به بررسی دارد.";
  if (text.includes("magnitude_anomaly")) return "مقدار غیرعادی در داده؛ صحت آن نیاز به بررسی دارد.";
  if (text.includes("stale_price")) return "قیمت استفاده‌شده قدیمی است.";
  return text;
};

type Tab = "ranked" | "portfolio" | "unscored" | "paper";

const num = (v: number | null | undefined, d = 1) =>
  v == null || !isFinite(v) ? "—" : v.toFixed(d);

const pct = (v: number | null | undefined, d = 0) =>
  v == null || !isFinite(v) ? "—" : `${(v * 100).toFixed(d)}%`;

const rankStatusTone: Record<string, string> = {
  buy_review:
    "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30",
  wait: "bg-amber-500/12 text-amber-700 dark:text-amber-300 ring-amber-500/30",
  weak: "bg-rose-500/12 text-rose-700 dark:text-rose-300 ring-rose-500/30",
};

const scoreTone = (_s: number) => "text-gray-800 dark:text-gray-100";
const marketDate = (value: string) => new Intl.DateTimeFormat("fa-IR", { timeZone: "UTC" }).format(new Date(`${value}T00:00:00Z`));
const factorProfile = (s: QvtRankedStock) => [s.model_family, s.q.scored_factors?.join(","), s.v.scored_factors?.join(","), s.t.scored_factors?.join(",")].join("|");

// برچسب کوتاهِ کامل بودن داده — فقط «پوشش کامل» یا «پوشش جزئی ٪».
function CoverageChip({ s }: { s: QvtRankedStock }) {
  const full = s.full_coverage;
  const pctTxt = s.coverage_min != null ? `${Math.round(s.coverage_min * 100)}%` : "—";
  return (
    <span
      title={
        full
          ? "این نماد همهٔ عوامل مشاهده‌شده در خانوادهٔ خود را پوشش می‌دهد؛ صحت داده و توان پیش‌بینی جداگانه بررسی می‌شوند."
          : `بخشی از عوامل بنیادی این نماد دادهٔ مفقود دارند؛ سقف عملی امتیازش ${num(
              s.practical_ceiling,
              0,
            )} است (نه ۱۰۰). این محدودیت داده است، نه ضعف عملکرد.`
      }
      className={`text-[9px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap ${
        full
          ? "bg-emerald-500/12 text-emerald-700 dark:text-emerald-300 ring-emerald-500/30"
          : "bg-amber-500/12 text-amber-700 dark:text-amber-300 ring-amber-500/30"
      }`}
    >
      {full ? "پوشش بیشینه" : `پوشش جزئی ${pctTxt}`}
    </span>
  );
}

// برچسب کوچک اعتبار گروه همتای متوازن — فقط وقتی کمتر از ۵ عضو دارد، چون
// در آن حالت رتبهٔ نسبی درون‌صنعت معتبر نیست و فقط قرائت مطلق خوانده می‌شود.
function PeerGroupChip({ s }: { s: QvtRankedStock }) {
  // فقط گروه ارزیابی‌شدهٔ کوچک (۱ تا ۴ عضو) نشان داده می‌شود؛ اندازهٔ ۰ یعنی
  // نماد خارج از نامزدهای متوازن است و گروه اصلاً ارزیابی نشده.
  if (s.peer_group_valid || s.peer_group_size <= 0) return null;
  return (
    <span
      title={`گروه همتای متوازن این نماد در صنعت «${s.industry}» فقط ${s.peer_group_size} عضو دارد (حداقل ۵ لازم است)؛ رتبهٔ نسبی درون‌صنعت معتبر نیست و فقط معیار مطلق خوانده می‌شود — این گروه دوشرکتی معادل مقایسهٔ صنعتی معتبر نیست.`}
      className="text-[9px] px-1.5 py-0.5 rounded-full ring-1 whitespace-nowrap bg-slate-500/10 text-slate-600 dark:text-slate-300 ring-slate-400/30"
    >
      گروه همتا {s.peer_group_size}
    </span>
  );
}

// پنل شفافِ مقایسه‌پذیری + برنامهٔ مشخص تکمیل داده (بازشو).
function ComparabilityPanel({ data }: { data: QvtRankingResponse }) {
  const [open, setOpen] = useState(false);
  const ci = data.coverage_impact;
  const pg = data.peer_group_impact;
  const plan = data.data_completion_plan;
  return (
    <div className="rounded-2xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/50 dark:bg-sky-900/10 p-3 text-[11px] leading-5">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="text-sky-800 dark:text-sky-200 max-w-3xl">
          <b>کیفیت پوشش:</b> {ci.n_full_coverage} نماد با پوشش بیشینهٔ عوامل مشاهده‌شده و {ci.n_partial_coverage} نماد با پوشش جزئی.
        </p>
        <button
          onClick={() => setOpen((v) => !v)}
          className="text-[11px] px-2.5 py-1 rounded-xl bg-white/70 dark:bg-sky-950/30 ring-1 ring-sky-300/50 dark:ring-sky-700/50 text-sky-700 dark:text-sky-200 hover:bg-white"
        >
          {open ? "بستن" : "جزئیات و راه‌حل تکمیل داده"}
        </button>
      </div>

      {open && (
        <div className="mt-3 space-y-2 text-sky-900/90 dark:text-sky-100/90">
          <p>{ci.interpretation}</p>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-[10px] tabular-nums">
            <div className="rounded-xl bg-white/60 dark:bg-sky-950/20 px-2 py-1.5">
              <div className="opacity-70">پوشش کامل</div>
              <div className="font-bold">{ci.n_full_coverage} نماد</div>
            </div>
            <div className="rounded-xl bg-white/60 dark:bg-sky-950/20 px-2 py-1.5">
              <div className="opacity-70">پوشش جزئی</div>
              <div className="font-bold">{ci.n_partial_coverage} نماد</div>
            </div>
            <div className="rounded-xl bg-white/60 dark:bg-sky-950/20 px-2 py-1.5">
              <div className="opacity-70">همبستگی رتبهٔ خام با رتبهٔ هم‌پوشش</div>
              <div className="font-bold">
                {ci.spearman_raw_vs_coverage_equalized.toFixed(3)}
              </div>
            </div>
            <div className="rounded-xl bg-white/60 dark:bg-sky-950/20 px-2 py-1.5">
              <div className="opacity-70">بیشترین جابه‌جایی رتبه</div>
              <div className="font-bold">{ci.max_rank_shift} رتبه</div>
            </div>
          </div>
          <p>
            <b>سقف عملی امتیاز</b> بین {num(ci.practical_ceiling_min, 0)} و{" "}
            {num(ci.practical_ceiling_max, 0)} است (نه ۱۰۰)؛ تفاوت آن با ۱۰۰ فقط از
            عوامل محاسبه‌نشده می‌آید: دادهٔ ناقص، پیاده‌سازی یا سیاست محاسبه. همبستگی امتیاز با پوشش بنیادی{" "}
            {ci.spearman_score_vs_q_coverage.toFixed(3)} است.
            از {ci.n_scored} نماد، {ci.n_shift_gt5} نماد بیش از ۵ رتبه و{" "}
            {ci.n_shift_gt10} نماد بیش از ۱۰ رتبه جابه‌جا می‌شوند.
            {ci.top10_overlap != null && ` از ${ci.top10_count} نماد برتر، ${ci.top10_overlap} نماد در فهرست بالای تحلیل حساسیت باقی می‌مانند.`}
          </p>
          <p>
            <b>اعتبار مقایسهٔ صنعتی:</b> {pg.interpretation} در این snapshot{" "}
            {pg.n_valid_group} نماد گروه معتبر (حداقل {pg.min_group_rule} همتا)
            دارند و {pg.n_small_group} نماد گروه کوچک‌تر (۱ تا ۴ عضو) دارند — شامل{" "}
            {pg.top10_small_group} نماد از ۱۰ نماد برتر — که برای آن‌ها رتبهٔ نسبی
            صنعت صادر نمی‌شود؛ {pg.n_group_not_evaluated} نماد هم خارج از
            نامزدهای متوازن‌اند (گروه ارزیابی‌نشده).
          </p>
          <div className="rounded-xl bg-white/60 dark:bg-sky-950/20 p-2.5 space-y-1">
            <p className="font-bold">راه‌حل مشخص برای مقایسه‌پذیرکردن:</p>
            <p>{plan.why_q_only}</p>
            <p>
              <b>شکاف ساختاری:</b> {plan.structural_gap}
            </p>
            <p>
              <b>تفاوت بین نمادها:</b> {plan.differentiating_gaps}
            </p>
            <p>
              <b>علت پس‌ماندهٔ ناقص‌ها:</b> {plan.residual_causes}
            </p>
            <ul className="list-disc pr-4 space-y-0.5">
              {plan.steps.map((st, i) => (
                <li key={i}>{st}</li>
              ))}
            </ul>
            <p>
              <b>معیار موفقیت:</b> {plan.success_criterion}
            </p>
            <p className="opacity-80">{plan.not_a_new_score}</p>
          </div>
        </div>
      )}
    </div>
  );
}

function AxisBar({
  label,
  axis,
  colorClass,
}: {
  label: string;
  axis: QvtRankAxis;
  colorClass: string;
}) {
  const ratio = axis.coverage_ratio ?? 0;
  return (
    <div className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-900/30 p-2.5">
      <div className="flex items-center justify-between text-[11px] mb-1">
        <span className="font-bold text-gray-700 dark:text-gray-200">{label}</span>
        <span className="tabular-nums text-gray-500 dark:text-gray-400">
          {num(axis.points)} از {num(axis.max, 0)}
        </span>
      </div>
      <div className="h-1.5 rounded-full bg-gray-200/70 dark:bg-gray-700/50 overflow-hidden">
        <div
          className={`h-full ${colorClass}`}
          style={{ width: `${Math.max(0, Math.min(100, (ratio || 0) * 100))}%` }}
        />
      </div>
      <div className="flex items-center justify-between text-[10px] mt-1 text-gray-500 dark:text-gray-400 tabular-nums">
        <span>پوشش {pct(axis.coverage_ratio)}</span>
        <span>{axis.n_scored_factors} عامل</span>
        {axis.n_factor_issues > 0 && (
          <span className="text-amber-600 dark:text-amber-400">
            {axis.n_factor_issues} محدودیت داده
          </span>
        )}
      </div>
    </div>
  );
}

function DetailPanel({ s }: { s: QvtRankedStock }) {
  const q = s.q.points ?? 0;
  const v = s.v.points ?? 0;
  const t = s.t.points ?? 0;
  return (
    <div className="px-3 pb-4 pt-1 space-y-3 text-[12px]">
      <div className="rounded-xl bg-amber-50/60 dark:bg-amber-900/10 p-2.5 text-amber-800 dark:text-amber-200 leading-6">
        <b>دلیل اصلی:</b> {s.main_reason || "—"}<br />
        <b>ریسک مهم:</b> {s.main_risk || "—"}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <AxisBar label="بنیادی (Q)" axis={s.q} colorClass="bg-indigo-500" />
        <AxisBar label="ارزندگی (V)" axis={s.v} colorClass="bg-emerald-500" />
        <AxisBar label="شرایط ورود (T)" axis={s.t} colorClass="bg-cyan-500" />
      </div>

      {(s.q.missing_factors?.length ?? 0) > 0 && (
        <div className="rounded-xl bg-amber-50/60 dark:bg-amber-900/10 p-2.5 text-[11px]">
          <b>عوامل بنیادی بدون سهم در امتیاز:</b>
          <ul className="mt-1 space-y-1">
            {s.q.missing_factors?.map((f) => <li key={f.factor}>{f.label}، وزن {num(f.weight, 0)}: {f.reason}</li>)}
          </ul>
          <p className="mt-1">این عوامل عملکرد صفر ندارند؛ کمبود داده و آماده‌نبودن مدل علت‌های جدا هستند.</p>
        </div>
      )}
      {(s.timing_windows?.length ?? 0) > 0 && (
        <div className="rounded-xl bg-cyan-50/60 dark:bg-cyan-900/10 p-2.5 text-[11px]">
          <b>بازهٔ واقعی مقایسهٔ بازده:</b>
          {s.timing_windows?.map((w) => <p key={w.factor}>{w.label}: {marketDate(w.start)} تا {marketDate(w.end)}{w.anchor_age_days > 7 && `؛ قیمت پایه ${w.anchor_age_days} روز پیش از ابتدای بازهٔ تقویمی است`}</p>)}
          <p className="mt-1">اعداد نسبی اختلاف بازده با بازار یا صنعت در واحد درصد هستند، نه بازده خود سهم.</p>
        </div>
      )}

      <div className="rounded-xl bg-gray-50/70 dark:bg-gray-900/40 p-2.5 text-[11px] text-gray-600 dark:text-gray-300 tabular-nums">
        <span className="font-bold text-gray-700 dark:text-gray-200">
          امتیاز مشاهده‌شدهٔ آزمایشی
        </span>{" "}
        = {num(q)} + {num(v)} + {num(t)} = <b>{num(s.score)}</b> از{" "}
        {num(s.score_ceiling, 0)} — مجموع سه امتیاز مشاهده‌شدهٔ رسمی (بدون تقسیم
        بر پوشش، بدون بازتوزیع وزن مفقود).
        <div className="mt-1">
          سقف عملی این نماد با دادهٔ فعلی: <b>{num(s.practical_ceiling, 0)}</b>
          {s.coverage_min != null && <> (کمینهٔ پوشش {pct(s.coverage_min)})</>} —
          تفاوت آن با ۱۰۰ از عوامل محاسبه‌نشده است و به‌تنهایی ضعف عملکرد نیست.
        </div>
        <div className="mt-1">
          کیفیت پوشش امتیاز: <b>{s.score_confidence_label}</b>.{" "}
          <span
            className={
              s.full_coverage
                ? "text-emerald-700 dark:text-emerald-300"
                : "text-amber-700 dark:text-amber-300"
            }
          >
            {s.comparability_label}
          </span>
        </div>
        <div className="mt-1 text-gray-500 dark:text-gray-400">
          <b>تحلیل حساسیت (غیررسمی، فقط برای سنجش اثر پوشش):</b> اگر وزن
          پوشش‌داده‌شدهٔ هر محور با بیشترین پوشش مشاهده‌شده یکسان می‌شد، رتبهٔ این
          نماد <b>{s.sensitivity_rank}</b> می‌شد (
          {s.rank_shift === 0
            ? "بدون تغییر رتبه"
            : `${s.rank_shift > 0 ? "+" : ""}${s.rank_shift} رتبه`}
          ). این عدد امتیاز رسمی نیست و مبنای تصمیم قرار نمی‌گیرد.
        </div>
      </div>

      <div className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 p-2.5">
        <p className="font-bold text-gray-700 dark:text-gray-200 mb-1">
          دلیل گروه‌بندی
        </p>
        <p className="text-gray-600 dark:text-gray-300 leading-5">{s.group_reason}</p>
      </div>

      {s.why.length > 0 && (
        <div className="rounded-xl border border-emerald-200/60 dark:border-emerald-900/40 bg-emerald-50/40 dark:bg-emerald-900/10 p-2.5">
          <p className="font-bold text-emerald-700 dark:text-emerald-300 mb-1">
            چرا این نماد؟
          </p>
          <ul className="list-disc pr-4 space-y-0.5 text-emerald-800/90 dark:text-emerald-200/90">
            {s.why.map((w, i) => (
              <li key={i} className="leading-5">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {s.careful.length > 0 && (
        <div className="rounded-xl border border-amber-200/60 dark:border-amber-900/40 bg-amber-50/40 dark:bg-amber-900/10 p-2.5">
          <p className="font-bold text-amber-700 dark:text-amber-300 mb-1">
            چرا ممکن است انتخاب خوبی نباشد؟
          </p>
          <ul className="list-disc pr-4 space-y-0.5 text-amber-800/90 dark:text-amber-200/90">
            {s.careful.map((w, i) => (
              <li key={i} className="leading-5">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      {s.review_when.length > 0 && (
        <div className="rounded-xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/40 dark:bg-sky-900/10 p-2.5">
          <p className="font-bold text-sky-700 dark:text-sky-300 mb-1">
            چه زمانی ارزش بررسی مجدد دارد؟
          </p>
          <ul className="list-disc pr-4 space-y-0.5 text-sky-800/90 dark:text-sky-200/90">
            {s.review_when.map((w, i) => (
              <li key={i} className="leading-5">
                {w}
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 text-[10px]">
        <span className="px-2 py-0.5 rounded-full ring-1 ring-gray-300/60 dark:ring-gray-600/50 text-gray-600 dark:text-gray-300">
          گروه تصمیم: {s.board_group_label}
        </span>
        <span className="px-2 py-0.5 rounded-full ring-1 ring-gray-300/60 dark:ring-gray-600/50 text-gray-600 dark:text-gray-300">
          داده: {s.confidence_label}
        </span>
        <span className="px-2 py-0.5 rounded-full ring-1 ring-gray-300/60 dark:ring-gray-600/50 text-gray-600 dark:text-gray-300">
          دروازه ریسک: {s.risk_gate_label}
        </span>
        {s.conditional && (
          <span className="px-2 py-0.5 rounded-full bg-amber-500/15 ring-1 ring-amber-500/30 text-amber-700 dark:text-amber-300">
            قید کیفیت اقتصادی
          </span>
        )}
        {s.negative_operating_profit && (
          <span className="px-2 py-0.5 rounded-full bg-rose-500/15 ring-1 ring-rose-500/30 text-rose-700 dark:text-rose-300">
            سود عملیاتی منفی
          </span>
        )}
      </div>

      {s.conditional && s.conditional_reasons.length > 0 && (
        <div className="rounded-xl bg-amber-50/60 dark:bg-amber-900/10 p-2.5 text-[11px] text-amber-800 dark:text-amber-200">
          <b>قیدهای کیفیت:</b> {s.conditional_reasons.join("؛ ")}
        </div>
      )}
    </div>
  );
}

function RankedTable({
  rows,
  expanded,
  onToggle,
  watched,
  onWatch,
  detailed,
}: {
  rows: QvtRankedStock[];
  expanded: string | null;
  onToggle: (id: string) => void;
  watched: string[];
  onWatch: (id: string) => void;
  detailed: boolean;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-gray-200/60 dark:border-gray-700/40">
      <table className="w-full text-right text-[12px] border-collapse">
        <thead>
          <tr className="bg-gray-50/80 dark:bg-gray-800/60 text-gray-500 dark:text-gray-400 text-[11px]">
            <th className="px-2 py-2 font-medium">رتبهٔ امتیاز</th>
            <th className="px-2 py-2 font-medium">نماد</th>
            <th className="px-2 py-2 font-medium">امتیاز</th>
            {detailed && <>
            <th className="px-2 py-2 font-medium">بنیادی</th>
            <th className="px-2 py-2 font-medium">ارزندگی</th>
            <th className="px-2 py-2 font-medium">ورود</th>
            </>}
            <th className="px-2 py-2 font-medium">وضعیت بررسی</th>
            <th className="px-2 py-2 font-medium">دلیل اصلی</th>
            <th className="px-2 py-2 font-medium">ریسک مهم</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((s) => {
            const open = expanded === s.company_id;
            return (
              <Fragment key={s.company_id}>
                <tr
                  onClick={() => onToggle(s.company_id)}
                  className={`border-t border-gray-100 dark:border-gray-800 cursor-pointer transition-colors ${
                    open
                      ? "bg-indigo-50/50 dark:bg-indigo-900/10"
                      : "hover:bg-gray-50/70 dark:hover:bg-gray-800/40"
                  }`}
                >
                  <td className="px-2 py-2 tabular-nums text-gray-500 dark:text-gray-400">
                    {s.rank}
                  </td>
                  <td className="px-2 py-2">
                    <div className="flex items-center gap-1.5">
                      <button
                        type="button"
                        aria-label={`${watched.includes(s.company_id) ? "حذف از" : "افزودن به"} پیگیری: ${s.symbol}`}
                        aria-pressed={watched.includes(s.company_id)}
                        title="فهرست پیگیری در همین مرورگر ذخیره می‌شود"
                        onClick={(event) => { event.stopPropagation(); onWatch(s.company_id); }}
                        className="px-1 text-base text-amber-500 hover:text-amber-600"
                      >
                        {watched.includes(s.company_id) ? "★" : "☆"}
                      </button>
                      <span className="font-bold text-gray-800 dark:text-gray-100">
                        {s.symbol}
                      </span>
                      {s.critical && (
                        <span
                          title={s.critical_flags.join("؛ ")}
                          className="text-[9px] px-1.5 py-0.5 rounded-full bg-rose-500/15 text-rose-700 dark:text-rose-300 ring-1 ring-rose-500/30"
                        >
                          ریسک بحرانی
                        </span>
                      )}
                      {s.conditional && (
                        <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-500/15 text-amber-700 dark:text-amber-300">
                          مشروط
                        </span>
                      )}
                      <CoverageChip s={s} />
                      {detailed && <PeerGroupChip s={s} />}
                    </div>
                    <div className="text-[10px] text-gray-500 dark:text-gray-400">
                      {s.industry}
                    </div>
                  </td>
                  <td
                    title={`سقف عملی با عوامل محاسبه‌شده ${num(s.practical_ceiling, 0)} است: پوشش بنیادی ${num(s.q.covered_weight ?? 0, 0)} از ${num(s.q.max, 0)}، ارزندگی ${num(s.v.covered_weight ?? 0, 0)} از ${num(s.v.max, 0)} و ورود ${num(s.t.covered_weight ?? 0, 0)} از ${num(s.t.max, 0)}. عوامل فاقد داده، پیاده‌سازی یا مجوز محاسبه در امتیاز سهم ندارند؛ این تفاوت به‌تنهایی ضعف شرکت نیست.`}
                    className={`px-2 py-2 tabular-nums font-bold ${scoreTone(s.score)}`}
                  >
                    {num(s.score)}
                    {detailed && <span className="text-[9px] font-normal text-gray-500 dark:text-gray-400">
                      {" "}
                      / {num(s.practical_ceiling, 0)}
                    </span>}
                  </td>
                  {detailed && [s.q, s.v, s.t].map((axis, i) => (
                    <td key={i} className="px-2 py-2 tabular-nums whitespace-nowrap text-gray-700 dark:text-gray-200" title={`امتیاز مشاهده‌شده؛ پوشش ${pct(axis.coverage_ratio)} از وزن ${num(axis.max, 0)}`}>
                      {num(axis.points)} <span className="text-[9px] text-gray-400">/ {num(axis.covered_weight, 0)}</span>
                      <div className="text-[9px] text-gray-400">پوشش {pct(axis.coverage_ratio)}</div>
                    </td>
                  ))}
                  <td className="px-2 py-2">
                    <span
                      className={`text-[10px] px-2 py-0.5 rounded-full ring-1 ${
                        rankStatusTone[s.status] ??
                        "ring-gray-300 text-gray-600 dark:text-gray-300"
                      }`}
                    >
                      {s.status_label}
                    </span>
                  </td>
                  <td className="px-2 py-2 text-gray-600 dark:text-gray-300 leading-5 max-w-[280px]">
                    <span title={s.main_reason}>{s.main_reason?.split(":")[0] || "—"}</span>
                  </td>
                  <td className="px-2 py-2 text-amber-700/90 dark:text-amber-300/90 leading-5 max-w-[260px]">
                    <span className="line-clamp-3" title={s.main_risk}>{briefRisk(s)}</span>
                  </td>
                </tr>
                {open && (
                  <tr className="bg-gray-50/40 dark:bg-gray-900/20">
                    <td colSpan={detailed ? 9 : 6} className="p-0">
                      {s.critical && (
                        <div className="mx-3 mt-3 rounded-xl bg-rose-50/70 dark:bg-rose-900/15 border border-rose-200/60 dark:border-rose-900/40 p-2.5 text-[11px] text-rose-700 dark:text-rose-300">
                          <b>هشدار بحرانی:</b> {s.critical_flags.join("؛ ")}
                        </div>
                      )}
                      <DetailPanel s={s} />
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function PortfolioReview({
  data,
  portfolio,
}: {
  data: QvtRankingResponse;
  portfolio: PortfolioSummary | null;
}) {
  const byId = useMemo(() => {
    const m = new Map<string, QvtRankedStock>();
    for (const s of data.ranked) m.set(s.company_id, s);
    return m;
  }, [data.ranked]);
  const bySymbol = useMemo(() => {
    const m = new Map<string, QvtRankedStock>();
    for (const s of data.ranked) m.set(s.symbol, s);
    return m;
  }, [data.ranked]);
  const unscoredSet = useMemo(
    () => new Set(data.unscored.map((u) => u.company_id)),
    [data.unscored],
  );

  const holdings = portfolio?.holdings ?? [];

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-sky-200/60 dark:border-sky-900/40 bg-sky-50/50 dark:bg-sky-900/10 p-3 text-[11px] text-sky-800 dark:text-sky-200 leading-5">
        این بخش برای «نگهداری یا بررسی فروش» سهم‌های موجود در سبد است. امتیاز پایین
        به‌تنهایی سیگنال فروش قطعی نیست و امتیاز بالا هم به‌تنهایی دلیل نگهداری
        نیست؛ تصمیم نهایی با توجه به هدف و افق سرمایه‌گذاری شماست.
      </div>

      {holdings.length === 0 ? (
        <p className="text-sm text-gray-500 dark:text-gray-400 px-1">
          سبدی ثبت نشده است. پس از افزودن سهم در صفحهٔ «پورتفولیو»، اینجا وضعیت
          QVT هر سهم و راهنمای نگهداری/بررسی فروش نمایش داده می‌شود.
        </p>
      ) : (
        <div className="overflow-x-auto rounded-2xl border border-gray-200/60 dark:border-gray-700/40">
          <table className="w-full text-right text-[12px] border-collapse">
            <thead>
              <tr className="bg-gray-50/80 dark:bg-gray-800/60 text-gray-500 dark:text-gray-400 text-[11px]">
                <th className="px-2 py-2 font-medium">نماد</th>
                <th className="px-2 py-2 font-medium">وضعیت سود</th>
                <th className="px-2 py-2 font-medium">امتیاز مشاهده‌شده</th>
                <th className="px-2 py-2 font-medium">وضعیت بررسی</th>
                <th className="px-2 py-2 font-medium">راهنمای نگهداری</th>
              </tr>
            </thead>
            <tbody>
              {holdings.map((h) => {
                const s = byId.get(h.company_id) ?? bySymbol.get(h.symbol ?? "");
                const inUniverse = s != null || unscoredSet.has(h.company_id);
                let guide: string;
                let tone = "text-gray-600 dark:text-gray-300";
                if (!inUniverse) {
                  guide =
                    "این نماد در جامعهٔ Q/V/T این snapshot نیست؛ ارزیابی QVT برایش معنا ندارد — به‌صورت دستی بررسی شود.";
                  tone = "text-gray-500 dark:text-gray-400";
                } else if (!s) {
                  guide =
                    "دادهٔ کافی برای امتیاز معتبر نیست؛ نگهداری با احتیاط و بررسی دستی.";
                  tone = "text-gray-500 dark:text-gray-400";
                } else if (s.status === "buy_review") {
                  guide = "نگهداری و بررسی؛ ترکیب بنیادی/ارزندگی/ورود قابل دفاع است.";
                  tone = "text-emerald-700 dark:text-emerald-300";
                } else if (s.status === "wait") {
                  guide =
                    "نگهداری و پایش؛ منتظر بهترشدن شرایط (ورود/ارزندگی/رفع قید).";
                  tone = "text-amber-700 dark:text-amber-300";
                } else {
                  guide =
                    "بررسی فروش/کاهش وزن قابل بررسی است — ولی امتیاز پایین به‌تنهایی سیگنال فروش قطعی نیست.";
                  tone = "text-rose-700 dark:text-rose-300";
                }
                return (
                  <tr
                    key={h.company_id}
                    className="border-t border-gray-100 dark:border-gray-800"
                  >
                    <td className="px-2 py-2 font-bold text-gray-800 dark:text-gray-100">
                      {h.symbol || h.company_name}
                    </td>
                    <td
                      className={`px-2 py-2 tabular-nums ${
                        h.gain_pct >= 0
                          ? "text-emerald-600 dark:text-emerald-400"
                          : "text-rose-600 dark:text-rose-400"
                      }`}
                    >
                      {num(h.gain_pct)}%
                    </td>
                    <td className="px-2 py-2 tabular-nums">
                      {s ? (
                        <span className={`font-bold ${scoreTone(s.score)}`}>
                          {num(s.score)} <span className="text-[9px] text-gray-400">/ {num(s.practical_ceiling, 0)}</span>
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className="px-2 py-2">
                      {s ? (
                        <span
                          className={`text-[10px] px-2 py-0.5 rounded-full ring-1 ${
                            rankStatusTone[s.status] ?? ""
                          }`}
                        >
                          {s.status_label}
                        </span>
                      ) : (
                        <span className="text-[10px] text-gray-400">بدون امتیاز</span>
                      )}
                    </td>
                    <td className={`px-2 py-2 leading-5 ${tone}`}>{guide}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function UnscoredTable({ rows }: { rows: QvtUnscoredStock[] }) {
  const [q, setQ] = useState("");
  const [readyOnly, setReadyOnly] = useState(false);
  const readyCount = rows.filter((row) => row.q.eligible && row.v.eligible).length;
  const filtered = useMemo(() => {
    const t = q.trim();
    return rows.filter(
      (r) => (!t || r.symbol.includes(t) || r.industry.includes(t)) && (!readyOnly || (r.q.eligible && r.v.eligible)),
    );
  }, [rows, q, readyOnly]);

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-800/30 p-3 text-[11px] text-gray-600 dark:text-gray-300 leading-5">
        امتیاز کامل این نمادها هنوز قابل محاسبه نیست. امتیاز بنیادی و ارزندگیِ موجود
        جدا نمایش داده می‌شود؛ علت نقص هر نماد در ستون «دلیل» آمده است.
      </div>
      <button type="button" aria-pressed={readyOnly} onClick={() => setReadyOnly((value) => !value)} className={`rounded-xl px-3 py-2 text-xs ring-1 ${readyOnly ? "bg-indigo-600 text-white ring-indigo-600" : "bg-white dark:bg-gray-800 text-gray-600 dark:text-gray-200 ring-gray-200 dark:ring-gray-700"}`}>
        {readyOnly ? "نمایش همهٔ موارد ناقص" : `بنیادی و ارزندگی آماده؛ ورود ناقص (${readyCount})`}
      </button>
      {readyOnly && <p className="text-xs text-amber-700 dark:text-amber-300 leading-5">این شرکت‌ها دادهٔ کافی برای بنیادی و ارزندگی دارند، اما شرایط ورودشان هنوز قابل ارزیابی نیست.</p>}
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="جست‌وجوی نماد یا صنعت…"
        className="w-full max-w-xs text-[12px] px-3 py-2 rounded-xl border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-900/40 text-gray-700 dark:text-gray-200 outline-none focus:ring-2 focus:ring-indigo-500/30"
      />
      <div className="overflow-x-auto rounded-2xl border border-gray-200/60 dark:border-gray-700/40 max-h-[560px] overflow-y-auto">
        <table className="w-full text-right text-[12px] border-collapse">
          <thead className="sticky top-0">
            <tr className="bg-gray-50/95 dark:bg-gray-800/95 text-gray-500 dark:text-gray-400 text-[11px]">
              <th className="px-2 py-2 font-medium">نماد</th>
              <th className="px-2 py-2 font-medium">صنعت</th>
              <th className="px-2 py-2 font-medium">بنیادی</th>
              <th className="px-2 py-2 font-medium">ارزندگی</th>
              <th className="px-2 py-2 font-medium">محورهای دارای نقص</th>
              <th className="px-2 py-2 font-medium">دلیل</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((u) => (
              <tr
                key={u.company_id}
                className="border-t border-gray-100 dark:border-gray-800"
              >
                <td className="px-2 py-1.5 font-bold text-gray-700 dark:text-gray-200">
                  {u.symbol}
                </td>
                <td className="px-2 py-1.5 text-gray-500 dark:text-gray-400">
                  {u.industry}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300" title={`پوشش: ${pct(u.q.coverage_ratio)}`}>
                  {u.q.points == null ? "—" : `${num(u.q.points)} / ${num(u.q.max, 0)}`}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-600 dark:text-gray-300" title={`پوشش: ${pct(u.v.coverage_ratio)}`}>
                  {u.v.points == null ? "—" : `${num(u.v.points)} / ${num(u.v.max, 0)}`}
                </td>
                <td className="px-2 py-1.5 tabular-nums text-gray-500 dark:text-gray-400">
                  {u.blocking_axes.map((axis) => ({Q: "بنیادی", V: "ارزندگی", T: "شرایط ورود"}[axis] || axis)).join("، ")}
                </td>
                <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300 leading-5">
                  {u.reason_label}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-2 py-4 text-center text-gray-500 dark:text-gray-400"
                >
                  موردی یافت نشد.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export default function QvtRankingPage() {
  const [data, setData] = useState<QvtRankingResponse | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("ranked");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState("all");
  const [industry, setIndustry] = useState("");
  const [sortAxis, setSortAxis] = useState("review");
  const [coverageProfile, setCoverageProfile] = useState("");
  const [detailed, setDetailed] = useState(false);
  const [paper, setPaper] = useState<QvtPaperSummary | null>(null);
  const [paperError, setPaperError] = useState<string | null>(null);
  const refreshPaper = () => {
    setPaperError(null);
    fetchQvtV2Paper().then(setPaper).catch((e: Error) => setPaperError(e.message));
  };
  useEffect(() => {
    let alive = true;
    fetchQvtV2Paper().then((value) => { if (alive) setPaper(value); })
      .catch((e: Error) => { if (alive) setPaperError(e.message); });
    return () => { alive = false; };
  }, []);
  const [watchStorageKey] = useState(() => {
    try {
      const token = localStorage.getItem("token");
      const username = token ? jwtDecode<{ username?: string }>(token).username : undefined;
      return `qvt-ranking-watchlist-v1:${encodeURIComponent(username || "preview")}`;
    } catch { return "qvt-ranking-watchlist-v1:preview"; }
  });
  const [watched, setWatched] = useState<string[]>(() => {
    try {
      const saved: unknown = JSON.parse(localStorage.getItem(watchStorageKey) || "[]");
      return Array.isArray(saved) ? saved.filter((id): id is string => typeof id === "string") : [];
    } catch { return []; }
  });

  useEffect(() => {
    try { localStorage.setItem(watchStorageKey, JSON.stringify(watched)); } catch { /* storage may be disabled */ }
  }, [watched, watchStorageKey]);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const r = await fetchQvtV2Ranking();
        if (!alive) return;
        setData(r);
      } catch (e: any) {
        if (alive) setError(e?.message || "خطا در دریافت رتبه‌بندی");
      } finally {
        if (alive) setLoading(false);
      }
      try {
        const p = await getPortfolio();
        if (alive) setPortfolio(p);
      } catch {
        /* سبد اختیاری است؛ خطای آن صفحه را نمی‌شکند */
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  const matches = useMemo(() => {
    if (!data) return [];
    const normalized = (text: string) => text.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/\u200c/g, "").trim();
    const term = normalized(query);
    return data.ranked.filter((stock) =>
      (!term || normalized(`${stock.symbol} ${stock.industry}`).includes(term)) &&
      (!industry || stock.industry === industry) &&
      (!coverageProfile || factorProfile(stock) === coverageProfile) &&
      (filter === "all" || (filter === "watched" ? watched.includes(stock.company_id) : stock.status === filter)))
      .sort((a, b) => {
        if (sortAxis === "review") {
          const priority = (s: QvtRankedStock) => {
            if (s.critical || s.negative_operating_profit) return 4;
            if (s.status === "weak") return 3;
            if (s.status === "buy_review" && !s.conditional) return 0;
            return s.conditional ? 2 : 1;
          };
          return priority(a) - priority(b) || b.score - a.score || a.rank - b.rank;
        }
        const value = (s: QvtRankedStock) => sortAxis === "score" ? s.score : s[sortAxis as "q" | "v" | "t"].points ?? -Infinity;
        return value(b) - value(a) || a.rank - b.rank;
      });
  }, [data, query, industry, filter, watched, sortAxis, coverageProfile]);
  const visible = showAll || query || industry || filter !== "all" ? matches : matches.slice(0, 10);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh] text-gray-500 dark:text-gray-400 text-sm">
        در حال بارگذاری رتبه‌بندی…
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="rounded-2xl border border-rose-200/60 dark:border-rose-900/40 bg-rose-50/60 dark:bg-rose-900/10 p-4 text-rose-700 dark:text-rose-300 text-sm">
        {error || "رتبه‌بندی در دسترس نیست."}
      </div>
    );
  }

  const u = data.universe;
  const profiles = [...new Map(data.ranked.filter((s) => s.q.scored_factors).map((s) => [factorProfile(s), s])).entries()];
  const buyCount = data.ranked.filter((stock) => stock.status === "buy_review").length;
  const holdingIds = new Set((portfolio?.holdings ?? []).map((holding) => holding.company_id));
  const holdingSymbols = new Set((portfolio?.holdings ?? []).map((holding) => holding.symbol));
  const attentionCount = data.ranked.filter((stock) =>
    (holdingIds.has(stock.company_id) || holdingSymbols.has(stock.symbol)) && (stock.status === "weak" || stock.critical)).length;

  return (
    <div dir="rtl" className="space-y-4">
      <div className="rounded-2xl bg-indigo-600 p-4 text-white">
        <h1 className="text-base font-bold">خلاصهٔ بررسی سرمایه‌گذاری</h1>
        <p className="mt-2 text-sm leading-6">
          {buyCount > 0 ? `${buyCount} نماد برای بررسی خرید پیدا شده است.` : "فعلاً هیچ نمادی شرایط بررسی خرید را کامل ندارد."}
          {attentionCount > 0 && ` ${attentionCount} سهم در سبد شما نیازمند بررسی بیشتر است.`}
        </p>
        <p className="mt-1 text-xs text-indigo-100 leading-5">
          رتبه‌ها برای اولویت بررسی‌اند. با ستاره، سهم‌های موردنظرتان را برای مراجعهٔ بعدی نگه دارید.
        </p>
      </div>
      {(data.freshness?.status !== "same_day" || (data.data_dates?.market_data_as_of && data.data_dates.market_data_as_of !== data.freshness?.today)) && (
        <div className="rounded-xl border border-amber-200 dark:border-amber-900 bg-amber-50 dark:bg-amber-900/15 p-3 text-xs text-amber-800 dark:text-amber-200 leading-5">
          مبنای رتبه‌بندی: {data.freshness?.as_of_date || data.as_of}.
          {data.freshness?.age_calendar_days != null && data.freshness.age_calendar_days > 0 && ` این بسته ${data.freshness.age_calendar_days} روز تقویمی قبل است.`}
          {data.data_dates?.market_data_as_of && ` تاریخ قیمت مبنای ارزندگی: ${data.data_dates.market_data_as_of}.`}
          {data.data_dates?.timing_market_data_as_of && ` تاریخ تاریخچهٔ شرایط ورود: ${data.data_dates.timing_market_data_as_of}.`}
          {" "}قیمت یا گزارش جدیدتر ممکن است نتیجه را تغییر دهد.
        </div>
      )}
      {/* نوار اعلامیهٔ اجباری نسخهٔ آزمایشی */}
      <button type="button" onClick={() => setTab("paper")} className="w-full text-right rounded-xl border border-indigo-200 dark:border-indigo-900 p-3 text-xs text-indigo-700 dark:text-indigo-200 leading-5">
        <b>بررسی عملکرد مدل:</b> {paper?.historical ? "نتیجهٔ آزمون تاریخی آماده است" : paper?.observer?.enabled === false ? "پایش آینده غیرفعال است" : paper?.status_label || "در حال آماده‌سازی"} — مشاهدهٔ نتیجه
      </button>
      <div className="rounded-2xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/70 dark:bg-amber-900/15 p-3">
        <p className="text-[12px] font-bold text-amber-800 dark:text-amber-300">
          {data.disclaimer || FALLBACK_DISCLAIMER}
        </p>
        <details className="text-[11px] text-amber-700/90 dark:text-amber-300/80 mt-1 leading-5">
          <summary className="cursor-pointer">معنای امتیاز و محدودیت‌های مقایسه</summary>
          <p className="mt-1">{data.not_a_signal}</p>
        </details>
      </div>

      {/* نوار بستهٔ آزمایشی ۲-ک-۱۳ (فقط وقتی QVT_RANKING_BUNDLE_DIR فعال است) */}
      <details className="rounded-2xl border border-gray-200 dark:border-gray-700 p-3 text-xs text-gray-600 dark:text-gray-300">
        <summary className="cursor-pointer">اطلاعات داده و روش امتیازدهی</summary>
        <div className="mt-3 space-y-3">
      {data.experimental_bundle?.active && (
        <div className="rounded-2xl border border-sky-300/70 dark:border-sky-800/50 bg-sky-50/70 dark:bg-sky-900/15 p-3">
          <p className="text-[12px] font-bold text-sky-800 dark:text-sky-300">
            پوشش تکمیل‌شده با اطلاعات کدال
          </p>
          <p className="text-[11px] text-sky-700/90 dark:text-sky-300/80 mt-1 leading-5">
            {data.experimental_bundle.note}
          </p>
        </div>
      )}

      {/* خلاصهٔ بالای صفحه */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-500 dark:text-gray-400">
            نمادهای امتیازدار
          </p>
          <p className="text-xl font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
            {u.n_scored}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-500 dark:text-gray-400">نیازمند تکمیل داده</p>
          <p className="text-xl font-bold tabular-nums text-gray-500 dark:text-gray-400">
            {u.n_unscored}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-500 dark:text-gray-400">نمادهای تحت بررسی</p>
          <p className="text-xl font-bold tabular-nums text-gray-700 dark:text-gray-200">
            {u.n_all_artifacts}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-500 dark:text-gray-400">تاریخ دادهٔ رتبه‌بندی</p>
          <p className="text-sm font-bold tabular-nums text-gray-700 dark:text-gray-200 mt-1">
            {data.as_of}
          </p>
        </div>
      </div>

      <details className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-3 text-[11px] text-gray-500 dark:text-gray-400 leading-5">
        <summary className="cursor-pointer font-bold text-gray-700 dark:text-gray-200">روش محاسبهٔ امتیاز</summary>
        <p className="mt-2">
        {data.score_contract?.formula}. {data.score_contract?.weights}.{" "}
        {data.score_contract?.full_coverage_meaning}.{" "}
        {data.score_contract?.no_redistribution}. سقف عملی هر نماد در ستون امتیاز
        نمایش داده می‌شود و «پوشش کامل» به‌معنای کامل بودن همهٔ ۴۰ امتیاز بنیادی نیست.
        </p>
      </details>

      <ComparabilityPanel data={data} />
        </div>
      </details>

      {/* تب‌ها */}
      <div className="flex flex-wrap gap-2 text-[12px]">
        {(
          [
            ["ranked", `رتبه‌بندی (${u.n_scored})`],
            ["portfolio", "بررسی سبد"],
            ["paper", "بررسی عملکرد مدل"],
            ["unscored", `بدون امتیاز معتبر (${u.n_unscored})`],
          ] as [Tab, string][]
        ).map(([k, label]) => (
          <button
            key={k}
            onClick={() => setTab(k)}
            className={`px-3 py-1.5 rounded-xl font-medium transition-colors ${
              tab === k
                ? "bg-indigo-600 text-white shadow-sm"
                : "bg-white/60 dark:bg-gray-800/40 text-gray-600 dark:text-gray-300 ring-1 ring-gray-200/70 dark:ring-gray-700/50 hover:bg-gray-100/70 dark:hover:bg-gray-700/40"
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === "ranked" && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2">
            <input aria-label="جست‌وجوی نماد" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="جست‌وجوی نماد یا صنعت…" className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs dark:text-gray-100" />
            <select aria-label="وضعیت بررسی" value={filter} onChange={(event) => setFilter(event.target.value)} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs dark:text-gray-100">
              <option value="all">همهٔ وضعیت‌ها</option><option value="watched">پیگیری‌های من ({watched.length})</option><option value="buy_review">بررسی خرید</option><option value="wait">انتظار</option><option value="weak">ضعیف / نیازمند بررسی</option>
            </select>
            <button type="button" aria-pressed={detailed} onClick={() => {
              setDetailed((value) => !value);
              if (detailed) { setSortAxis("review"); setCoverageProfile(""); setIndustry(""); }
            }} className="rounded-xl border border-gray-200 dark:border-gray-700 px-3 py-2 text-xs text-gray-600 dark:text-gray-300">{detailed ? "نمای ساده" : "فیلترها و ستون‌های بیشتر"}</button>
            {detailed && <>
            <select aria-label="مرتب‌سازی" value={sortAxis} onChange={(event) => setSortAxis(event.target.value)} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs dark:text-gray-100">
              <option value="review">ترتیب: اولویت بررسی</option><option value="score">ترتیب: امتیاز کل</option><option value="q">ترتیب: بنیادی</option><option value="v">ترتیب: ارزندگی</option><option value="t">ترتیب: شرایط ورود</option>
            </select>
            <select aria-label="مقایسه با عوامل یکسان" value={coverageProfile} onChange={(event) => setCoverageProfile(event.target.value)} className="max-w-sm rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs dark:text-gray-100">
              <option value="">همهٔ پوشش‌ها</option>
              {profiles.map(([key, s]) => <option key={key} value={key}>عوامل یکسان: بنیادی {num(s.q.covered_weight, 0)}، ارزندگی {num(s.v.covered_weight, 0)}، ورود {num(s.t.covered_weight, 0)}؛ بدون {(s.q.missing_factors ?? []).filter((f) => f.kind === "missing").map((f) => f.label).join("، ") || "نقص دادهٔ بنیادی"}</option>)}
            </select>
            <select aria-label="صنعت" value={industry} onChange={(event) => setIndustry(event.target.value)} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 px-3 py-2 text-xs dark:text-gray-100">
              <option value="">همهٔ صنایع</option>
              {[...new Set(data.ranked.map((stock) => stock.industry))].sort((a, b) => a.localeCompare(b, "fa")).map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
            </>}
          </div>
          {sortAxis === "review" && <p className="text-xs text-gray-500 dark:text-gray-400 px-1">
            ابتدا نمادهای قابل بررسیِ بدون قید کیفیت، سپس انتظار و موارد نیازمند بررسی بیشتر؛ در هر گروه، امتیاز بالاتر اول است. ستون رتبهٔ امتیاز، جایگاه عددی قبلی را نشان می‌دهد.
          </p>}
          {matches.length === 0 ? (
            <p className="text-sm text-gray-500 dark:text-gray-400">
              نمادی با این شرایط پیدا نشد.
            </p>
          ) : (
            <>
              <RankedTable
                rows={visible}
                expanded={expanded}
                onToggle={(id) => setExpanded((cur) => (cur === id ? null : id))}
                watched={watched}
                detailed={detailed}
                onWatch={(id) => setWatched((current) => current.includes(id) ? current.filter((item) => item !== id) : [...current, id])}
              />
              <p className="text-[11px] text-gray-500 dark:text-gray-400 px-1">
                برای دیدن جزئیات Q/V/T، دلیل، ریسک و شرط‌های بررسی مجدد، روی هر
                سهم کلیک کنید. امتیاز فقط «اولویت بررسی» است، نه توصیه خرید.
              </p>
              {matches.length > 10 && !query && !industry && filter === "all" && (
                <button
                  onClick={() => setShowAll((v) => !v)}
                  className="text-[12px] px-3 py-1.5 rounded-xl bg-white/60 dark:bg-gray-800/40 ring-1 ring-gray-200/70 dark:ring-gray-700/50 text-gray-600 dark:text-gray-300 hover:bg-gray-100/70 dark:hover:bg-gray-700/40"
                >
                  {showAll
                    ? "نمایش ۱۰ مورد اول"
                    : `نمایش همهٔ ${matches.length} نماد امتیازدار`}
                </button>
              )}
            </>
          )}
        </div>
      )}

      {tab === "portfolio" && (
        <PortfolioReview data={data} portfolio={portfolio} />
      )}

      {tab === "unscored" && <UnscoredTable rows={data.unscored} />}
      {tab === "paper" && <QvtPaperPanel data={paper} error={paperError} onRefresh={refreshPaper}
        sourceHashes={{ q: data.sources.q.sha256, v: data.sources.v.sha256, t: data.sources.t.sha256 }}
        sourceChanged={!!paper?.source_hashes && (["q", "v", "t"] as const).some((axis) => paper.source_hashes?.[axis] !== data.sources[axis].sha256)} />}
    </div>
  );
}
