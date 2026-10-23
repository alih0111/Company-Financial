import { useEffect, useMemo, useState } from "react";
import { assessMarketState, estimateTarget, sessionCountLabel } from "./paperPortfolioView.js";

type Candidate = { symbol: string; company_id: string; rank: number; score: number; coverage: number; price_date: string | null; last_price_rial: number | null };
type PaperState = {
  account_id: string; initial_capital_toman: number; cash_toman: number; created_at_utc: string; created_at_tehran: string;
  contract: { id: string; sha256: string; model: string; weight_id: string; target_count: number; exit_rank: number; review_cadence_sessions: number };
  ranking: { dataset_id: string; artifact_sha256: string; evaluation_date: string; status: string; p1_scored_count: number; top_candidate: Candidate | null };
  holdings: Array<{ symbol: string; company_id?: string; shares: number; purchase_price_toman: number; purchase_price_rial: number; purchase_at_utc: string; cost_basis_toman: number; fee_toman: number; last_price_rial: number; last_price_date: string; market_value_toman: number; unrealized_pnl_toman: number; price_status: string }>;
  event_log: Array<{ event_id: string; type: string; at_utc: string; reason: string; details: string }>;
  accounting: { holdings_value_toman: number; total_value_toman: number; profit_loss_toman: number; last_price_status: string };
  active_decision?: { decision_id: string; decided_at_utc: string; decision_local_date: string; candidate: Candidate; ranking: { dataset_id: string; evaluation_date: string; status: string; artifact_sha256: string; scored: number; universe: number }; execution_rules: { rule_id: string; sha256: string } };
  paper_order?: { order_id: string; decision_id: string; symbol: string; company_id: string; status: string; created_at_utc: string; designated_execution_session: string | null; designated_execution_price_rial: number | null; expires_after_official_sessions: number; eligible_session_count_observed: number; fill_event_id: string | null; waiting_reason: string; queue_limitation: string; source_manifest_sha256: string };
};
type PaperCheck = {
  checked_at_utc: string; fill_recorded: boolean; latest_official_completed_session: string | null; candidate_latest_positive_price_date: string | null;
  candidate_post_decision_quotes: string[]; decision: NonNullable<PaperState["active_decision"]>; order: NonNullable<PaperState["paper_order"]>;
  first_eligible_session: string | null; calendar_retrieved_at_utc?: string | null; calendar_local_through: string | null; execution_attempt_status?: string;
  blockers: string[]; barriers?: Array<{ id: string; state: string; title: string; details: string }>;
  required_data: string[]; cash_reconciliation: { initial_toman: number; cash_toman: number; holdings_count: number; holdings_value_toman: number; total_value_toman: number; profit_loss_toman: number; balanced: boolean };
};
type CycleSource = {
  state: string; latest_successful_retrieval_utc?: string; last_successful_retrieval_utc?: string; latest_body_received_at_utc?: string;
  latest_data_date?: string; latest_complete_session?: string; coverage?: number | { completed?: number; universe?: number; failed?: number };
  coverage_universe?: number; companies_checked?: number; companies_new_reports?: number; companies_no_new_reports?: number; companies_failed?: number;
  pages_fetched?: number; pagination_complete?: boolean; search_window_from_min?: string; search_window_to_max?: string; identity_audit_count?: number;
  report_bodies_received?: number; documents_extracted?: number; document_admission_count?: number; extraction_errors?: number; report_body_errors?: number;
  archive_reuse?: { cached_report_count?: number; valid_bodies_reused?: number; incomplete_or_invalid_cached_bodies?: number; quarantined_invalid_responses?: number; missing_cached_bodies?: number; reprocessed_from_local_body?: number; fresh_report_metadata?: number; fresh_report_bodies_received_this_run?: number; retried_after_missing_or_invalid_body?: number };
  retry_after?: { attempts?: number; next_attempt_at_utc?: string; source_stopped?: boolean }; error?: string; ranking_admission?: string;
  coverage_from?: string; target_global_index?: number; local_calendar_computed_index_at_panel_end?: number; locked_panel_index?: number;
  locked_prefix_date_mapping_complete?: boolean; locked_prefix_extra_local_dates?: string[]; missing_locked_dates?: string[];
};
type LatestRanking = {
  artifact_id: string; artifact_sha256: string; evaluation_date: string; status: string; received_at_status: string;
  scored_count: { P1: number; P3: number }; universe_count: number;
  rows: Array<{ company_id: string; symbol: string; evaluation_date: string; methods: { P1: { rank: number; score: number; financial_factor_coverage: number } }; price_effective_date: string | null }>;
};
type CycleStatus = {
  run_id: string; status: string; status_fa?: string; started_at_utc: string; finished_at_utc: string;
  schedule?: { task_name: string; daily_local_time: string; timezone: string; state: string; window_requires_user_session?: boolean };
  decision?: { next_review: string }; paper_account?: { order_status: string; fill_recorded: boolean; reconciliation_balanced: boolean };
  data_sources?: { market?: CycleSource; calendar_for_order?: CycleSource; calendar_for_o00?: CycleSource; financial?: CycleSource; sales?: CycleSource };
  credential?: { state: string; task_identity_state: string; remote_validity: string; future_validity_guaranteed: boolean };
  blockers?: string[]; cycle_blockers?: string[]; stages?: Array<{ stage: string; status: string }>;
  stage_statuses?: Record<string, string>; ranking_input_admission?: { reason?: string };
};

