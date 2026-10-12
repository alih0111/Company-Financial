import { Fragment, useEffect, useMemo, useState } from "react";
import {
  fetchQvtV2Ranking,
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

type Tab = "ranked" | "portfolio" | "unscored";

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

const scoreTone = (s: number) =>
  s >= 60
    ? "text-emerald-600 dark:text-emerald-400"
    : s >= 45
      ? "text-amber-600 dark:text-amber-400"
      : "text-rose-600 dark:text-rose-400";

// برچسب کوتاهِ کامل بودن داده — فقط «پوشش کامل» یا «پوشش جزئی ٪».
function CoverageChip({ s }: { s: QvtRankedStock }) {
  const full = s.full_coverage;
  const pctTxt = s.coverage_min != null ? `${Math.round(s.coverage_min * 100)}%` : "—";
  return (
    <span
      title={
        full
          ? "پوشش دادهٔ این نماد در هر سه محور با بیشترین پوشش مشاهده‌شده برابر است؛ امتیازش مستقیماً با نمادهای پوشش‌کامل مقایسه‌پذیر است."
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
      {full ? "پوشش کامل" : `پوشش جزئی ${pctTxt}`}
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
          <b>مقایسه‌پذیری امتیاز:</b> {ci.interpretation}
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
            دادهٔ مفقودِ همان عوامل رسمی می‌آید. همبستگی امتیاز با پوشش بنیادی{" "}
            {ci.spearman_score_vs_q_coverage.toFixed(3)} است (اثر ملایم ولی موجود).
            از {ci.n_scored} نماد، {ci.n_shift_gt5} نماد بیش از ۵ رتبه و{" "}
            {ci.n_shift_gt10} نماد بیش از ۱۰ رتبه جابه‌جا می‌شوند؛ فهرست ۱۰ نماد برتر
            پایدار است.
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
      <div className="flex items-center justify-between text-[10px] mt-1 text-gray-400 dark:text-gray-500 tabular-nums">
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
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
        <AxisBar label="بنیادی (Q)" axis={s.q} colorClass="bg-indigo-500" />
        <AxisBar label="ارزندگی (V)" axis={s.v} colorClass="bg-emerald-500" />
        <AxisBar label="شرایط ورود (T)" axis={s.t} colorClass="bg-cyan-500" />
      </div>

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
          تفاوت آن با ۱۰۰ صرفاً از دادهٔ مفقود است، نه ضعف عملکرد.
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
}: {
  rows: QvtRankedStock[];
  expanded: string | null;
  onToggle: (id: string) => void;
}) {
  return (
    <div className="overflow-x-auto rounded-2xl border border-gray-200/60 dark:border-gray-700/40">
      <table className="w-full text-right text-[12px] border-collapse">
        <thead>
          <tr className="bg-gray-50/80 dark:bg-gray-800/60 text-gray-500 dark:text-gray-400 text-[11px]">
            <th className="px-2 py-2 font-medium">رتبه</th>
            <th className="px-2 py-2 font-medium">نماد</th>
            <th className="px-2 py-2 font-medium">امتیاز مشاهده‌شده</th>
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
                      <PeerGroupChip s={s} />
                    </div>
                    <div className="text-[10px] text-gray-400 dark:text-gray-500">
                      {s.industry}
                    </div>
                  </td>
                  <td
                    title={`سقف عملی این نماد با دادهٔ فعلی ${num(s.practical_ceiling, 0)} است (نه ۱۰۰): ${s.full_coverage ? "پوشش کامل یعنی Q ۳۱ از ۴۰، V ۳۵ از ۳۵، T ۲۵ از ۲۵" : "بخشی از عوامل بنیادی دادهٔ مفقود دارند"}؛ تفاوت با ۱۰۰ فقط از دادهٔ مفقود ساختاری است، نه ضعف عملکرد.`}
                    className={`px-2 py-2 tabular-nums font-bold ${scoreTone(s.score)}`}
                  >
                    {num(s.score)}
                    <span className="text-[9px] font-normal text-gray-400 dark:text-gray-500">
                      {" "}
                      / {num(s.practical_ceiling, 0)}
                    </span>
                  </td>
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
                    {s.main_reason || "—"}
                  </td>
                  <td className="px-2 py-2 text-amber-700/90 dark:text-amber-300/90 leading-5 max-w-[260px]">
                    {s.main_risk || "—"}
                  </td>
                </tr>
                {open && (
                  <tr className="bg-gray-50/40 dark:bg-gray-900/20">
                    <td colSpan={6} className="p-0">
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
        <p className="text-sm text-gray-400 dark:text-gray-500 px-1">
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
                          {num(s.score)} <span className="text-[9px] text-gray-400">/ ۱۰۰</span>
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
  const filtered = useMemo(() => {
    const t = q.trim();
    if (!t) return rows;
    return rows.filter(
      (r) => r.symbol.includes(t) || r.industry.includes(t),
    );
  }, [rows, q]);

  return (
    <div className="space-y-3">
      <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-800/30 p-3 text-[11px] text-gray-600 dark:text-gray-300 leading-5">
        این نمادها در این snapshot دادهٔ کافی و معتبر برای هر سه محور Q/V/T
        ندارند؛ برای آن‌ها امتیاز ساخته نمی‌شود (هیچ مقدار جعلی یا صفر فرض‌شده‌ای
        وجود ندارد). علت دقیق هر مورد در ستون «دلیل» آمده است.
      </div>
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
                <td className="px-2 py-1.5 tabular-nums text-gray-500 dark:text-gray-400">
                  {u.blocking_axes.join("، ")}
                </td>
                <td className="px-2 py-1.5 text-gray-600 dark:text-gray-300 leading-5">
                  {u.reason_label}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={4}
                  className="px-2 py-4 text-center text-gray-400 dark:text-gray-500"
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

  const visible = useMemo(() => {
    if (!data) return [];
    return showAll ? data.ranked : data.ranked.slice(0, 10);
  }, [data, showAll]);

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh] text-gray-400 dark:text-gray-500 text-sm">
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

  return (
    <div dir="rtl" className="space-y-4">
      {/* نوار اعلامیهٔ اجباری نسخهٔ آزمایشی */}
      <div className="rounded-2xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/70 dark:bg-amber-900/15 p-3">
        <p className="text-[12px] font-bold text-amber-800 dark:text-amber-300">
          {data.disclaimer || FALLBACK_DISCLAIMER}
        </p>
        <p className="text-[11px] text-amber-700/90 dark:text-amber-300/80 mt-1 leading-5">
          {data.not_a_signal}
        </p>
      </div>

      {/* نوار بستهٔ آزمایشی ۲-ک-۱۳ (فقط وقتی QVT_RANKING_BUNDLE_DIR فعال است) */}
      {data.experimental_bundle?.active && (
        <div className="rounded-2xl border border-sky-300/70 dark:border-sky-800/50 bg-sky-50/70 dark:bg-sky-900/15 p-3">
          <p className="text-[12px] font-bold text-sky-800 dark:text-sky-300">
            بستهٔ آزمایشی «تکمیل پوشش از کدال» (گام ۲-ک-۱۳)
          </p>
          <p className="text-[11px] text-sky-700/90 dark:text-sky-300/80 mt-1 leading-5">
            در این نمایش، محورهای Q و V روی دادهٔ بازپرکردهٔ صورت‌های مالی حسابرسی‌شدهٔ
            کدال بازمحاسبه شده‌اند و محور T همان آرتیفکت رسمیِ تغییرناپذیر است.
            اسنپ‌شات رسمی روی دیسک دست‌نخورده باقی است و با حذف متغیر محیطی، همین
            صفحه دقیقاً همان snapshot رسمی را نشان می‌دهد.
          </p>
        </div>
      )}

      {/* خلاصهٔ بالای صفحه */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-400 dark:text-gray-500">
            نمادهای دارای امتیاز مشاهده‌شده
          </p>
          <p className="text-xl font-bold tabular-nums text-emerald-600 dark:text-emerald-400">
            {u.n_scored}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-400 dark:text-gray-500">بدون دادهٔ معتبر</p>
          <p className="text-xl font-bold tabular-nums text-gray-500 dark:text-gray-400">
            {u.n_unscored}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-400 dark:text-gray-500">کل جامعهٔ آرتیفکت‌ها</p>
          <p className="text-xl font-bold tabular-nums text-gray-700 dark:text-gray-200">
            {u.n_all_artifacts}
          </p>
        </div>
        <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/30 p-3">
          <p className="text-[10px] text-gray-400 dark:text-gray-500">تاریخ snapshot</p>
          <p className="text-sm font-bold tabular-nums text-gray-700 dark:text-gray-200 mt-1">
            {data.as_of}
          </p>
        </div>
      </div>

      <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/50 dark:bg-gray-800/20 p-3 text-[11px] text-gray-500 dark:text-gray-400 leading-5">
        <b className="text-gray-700 dark:text-gray-200">
          امتیاز مشاهده‌شدهٔ آزمایشی از چه ساخته می‌شود:
        </b>{" "}
        {data.score_contract?.formula}. {data.score_contract?.weights}.{" "}
        {data.score_contract?.full_coverage_meaning}.{" "}
        {data.score_contract?.no_redistribution}. سقف عملی هر نماد در ستون امتیاز
        نمایش داده می‌شود و «پوشش کامل» به‌معنای کامل بودن همهٔ ۴۰ امتیاز بنیادی نیست.
      </div>

      <ComparabilityPanel data={data} />

      {/* تب‌ها */}
      <div className="flex flex-wrap gap-2 text-[12px]">
        {(
          [
            ["ranked", `رتبه‌بندی (${u.n_scored})`],
            ["portfolio", "بررسی سبد"],
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
          {!data.ranked.some((r) => r.status === "buy_review") && (
            <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-800/30 p-3 text-[11px] text-gray-600 dark:text-gray-300 leading-5">
              در این snapshot هیچ نمادی به وضعیت «قابل بررسی برای خرید» نرسیده است —
              این نتیجهٔ صادقانهٔ شواهد است و برای پرکردن فهرست، نماد یا امتیاز
              ساختگی اضافه نمی‌شود. جدول زیر نامزدهای دارای دادهٔ معتبر را بر اساس
              امتیاز مرتب می‌کند تا سریع‌تر بررسی شوند (بیشتر در وضعیت «انتظار»).
            </div>
          )}
          {data.ranked.length === 0 ? (
            <p className="text-sm text-gray-400 dark:text-gray-500">
              در این snapshot هیچ نمادی دادهٔ کافی برای امتیاز معتبر ندارد.
            </p>
          ) : (
            <>
              <RankedTable
                rows={visible}
                expanded={expanded}
                onToggle={(id) => setExpanded((cur) => (cur === id ? null : id))}
              />
              <p className="text-[11px] text-gray-400 dark:text-gray-500 px-1">
                برای دیدن جزئیات Q/V/T، دلیل، ریسک و شرط‌های بررسی مجدد، روی هر
                سهم کلیک کنید. امتیاز فقط «اولویت بررسی» است، نه توصیه خرید.
              </p>
              {data.ranked.length > 10 && (
                <button
                  onClick={() => setShowAll((v) => !v)}
                  className="text-[12px] px-3 py-1.5 rounded-xl bg-white/60 dark:bg-gray-800/40 ring-1 ring-gray-200/70 dark:ring-gray-700/50 text-gray-600 dark:text-gray-300 hover:bg-gray-100/70 dark:hover:bg-gray-700/40"
                >
                  {showAll
                    ? "نمایش ۱۰ مورد برتر"
                    : `نمایش همهٔ ${data.ranked.length} نماد امتیازدار`}
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
    </div>
  );
}