const n = (v: number | null | undefined, digits = 0) => v == null ? "ثبت نشده" : new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v);
const d = (v: string | null | undefined) => v ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${v.slice(0, 10)}T00:00:00Z`)) : "ثبت نشده";
const tehranTime = (v: string | null | undefined) => v ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran" }).format(new Date(v)) : "ثبت نشده";
const verifiedCalendar = (source?: CycleSource) => source?.state === "verified" || source?.state === "verified_recent_window";
const stageNames: Record<string, string> = {
  market_prices_254: "دریافت بازار و تازگی", calendar_for_order: "تقویم سفارش", calendar_for_o00: "تاریخچهٔ O00",
  sales_factor_timing_calendar: "تقویم عامل فروش", financial_incremental_discovery: "کشف مالی", sales_incremental_discovery: "کشف فروش",
  codal_report_extraction: "استخراج سند", factor_input_preparation: "پذیرش عامل", ranking: "رتبه‌بندی P1/P3",
  decision: "موعد تصمیم", order_execution: "سفارش", valuation: "ارزش‌گذاری",
};
const stateNames: Record<string, string> = {
  source_error: "خطای دریافت منبع", confirmed_session_missing_data: "جلسه تأیید شده؛ قیمت آن دریافت نشده",
  calendar_verified_waiting: "تقویم تأیید شده؛ جلسهٔ واجد شرایط در دادهٔ موجود نیست",
  natural_weekly_closure: "انتظار طبیعی تعطیلی هفتگی؛ جلسهٔ بعد هنوز تأیید نشده",
  calendar_unknown: "وضعیت جلسه نامشخص است؛ تقویم ناقص است",
};
const orderNames: Record<string, string> = {
  PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE: "معلق؛ در انتظار شواهد نخستین جلسه",
  PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE: "اجرای فرضی ثبت‌شده با محدودیت صف",
  EXPIRED_NO_FILL: "منقضی‌شده؛ بدون خرید",
};

export default function PaperPortfolioTab() {
  const [state, setState] = useState<PaperState | null>(null);
  const [error, setError] = useState("");
  const [check, setCheck] = useState<PaperCheck | null>(null);
  const [checkError, setCheckError] = useState("");
  const [cycle, setCycle] = useState<CycleStatus | null>(null);
  const [latestRanking, setLatestRanking] = useState<LatestRanking | null>(null);
  const [rankingError, setRankingError] = useState("");

  useEffect(() => {
    const ctl = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/v12-36/paper-portfolio.json`, { signal: ctl.signal, cache: "no-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(`حساب آزمایشی بارگذاری نشد (HTTP ${r.status}).`); return r.json() as Promise<PaperState>; })
      .then((x) => {
        if (x.initial_capital_toman !== 100_000_000 || !x.created_at_utc || !x.contract?.sha256 || x.cash_toman + x.accounting.holdings_value_toman !== x.accounting.total_value_toman) throw new Error("منبع حساب آزمایشی ناقص یا ناسازگار است.");
        setState(x);
      }).catch((e) => { if (!ctl.signal.aborted) setError(e instanceof Error ? e.message : "خطای خواندن حساب آزمایشی."); });
    return () => ctl.abort();
  }, []);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/v12-38/paper-cycle-latest.json`, { signal: ctl.signal, cache: "no-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(`گزارش چرخه در دسترس نیست (HTTP ${r.status}).`); return r.json() as Promise<CycleStatus>; })
      .then(setCycle).catch(() => { if (!ctl.signal.aborted) setCycle(null); });
    return () => ctl.abort();
  }, []);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/v12-38/paper-account-check.json`, { signal: ctl.signal, cache: "no-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(`گزارش بررسی حساب در دسترس نیست (HTTP ${r.status}).`); return r.json() as Promise<PaperCheck>; })
      .then(setCheck).catch((e) => { if (!ctl.signal.aborted) setCheckError(e instanceof Error ? e.message : "گزارش بررسی حساب خوانده نشد."); });
    return () => ctl.abort();
  }, []);
  useEffect(() => {
    const ctl = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/v12-37/latest-ranking.json`, { signal: ctl.signal, cache: "no-cache" })
      .then(async (r) => { if (!r.ok) throw new Error(`رتبه‌بندی جاری در دسترس نیست (HTTP ${r.status}).`); return r.json() as Promise<LatestRanking>; })
      .then(setLatestRanking).catch((e) => { if (!ctl.signal.aborted) setRankingError(e instanceof Error ? e.message : "رتبه‌بندی جاری خوانده نشد."); });
    return () => ctl.abort();
  }, []);

  const selected = useMemo(() => {
    if (!state) return null;
    const row = latestRanking?.rows.find((x) => x.methods?.P1?.rank === 1) ?? null;
    if (!row) return state.ranking.top_candidate;
    const accountPrice = state.ranking.top_candidate;
    const matchingReference = accountPrice?.company_id === row.company_id && accountPrice.price_date === row.price_effective_date;
    return {
      symbol: row.symbol, company_id: row.company_id, rank: 1, score: row.methods.P1.score,
      coverage: row.methods.P1.financial_factor_coverage, price_date: matchingReference ? accountPrice.price_date : null,
      last_price_rial: matchingReference ? accountPrice.last_price_rial : null,
    };
  }, [state, latestRanking]);
  const target = useMemo(() => selected?.last_price_rial && state ? estimateTarget({ cashToman: state.cash_toman, priceRial: selected.last_price_rial }) : null, [selected, state]);
  const marketState = check ? assessMarketState({
    checkedAtUtc: check.checked_at_utc,
    lastConfirmedSession: check.latest_official_completed_session ?? check.candidate_latest_positive_price_date,
    latestQuoteDate: check.candidate_latest_positive_price_date,
    calendarVerified: verifiedCalendar(cycle?.data_sources?.calendar_for_order),
    sourceError: Boolean(cycle?.data_sources?.market?.error),
  }) : null;
  const orderCalendarVerified = verifiedCalendar(cycle?.data_sources?.calendar_for_order);
  const proposalDiffersFromDecision = Boolean(selected && state?.active_decision && (selected.company_id !== state.active_decision.candidate.company_id));
  const marketMessage = marketState ? ({
    natural_weekly_closure: "آخرین جلسهٔ تأییدشده چهارشنبه ۲۱ اکتبر است؛ بررسی جمعه با تعطیلی عادی هفتگی سازگار است. شنبه فقط نامزد جلسهٔ بعدی است و تقویم آن هنوز تأیید نشده.",
    calendar_unknown: "آخرین جلسهٔ تأییدشده قدیمی‌تر از روز بررسی است و تقویم برای تعیین جلسهٔ بعد کامل نیست.",
    confirmed_session_missing_data: `جلسهٔ ${d(marketState.missedSession)} تأیید شده، اما دادهٔ قیمت آن هنوز دریافت نشده است.`,
    source_error: "منبع دریافت بازار خطا داده است؛ این وضعیت به‌عنوان تعطیلی بازار نمایش داده نمی‌شود.",
    calendar_verified_waiting: "تقویم معتبر بررسی شد؛ در دادهٔ موجود جلسهٔ واجد شرایط پس از تصمیم دیده نمی‌شود.",
  }[marketState.state]) : "وضعیت جلسه هنوز قابل تعیین نیست.";
  const lastCheckResult = check ? (check.fill_recorded ? "اجرای فرضی طبق شواهد ثبت شده" : check.order.status === "EXPIRED_NO_FILL" ? "انقضای مستند؛ بدون خرید" : marketState ? stateNames[marketState.state] : "بررسی انجام شده؛ نتیجهٔ تقویم بارگذاری می‌شود") : checkError || "گزارش بررسی بارگذاری می‌شود";
  const stageRows = cycle?.stage_statuses ? Object.entries(cycle.stage_statuses) : [];

  return <section aria-labelledby="paper-title" className="space-y-4 rounded-2xl border-2 border-indigo-200 bg-white p-4 text-slate-900 dark:border-indigo-800 dark:bg-slate-800 dark:text-slate-100 sm:p-5">
    {error ? <p role="alert" className="rounded-xl bg-rose-50 p-3 text-sm text-rose-800">{error}</p> : !state ? <p role="status" className="text-sm">در حال خواندن حساب آزمایشی…</p> : <>
      <header className="space-y-3">
        <div><p className="text-xs font-bold text-indigo-700 dark:text-indigo-300">حساب مستقل · قرارداد حفظ‌شدهٔ P1/P3</p><h2 id="paper-title" className="mt-1 text-xl font-black">سبد کاغذی</h2>
          <p className="mt-2 text-sm leading-7" aria-live="polite">{marketMessage}</p></div>
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">مدل انتخاب‌شده</p><p className="mt-1 font-bold">P1 · valuation_0</p><p className="text-xs text-slate-600 dark:text-slate-300">مقایسه: P3 · w0</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">سفارش موجود</p><p className="mt-1 break-words text-sm font-bold">{orderNames[state.paper_order?.status ?? ""] ?? state.paper_order?.status ?? "وضعیت ثبت نشده"}</p><p className="text-xs">{state.paper_order?.symbol ?? "—"} · V12.38</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">دارایی واقعی حساب</p><p className="mt-1 font-bold">{n(state.accounting.total_value_toman)} تومان</p><p className="text-xs">نقد {n(state.cash_toman)} · سهم {n(state.holdings.length)}</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">آخرین جلسه / قیمت نامزد</p><p className="mt-1 font-bold">{d(check?.latest_official_completed_session)}</p><p className="text-xs">قیمت تا {d(check?.candidate_latest_positive_price_date)}</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">آخرین بررسی</p><p className="mt-1 text-sm font-bold">{tehranTime(check?.checked_at_utc)}</p><p className="text-xs">{lastCheckResult}</p></article>
        </div>
      </header>

      <section aria-labelledby="proposal-title" className="rounded-2xl border border-indigo-300 bg-indigo-50 p-4 text-indigo-950 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-100">
        <div className="flex flex-wrap items-center justify-between gap-2"><h3 id="proposal-title" className="text-lg font-black">سبد پیشنهادی — هنوز خرید نشده</h3><span className="rounded-full bg-white/80 px-3 py-1 text-xs font-bold dark:bg-slate-900">آخرین snapshot رتبه‌بندی · {latestRanking?.status ?? state.ranking.status}</span></div>
        {selected ? <>
          <p className="mt-2 text-sm leading-7"><b>{selected.symbol}</b> · رتبهٔ P1 {n(selected.rank)} · امتیاز {n(selected.score, 3)} · پوشش عامل‌های مالی {n(selected.coverage * 100, 1)}٪ · تاریخ رتبه‌بندی {d(latestRanking?.evaluation_date ?? state.ranking.evaluation_date)} · {n(latestRanking?.scored_count.P1 ?? state.ranking.p1_scored_count)}/{n(latestRanking?.universe_count ?? 254)} نماد امتیازدار.</p>
          <p className="text-sm leading-7">قیمت مرجع {n(selected.last_price_rial)} ریال در {d(selected.price_date)}؛ قیمت مرجع، قیمت اجرا نیست. مبلغ قابل تخصیص فعلی: {n(state.cash_toman)} تومان.</p>
          {target ? <p className="text-sm leading-7">برآورد طبق lot یک سهم و هزینهٔ فرضی ۰٫۵٪: {n(target.shares)} سهم · بهای ناخالص {n(target.grossToman)} تومان · هزینه {n(target.feeToman)} تومان · نقد باقیمانده {n(target.remainingToman)} تومان. این صرفاً برآورد سبد است و سفارش یا fill جدید ایجاد نمی‌کند.</p> : <p className="text-sm leading-7">محاسبهٔ تعداد سهم ممکن نیست: قیمت مرجع معتبر و هم‌تاریخ با رتبه‌بندی موجود نیست.</p>}
          {proposalDiffersFromDecision ? <p className="mt-2 rounded-lg bg-amber-100 p-2 text-sm font-bold text-amber-950">پیشنهاد جاری {selected.symbol} با نماد سفارش V12.38 ({state.active_decision?.candidate.symbol}) متفاوت است؛ سفارش و تصمیم ثبت‌شده تغییر نکرده‌اند.</p> : <p className="mt-2 text-sm">نماد پیشنهادی با مبنای سفارش موجود یکسان است؛ نمایش رتبهٔ جاری، تصمیم ثبت‌شده را تغییر نمی‌دهد.</p>}
          {latestRanking?.received_at_status && <p className="mt-1 text-xs leading-6">اعتبار snapshot: {latestRanking.received_at_status}. این وضعیت آماده‌سازی تأییدنشده را به رتبه‌بندی زنده یا PIT تبدیل نمی‌کند.</p>}
        </> : <p className="mt-2 text-sm">رتبهٔ اول P1 در دسترس نیست؛ برآورد سبد ساخته نمی‌شود. {rankingError}</p>}
      </section>

      <section aria-labelledby="order-title" className="rounded-2xl border border-amber-300 bg-amber-50 p-4 text-amber-950 dark:border-amber-900 dark:bg-amber-950/25 dark:text-amber-100">
        <h3 id="order-title" className="text-lg font-black">سفارش منتظر اجرا</h3>
        {check ? <>
          <p className="mt-2 break-words text-sm leading-7">سفارش <code dir="ltr" className="break-all">{check.order.order_id}</code> · نماد {check.order.symbol} · وضعیت {orderNames[check.order.status] ?? check.order.status} · تصمیم در {tehranTime(check.decision.decided_at_utc)} به وقت تهران · snapshot <code dir="ltr" className="break-all">{check.decision.ranking.dataset_id}</code> ({d(check.decision.ranking.evaluation_date)}).</p>
          <p className="text-sm leading-7">علت انتظار: {check.order.waiting_reason}</p>
          <p className="text-sm leading-7">جلسهٔ اجرای تعیین‌شده: {d(check.order.designated_execution_session)} · جلسات مصرف‌شده تا انقضا: {sessionCountLabel({ calendarVerified: orderCalendarVerified, observed: check.order.eligible_session_count_observed, expirySessions: check.order.expires_after_official_sessions })}. قیمت پس از تصمیم: {check.candidate_post_decision_quotes.length ? check.candidate_post_decision_quotes.map(d).join("، ") : "در دریافت موجود نیست"}.</p>
          <p className="text-sm font-semibold">{check.fill_recorded ? "اجرای فرضی موجود در دفتر حساب ثبت شده است." : check.order.status === "EXPIRED_NO_FILL" ? "انقضای ثبت‌شده طبق شواهد؛ خریدی انجام نشده است." : "قیمت چهارشنبهٔ ۲۱ اکتبر پیش از تصمیم است و برای خرید به‌کار نرفته؛ حساب تا احراز جلسهٔ مجاز نقد می‌ماند."}</p>
          {marketState?.state === "natural_weekly_closure" && <p className="mt-2 rounded-lg bg-white/70 p-2 text-sm">تعطیلی پنجشنبه/جمعه مهلت سه‌جلسه‌ای را مصرف نمی‌کند. چون تقویم هنوز کامل نیست، تعداد جلسهٔ سپری‌شده را صفر فرض نمی‌کنیم.</p>}
          {check.execution_attempt_status === "LATE_FILL_TIMING_AMBIGUOUS" && <p role="alert" className="mt-2 rounded-lg bg-rose-100 p-3 text-sm font-bold text-rose-950">ترتیب زمانی اجرای دیررس قابل اثبات نیست؛ fill و انقضا ثبت نشده‌اند.</p>}
        </> : <p role={checkError ? "alert" : "status"} className="mt-2 text-sm">{checkError || "گزارش سفارش بارگذاری می‌شود…"}</p>}
      </section>

      <section aria-labelledby="account-title" className="rounded-2xl border border-slate-300 p-4 dark:border-slate-700">
        <h3 id="account-title" className="text-lg font-black">دارایی حساب کاغذی</h3>
        <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">نقد · تومان</p><p className="font-bold">{n(state.cash_toman)}</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">ارزش دارایی ثبت‌شده</p><p className="font-bold">{n(state.accounting.holdings_value_toman)} تومان · {state.holdings.length ? `${n(state.holdings.length)} موقعیت` : "صفر سهم"}</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">ارزش کل حساب</p><p className="font-bold">{n(state.accounting.total_value_toman)} تومان</p></article>
          <article className="rounded-xl bg-slate-50 p-3 dark:bg-slate-900"><p className="text-xs text-slate-500 dark:text-slate-400">سود/زیان ثبت‌شده</p><p className="font-bold">{n(state.accounting.profit_loss_toman)} تومان</p></article>
        </div>
        <p className="mt-2 text-xs leading-6">آشتی دفتر: نقد {n(state.cash_toman)} + ارزش دارایی {n(state.accounting.holdings_value_toman)} = {n(state.accounting.total_value_toman)} تومان. {state.holdings.length ? "ارزش‌گذاری دارایی‌ها بر پایهٔ قیمت‌های ثبت‌شدهٔ همان دارایی است." : "سفارش معلق و پیشنهاد مدل دارایی حساب نیستند؛ اکنون ۱۰۰ میلیون تومان نقد و صفر سهم ثبت شده است."}</p>
        {state.holdings.length > 0 && <div className="mt-3 overflow-x-auto"><table className="w-full min-w-[700px] text-right text-sm"><thead className="bg-slate-100 dark:bg-slate-900"><tr>{["سهم", "تعداد", "بهای خرید", "آخرین قیمت / تاریخ", "ارزش روز", "سود/زیان"].map((x) => <th key={x} className="p-2">{x}</th>)}</tr></thead><tbody>{state.holdings.map((h, i) => <tr key={`${h.company_id ?? h.symbol}-${i}`} className="border-t"><td className="p-2">{h.symbol}<small className="block">{h.price_status}</small></td><td className="p-2">{n(h.shares)}</td><td className="p-2">{n(h.purchase_price_rial)} ریال · {tehranTime(h.purchase_at_utc)}</td><td className="p-2">{n(h.last_price_rial)} ریال · {d(h.last_price_date)}</td><td className="p-2">{n(h.market_value_toman)} تومان</td><td className="p-2">{n(h.unrealized_pnl_toman)} تومان</td></tr>)}</tbody></table></div>}
      </section>

      <details className="rounded-xl border border-slate-200 p-4 dark:border-slate-700"><summary className="cursor-pointer font-bold">جزئیات چرخه، منابع و ممیزی</summary>
        {cycle ? <div className="mt-3 space-y-3 text-sm leading-7">
          <p className="break-words">آخرین اجرای چرخه: {cycle.status_fa ?? cycle.status} · <code dir="ltr" className="break-all">{cycle.run_id}</code> · آغاز {tehranTime(cycle.started_at_utc)} · پایان {tehranTime(cycle.finished_at_utc)}. این وضعیت از نتیجهٔ هر مرحله جداست.</p>
          <p>زمان‌بندی موجود: روزانه {cycle.schedule?.daily_local_time ?? "22:30"} به وقت {cycle.schedule?.timezone ?? "Asia/Tehran"} · task <code dir="ltr">{cycle.schedule?.task_name ?? "CompanyFinancial-PaperCycle"}</code> · {cycle.schedule?.state ?? "وضعیت ثبت نشده"}{cycle.schedule?.window_requires_user_session ? " · نشست کاربر برای دسترسی شبکه لازم است." : ""}. انتشار خروجی رابط: {state && check && cycle ? "گزارش چرخه و حساب در این صفحه بارگذاری شده‌اند." : "بارگذاری کامل نشده."}</p>
          {cycle.decision?.next_review && <p>موعد بازبینی مدل: {cycle.decision.next_review}</p>}
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{stageRows.map(([key, value]) => <article key={key} className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"><b>{stageNames[key] ?? key}</b><p className="mt-1 break-words text-xs">{value}</p></article>)}</div>
          {cycle.data_sources && <div className="space-y-2 border-t pt-3">
            {([ ["بازار", cycle.data_sources.market], ["مالی", cycle.data_sources.financial], ["فروش", cycle.data_sources.sales] ] as const).map(([label, source]) => source && <p key={label}><b>{label}:</b> {source.state} · آخرین دریافت موفق {source.latest_successful_retrieval_utc ?? source.last_successful_retrieval_utc ?? "ثبت نشده"} · تاریخ داده/انتشار {source.latest_data_date ?? source.latest_complete_session ?? "ثبت نشده"}{source.companies_checked != null ? ` · بررسی ${n(source.companies_checked)}/254؛ تازه ${n(source.companies_new_reports)}؛ بی‌گزارش تازه ${n(source.companies_no_new_reports)}؛ شکست ${n(source.companies_failed)}` : source.coverage ? ` · پوشش ${typeof source.coverage === "number" ? `${n(source.coverage)}/${n(source.coverage_universe ?? 254)}` : `${n(source.coverage.completed)}/${n(source.coverage.universe)} (شکست ${n(source.coverage.failed)})`}` : ""}{source.report_bodies_received != null ? ` · بدنهٔ تازه ${n(source.archive_reuse?.fresh_report_bodies_received_this_run ?? source.report_bodies_received)}؛ سند استخراج‌شده ${n(source.documents_extracted)}؛ عامل پذیرفته ${n(source.document_admission_count)}` : ""}{source.archive_reuse ? ` · از آرشیو موجود ${n(source.archive_reuse.valid_bodies_reused)}؛ بازپردازش محلی ${n(source.archive_reuse.reprocessed_from_local_body)}؛ فرادادهٔ گزارش تازه ${n(source.archive_reuse.fresh_report_metadata)}؛ تلاش مجدد بدنه ${n(source.archive_reuse.retried_after_missing_or_invalid_body)}؛ پاسخ نامعتبر قرنطینه ${n(source.archive_reuse.quarantined_invalid_responses)}` : ""}{source.pages_fetched != null ? ` · صفحه ${n(source.pages_fetched)}؛ صفحه‌بندی ${source.pagination_complete ? "کامل" : "ناقص"}؛ بازه ${source.search_window_from_min ?? "؟"} تا ${source.search_window_to_max ?? "؟"}; ممیزی هویت ${n(source.identity_audit_count)}/254` : ""}{source.retry_after?.next_attempt_at_utc ? ` · تلاش بعدی ${tehranTime(source.retry_after.next_attempt_at_utc)}` : ""}{source.error ? ` · خطا: ${source.error}` : ""}</p>)}
            <p><b>تقویم سفارش:</b> {cycle.data_sources.calendar_for_order?.state ?? "ثبت نشده"} · آخرین جلسه {d(cycle.data_sources.calendar_for_order?.latest_complete_session)} · پوشش {typeof cycle.data_sources.calendar_for_order?.coverage === "number" ? n(cycle.data_sources.calendar_for_order.coverage) : "نامشخص"} {cycle.data_sources.calendar_for_order?.error}</p>
            <p><b>تقویم O00:</b> {cycle.data_sources.calendar_for_o00?.state ?? "ثبت نشده"} · شکاف از {d(cycle.data_sources.calendar_for_o00?.coverage_from)} · اندیس مبنا {n(cycle.data_sources.calendar_for_o00?.locked_panel_index)}، شمارش محلی {n(cycle.data_sources.calendar_for_o00?.local_calendar_computed_index_at_panel_end)} · نگاشت مبنا {cycle.data_sources.calendar_for_o00?.locked_prefix_date_mapping_complete ? "کامل" : "ناقص"} · تاریخ اضافه {cycle.data_sources.calendar_for_o00?.locked_prefix_extra_local_dates?.join("، ") || "ندارد"} · هدف {n(cycle.data_sources.calendar_for_o00?.target_global_index)}؛ تاریخ موعد از این اندیس استنتاج نشده است.</p>
            <p><b>اعتبارنامه:</b> {cycle.credential?.state ?? "بررسی نشده"} · هویت task {cycle.credential?.task_identity_state ?? "ثبت نشده"} · اعتبار منبع {cycle.credential?.remote_validity ?? "بررسی نشده"} · ماندگاری اجراهای بعدی تضمین نمی‌شود.</p>
            {cycle.ranking_input_admission?.reason && <p className="rounded-lg bg-amber-100 p-2">{cycle.ranking_input_admission.reason}</p>}
          </div>}
          {check && <div className="space-y-2 border-t pt-3"><p>تصمیم {check.decision.candidate.symbol} در {tehranTime(check.decision.decided_at_utc)} · snapshot SHA-256 <code dir="ltr" className="break-all">{check.decision.ranking.artifact_sha256}</code> · قواعد {check.decision.execution_rules.rule_id} · SHA-256 <code dir="ltr" className="break-all">{check.decision.execution_rules.sha256}</code>.</p><p>تقویم جلسهٔ بعد: {marketState ? stateNames[marketState.state] : "نامشخص"} · شواهد قیمت پس از تصمیم {check.candidate_post_decision_quotes.map(d).join("، ") || "ندارد"} · وضعیت fill {check.fill_recorded ? "ثبت شده" : "ثبت نشده"}.</p>{(check.barriers ?? []).map((barrier) => <p key={barrier.id}><b>{barrier.title}:</b> {barrier.details}</p>)}</div>}
          <p>قواعد حفظ‌شده: {state.contract.model}/{state.contract.weight_id} · انتخاب تک‌سهمی · بازبینی هر {n(state.contract.review_cadence_sessions)} جلسه بر مبنای O00. اجرای سفارش فقط روی نخستین جلسهٔ رسمی پس از تصمیم و قیمت همان جلسه مجاز است؛ روزهای تعطیل مهلت را مصرف نمی‌کنند.</p>
          <p>حساب از {tehranTime(state.created_at_utc)} · سرمایهٔ آغازین {n(state.initial_capital_toman)} تومان · رویدادها {n(state.event_log.length)} · دفتر رسمی آینده به این حساب متصل نیست.</p>
          <details className="rounded-lg bg-slate-50 p-3 dark:bg-slate-900"><summary className="cursor-pointer font-semibold">دفتر رویداد حساب کاغذی</summary><ul className="mt-2 space-y-3">{state.event_log.map((x) => <li key={x.event_id} className="border-t pt-2"><b>{x.type}</b> · {tehranTime(x.at_utc)}<p>{x.details}</p><p className="text-xs text-slate-500">دلیل: {x.reason}</p></li>)}</ul></details>
        </div> : <p className="mt-2">گزارش چرخه بارگذاری نشده است.</p>}
      </details>
    </>}
  </section>;
}
