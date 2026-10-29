import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import LatestLockedRanking from "./LatestLockedRanking";
import PaperTrialPanel from "./PaperTrialPanel";

type ContractMethod = { method_id: string; role: string; weight_id: string; route: string; weights: number[] };
type Contract = {
  contract_id: string;
  status: string;
  factor_order: string[];
  methods: ContractMethod[];
  portfolio: { target_count: number; review_cadence_sessions: number; exit_rank: number };
  capital: { per_method_initial_toman: number; currency: string; independent_accounts: boolean };
  calendar: { id: string; review_rule: string; source_panel_end: string; next_scheduled_date: string | null };
  liquidity: { score_weight: number; execution_constraint_is_separate: boolean };
  scoring: { financial_eligibility: string; missing_and_zero: string; penalty_components: string; default_mask_dq_tiebreak: string };
};
type Readiness = {
  status: string;
  formal_start_date: string | null;
  last_compatible_price_effective_date: string | null;
  last_compatible_score_effective_date: string | null;
  last_compatible_calendar_session: string | null;
  calendar_status: string;
  o00_next_scheduled_date: string | null;
  source_received_at: string | null;
  official_event_count: number;
  no_future_results: boolean;
  expected_frozen_universe_symbols: number;
  compatible_snapshot_rows_on_last_date: number;
  symbols_missing_price_or_features_on_last_date: number;
  missing_inputs: Array<{ input: string; needed_for: string }>;
};
type OfficialState = {
  status: string;
  contract_sha256: string;
  formal_start_date: string | null;
  last_decision: string | null;
  pending_orders: unknown[] | Record<string, unknown[]>;
  account_results: Record<string, { nav_toman: number | null; net_profit_toman: number | null; fees_toman: number; cash_toman?: number | null; holdings_actual_shares?: Record<string, number>; valuation_status?: string }> | null;
  official_event_count: number;
};
type Preparation = {
  version: string; status: string; contract_sha256: string; as_of_utc: string;
  readiness: {
    data_and_rank: { compatible_scores_computed: boolean; candidate_snapshot_created: boolean };
    calendar_and_decision: { locked_last_date: string; next_o00_date: string | null };
    paper_execution_and_accounting: { status: string };
  };
};
type Loaded = { contract: Contract; readiness: Readiness; official: OfficialState; preparation: Preparation };
type LedgerRow = Record<string, unknown>;

const base = `${import.meta.env.BASE_URL}research/future-eval-v12-28-`;
const fmt = (value: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits, minimumFractionDigits: digits }).format(value);
const date = (value: string | null | undefined) => value ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${value.slice(0, 10)}T00:00:00Z`)) : "هنوز مشخص نیست";
const archiveVersions = [
  ["V12.27.1", "مرجع تاریخی بازپخش رتبه و دفتر", "مرجع تاریخی؛ شاخص قیمت تعدیل‌شده، نه تعداد سهم واقعی", "return-v12-27-1-page-data.json"],
  ["V12.27", "بازپخش رتبه و منشأ بازده", "تاریخی؛ نسخهٔ اصلاحی V12.27.1 مرجع نهایی است", "return-v12-27-page-data.json"],
  ["V12.26", "ممیزی صلاحیت مالی و دفتر", "تاریخی؛ برای ارزیابی آینده استفاده نمی‌شود", "return-v12-26-validation.json"],
  ["V12.25", "ممیزی ابهام و اجرای تاریخی", "تاریخی؛ برای ارزیابی آینده استفاده نمی‌شود", "return-v12-25-summary.json"],
  ["V12.24", "بررسی تقویم و مسیرها", "تاریخی؛ برای ارزیابی آینده استفاده نمی‌شود", "return-v12-24-summary.json"],
  ["V12.23", "مبنای snapshot پژوهش تاریخی", "تاریخی؛ دادهٔ قفل‌شدهٔ پژوهش گذشته", "return-v12-23.json"],
  ["V12.22", "بازسازی محلی score", "RECONSTRUCTION_MISMATCH؛ بازده محاسبه نشد", "return-v12-22-report.fa.md"],
  ...Array.from({ length: 20 }, (_, i) => {
    const v = 21 - i;
    return [`V12.${v}`, `پژوهش تاریخی مرحلهٔ V12.${v}`, "نسخهٔ تاریخی/میانی؛ انتخاب فعلی نیست", `return-v12-${v}.json`];
  }),
  ["V12.1", "رتبه‌بندی پژوهشی اولیه", "نسخهٔ تاریخی؛ انتخاب فعلی نیست", "return-v12-1.json"],
] as const;

const factorNames: Record<string, string> = {
  sales_growth_12m: "رشد فروش ۱۲ماهه", sales_growth_3m: "رشد فروش ۳ماهه", revenue_growth: "رشد درآمد",
  operating_profit_growth: "رشد سود عملیاتی", net_profit_growth: "رشد سود خالص", operating_margin: "حاشیهٔ عملیاتی",
  net_margin: "حاشیهٔ خالص", roe: "بازده حقوق صاحبان سهام", margin_trend: "روند حاشیهٔ سود",
  interest_coverage: "پوشش هزینهٔ مالی", cash_conversion: "تبدیل سود به وجه نقد", earnings_quality: "کیفیت سود",
  pe: "P/E", ps: "P/S", pb: "P/B", avg_trade_value_30d: "ارزش معاملات ۳۰روزه",
  sales_stability: "پایداری فروش", leverage: "اهرم مالی", current_ratio: "نسبت جاری",
  volatility_30d: "نوسان ۳۰روزه", price_momentum_30d: "شتاب قیمت ۳۰روزه",
};

function useResearchSources() {
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoaded(null);
    setError("");
    Promise.all([
      fetch(`${base}contract.json`, { signal: controller.signal, cache: "no-cache" }),
      fetch(`${base}status.json`, { signal: controller.signal, cache: "no-cache" }),
      fetch(`${base}official-state.json`, { signal: controller.signal, cache: "no-cache" }),
      fetch(`${import.meta.env.BASE_URL}research/future-eval-v12-29-readiness.json`, { signal: controller.signal, cache: "no-cache" }),
    ]).then(async (responses) => {
      const failed = responses.find((response) => !response.ok);
      if (failed) throw new Error(`دریافت منبع محلی ناموفق بود (HTTP ${failed.status}).`);
      const [contract, readiness, official, preparation] = await Promise.all(responses.map((response) => response.json()));
      if (!contract?.methods?.length || !contract?.factor_order?.length || !Array.isArray(readiness?.missing_inputs) || !official?.status) {
        throw new Error("ساختار قرارداد یا وضعیت رسمی با طرح مورد انتظار سازگار نیست.");
      }
      if (!["P1", "P3"].every((id) => contract.methods.some((method: ContractMethod) => method.method_id === id && method.weights?.length === contract.factor_order.length))) {
        throw new Error("وزن‌های P1/P3 با ترتیب عامل‌های قرارداد سازگار نیستند.");
      }
      if (preparation?.version !== "V12.29" || preparation?.contract_sha256 !== official.contract_sha256 ||
          typeof preparation?.readiness?.data_and_rank?.compatible_scores_computed !== "boolean" ||
          !preparation?.readiness?.calendar_and_decision?.locked_last_date ||
          !preparation?.readiness?.paper_execution_and_accounting?.status) {
        throw new Error("گزارش آمادگی V12.29 با قرارداد رسمی سازگار نیست.");
      }
      setLoaded({ contract, readiness, official, preparation });
    }).catch((reason: unknown) => {
      if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "خطای ناشناخته در خواندن منابع محلی.");
    });
    return () => controller.abort();
  }, [attempt]);
  return { loaded, error, retry: () => setAttempt((value) => value + 1) };
}

function NavTabs({ active, onSelect }: { active: string; onSelect: (value: string) => void }) {
  const tabs = [["overview", "رتبه‌بندی منتخب"], ["paper", "سبد آزمایشی"], ["method", "روش انتخاب"], ["archive", "آرشیو"]];
  return <nav aria-label="بخش‌های پژوهش" className="flex flex-wrap gap-2 border-b border-slate-200 pb-3 dark:border-slate-700">
    {tabs.map(([id, label]) => <button key={id} type="button" onClick={() => onSelect(id)} aria-current={active === id ? "page" : undefined}
      className={`rounded-xl px-4 py-2 text-sm font-semibold ${active === id ? "bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900" : "bg-white text-slate-700 ring-1 ring-slate-200 dark:bg-slate-800 dark:text-slate-200 dark:ring-slate-700"}`}>{label}</button>)}
  </nav>;
}

export default function ResearchHomePage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const tab = ["paper", "method", "archive"].includes(searchParams.get("view") ?? "") ? searchParams.get("view")! : "overview";
  const setTab = (value: string) => setSearchParams(value === "overview" ? {} : { view: value });
  const { loaded, error, retry } = useResearchSources();
  const [officialLogs, setOfficialLogs] = useState<{ events: LedgerRow[]; decisions: LedgerRow[] } | null>(null);
  const [ledgerError, setLedgerError] = useState("");
  useEffect(() => {
    if (loaded?.official.status !== "ACTIVE") { setOfficialLogs(null); setLedgerError(""); return; }
    const controller = new AbortController();
    const readJsonl = async (url: string) => {
      const response = await fetch(url, { signal: controller.signal, cache: "no-cache" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const body = await response.text();
      return body.split(/\r?\n/).filter((line) => line.trim()).map((line) => JSON.parse(line) as LedgerRow);
    };
    Promise.all([readJsonl(`${base}events.jsonl`), readJsonl(`${base}decisions.jsonl`)])
      .then(([events, decisions]) => setOfficialLogs({ events, decisions }))
      .catch((reason: unknown) => { if (!controller.signal.aborted) setLedgerError(reason instanceof Error ? reason.message : "خطا در خواندن دفتر رسمی."); });
    return () => controller.abort();
  }, [loaded]);
  const weights = useMemo(() => {
    if (!loaded) return [];
    return loaded.contract.methods.map((method) => ({ method, rows: loaded.contract.factor_order.map((factor, i) => ({ factor, weight: method.weights[i] })) }));
  }, [loaded]);
  const status = loaded?.official.status ?? loaded?.readiness.status;
  const active = status === "ACTIVE";
  const readiness = loaded?.readiness;
  const preparation = loaded?.preparation;
  const readyRows = [
    { name: "آمادگی snapshot رسمی آینده", state: preparation?.readiness.data_and_rank.compatible_scores_computed ? "نیازمند تأیید رسمی" : "snapshot رسمی نیاز است", detail: "تاریخ ارزیابی و آخرین دریافت ثبت‌شدهٔ رتبه‌بندی در بالای صفحه نمایش داده می‌شود؛ artifact رتبه‌بندی ایستا است و روزانه خودکار بازسازی نمی‌شود. این کارت فقط آمادگی snapshot برای ارزیابی آینده و شواهد زمان دریافت را نشان می‌دهد." },
    { name: "تقویم O00", state: preparation?.readiness.calendar_and_decision.next_o00_date ? "نیازمند تأیید" : "ادامهٔ تقویم ناموجود", detail: `تقویم معتبر تا ${date(preparation?.readiness.calendar_and_decision.locked_last_date)} موجود است؛ تقویم کامل جلسات بعدی باید تأمین شود.` },
    { name: "ثبت تصمیم", state: (loaded?.official.official_event_count ?? readiness?.official_event_count) ? "ثبت رسمی موجود" : "در انتظار آغاز رسمی", detail: (loaded?.official.official_event_count ?? readiness?.official_event_count) ? `${fmt(loaded?.official.official_event_count ?? readiness?.official_event_count ?? 0)} رویداد رسمی ثبت شده.` : "۰ رویداد رسمی؛ شروع فقط پس از تکمیل گیت‌ها و ثبت تصمیم اپراتور." },
    { name: "اجرای کاغذی و حسابداری سهم", state: loaded?.official.account_results ? "دارای ثبت حساب" : "مسدود؛ ورودی ناقص", detail: "قواعد تعداد سهم و اندازهٔ سفارش، هزینه‌ها، صف و عدم اجرا و رویدادهای شرکتی باید تکمیل شوند؛ هزینهٔ ۰٫۵٪ هر سمت هنوز تأیید نشده است." },
  ];

  return <main dir="rtl" className="mx-auto w-full max-w-7xl space-y-5 py-4" aria-labelledby="research-title">
    <header className="space-y-2">
      <p className="text-xs font-bold tracking-wide text-slate-500">رتبه‌بندی مدل منتخب · P1 / valuation_0</p>
      <h2 id="research-title" className="text-2xl font-black sm:text-3xl">رتبه‌بندی سهام</h2>
      <p className="max-w-3xl text-sm leading-7 text-slate-600 dark:text-slate-300">رتبه‌بندی از وضعیت آغاز ارزیابی آینده مستقل است؛ امتیاز مدل مقایسه‌ای P3 اختیاری است.</p>
    </header>
    <NavTabs active={tab} onSelect={setTab} />

    {tab === "overview" && <div className="space-y-5">
      <LatestLockedRanking />

      <details className="rounded-xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-700 dark:bg-slate-900" aria-live="polite">
        <summary className="cursor-pointer text-sm font-bold">وضعیت ارزیابی آینده — مستقل از رتبه‌بندی</summary>
        {error ? <div className="mt-2 text-sm" role="alert"><p>منبع وضعیت آینده بارگذاری یا اعتبارسنجی نشد: {error}</p><button className="mt-2 underline" onClick={retry}>تلاش دوباره</button></div> : !loaded ? <p role="status" className="mt-2 text-sm">در حال خواندن وضعیت دفتر آینده…</p> : <p className="mt-2 text-sm leading-7">وضعیت: {status === "ACTIVE" ? "فعال" : "ارزیابی آینده آغاز نشده"} · تاریخ شروع: {date(loaded.official.formal_start_date)} · آخرین دادهٔ تاریخی سازگار: {date(readiness?.last_compatible_score_effective_date)} · موعد O00: {date(readiness?.o00_next_scheduled_date)} · رویداد دفتر: {fmt(loaded.official.official_event_count)}. این وضعیت نمایش رتبه‌بندی بالا را کنترل نمی‌کند.</p>}
      </details>

      {loaded && <section className="grid gap-4 md:grid-cols-2" aria-label="مدل‌های منتخب">
        <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"><p className="text-xs font-semibold text-slate-500">مدل اصلی</p><h2 className="mt-1 text-xl font-black">P1 — رتبه‌بندی valuation_0</h2><p className="mt-2 text-sm">سرمایهٔ کاغذی مستقل: {fmt(loaded?.contract.capital.per_method_initial_toman ?? 100_000_000)} تومان</p></article>
        <article className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm dark:border-slate-700 dark:bg-slate-800"><p className="text-xs font-semibold text-slate-500">مدل مقایسه‌ای</p><h2 className="mt-1 text-xl font-black">P3 — رتبه‌بندی w0</h2><p className="mt-2 text-sm">سرمایهٔ کاغذی مستقل: {fmt(loaded?.contract.capital.per_method_initial_toman ?? 100_000_000)} تومان</p></article>
      </section>}
      <p className="rounded-xl bg-slate-100 px-4 py-3 text-sm leading-7 dark:bg-slate-800">این مدل برای آزمون آینده انتخاب و ثابت شده است؛ برتری آن در آینده هنوز اثبات نشده. هدف هر سبد: یک سهم، رتبهٔ اول. بازبینی: هر ۶۳ جلسه طبق تقویم ثابت O00.</p>

      <section className="space-y-3 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <div><h2 className="text-lg font-bold">آمادگی شروع</h2><p className="text-xs leading-6 text-slate-500">منبع کمبودهای داده: V12.29 · وضعیت رسمی و قرارداد: V12.28</p></div>
        {!loaded && !error ? <p role="status" className="text-sm">در حال خواندن وضعیت آمادگی…</p> : <div className="grid gap-3 sm:grid-cols-2">{readyRows.map((row) => <article key={row.name} className="rounded-xl bg-slate-50 p-4 dark:bg-slate-900"><h3 className="text-sm font-bold">{row.name}</h3><p className="mt-1 text-xs font-semibold text-amber-700 dark:text-amber-300">{loaded ? row.state : "منبع ناموجود"}</p><p className="mt-2 text-sm leading-7 text-slate-600 dark:text-slate-300">{loaded ? row.detail : error || "تا تأیید منبع، نامعلوم"}</p></article>)}</div>}
        {readiness?.missing_inputs?.length ? <details className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-900"><summary className="cursor-pointer font-semibold">جزئیات فنی ورودی‌های قرارداد V12.28</summary><ul className="mt-2 list-disc space-y-2 px-5 leading-6">{readiness.missing_inputs.map((item) => <li key={item.input}><strong>{item.input}:</strong> {item.needed_for}</li>)}</ul></details> : null}
      </section>

      <details className="space-y-3 rounded-2xl border border-slate-200 p-4 dark:border-slate-700"><summary className="cursor-pointer font-bold">دفتر ارزیابی آینده و نتیجه‌ها</summary>{active ? <>
        <p className="text-sm leading-7">داده‌های این بخش فقط از دفتر رسمی آینده خوانده می‌شوند؛ تاریخچهٔ شبیه‌سازی وارد آن نمی‌شود.</p>
        {ledgerError ? <p role="alert" className="text-sm">دفتر رسمی بارگذاری نشد؛ دادهٔ جایگزین نمایش داده نمی‌شود. {ledgerError}</p> : !officialLogs ? <p role="status" className="text-sm">در حال خواندن دفتر رسمی…</p> : <>
          <div className="grid gap-3 sm:grid-cols-2">{Object.entries(loaded?.official.account_results ?? {}).map(([method, result]) => <article key={method} className="rounded-xl bg-slate-50 p-3 text-sm leading-7 dark:bg-slate-800"><h3 className="font-bold">حساب {method}</h3><p>وجه نقد: {result.cash_toman == null ? "هنوز مشخص نیست" : `${fmt(result.cash_toman)} تومان`}</p><p>دارایی: {result.holdings_actual_shares ? Object.entries(result.holdings_actual_shares).filter(([, qty]) => qty > 0).map(([symbol, qty]) => `${symbol} (${fmt(qty)} سهم)`).join("، ") || "بدون سهم ثبت‌شده" : "هنوز مشخص نیست"}</p><p>NAV: {result.nav_toman == null ? "هنوز مشخص نیست" : `${fmt(result.nav_toman)} تومان`} · سود خالص: {result.net_profit_toman == null ? "هنوز مشخص نیست" : `${fmt(result.net_profit_toman)} تومان`} · کارمزد: {result.fees_toman == null ? "هنوز مشخص نیست" : `${fmt(result.fees_toman)} تومان`}</p></article>)}</div>
          <h3 className="font-semibold">تصمیم‌های رسمی</h3>{officialLogs.decisions.length ? <div className="overflow-x-auto"><table className="w-full min-w-[560px] text-right text-sm"><thead><tr className="border-b"><th className="p-2">مدل</th><th className="p-2">تاریخ مؤثر</th><th className="p-2">snapshot</th><th className="p-2">شناسهٔ رویداد</th></tr></thead><tbody>{officialLogs.decisions.map((row, i) => <tr key={String(row.event_id ?? i)} className="border-b"><td className="p-2">{String(row.method_id ?? "نامعلوم")}</td><td className="p-2">{date(String(row.effective_date ?? ""))}</td><td className="p-2">{String(row.snapshot_id ?? "نامعلوم")}</td><td className="p-2" dir="ltr">{String(row.event_id ?? "نامعلوم")}</td></tr>)}</tbody></table></div> : <p className="text-sm">تصمیم رسمی در دفتر ثبت نشده است.</p>}
          <h3 className="font-semibold">سفارش و اجرای ثبت‌شده</h3>{officialLogs.events.filter((row) => ["ORDER_CREATED", "ORDER_EXECUTION", "ORDER_NON_EXECUTION"].includes(String(row.event_type))).length ? <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-right text-sm"><thead><tr className="border-b"><th className="p-2">نوع</th><th className="p-2">مدل</th><th className="p-2">وضعیت اجرا</th><th className="p-2">شناسهٔ سفارش</th><th className="p-2">کارمزد ثبت‌شده</th></tr></thead><tbody>{officialLogs.events.filter((row) => ["ORDER_CREATED", "ORDER_EXECUTION", "ORDER_NON_EXECUTION"].includes(String(row.event_type))).map((row, i) => { const state = String(row.status ?? ""); const notFilled = state === "NOT_EXECUTED" || state === "CANCELLED" || row.event_type === "ORDER_NON_EXECUTION"; const execution = row.event_type === "ORDER_CREATED" ? "سفارش ثبت‌شده" : notFilled ? "عدم اجرا / لغو" : row.event_type === "ORDER_EXECUTION" ? "اجرای ثبت‌شده" : "عدم اجرا"; return <tr key={String(row.event_id ?? i)} className="border-b"><td className="p-2">{execution}</td><td className="p-2">{String(row.method_id ?? "نامعلوم")}</td><td className="p-2">{state || "ثبت نشده"}</td><td className="p-2" dir="ltr">{String(row.order_id ?? "نامعلوم")}</td><td className="p-2">{typeof row.fee_toman === "number" ? `${fmt(row.fee_toman)} تومان` : "هنوز مشخص نیست"}</td></tr>; })}</tbody></table></div> : <p className="text-sm">سفارش یا اجرای ثبت‌شده‌ای در دفتر رسمی موجود نیست.</p>}
        </>}
      </> : <><p className="mt-2 text-sm leading-7">{readiness?.no_future_results !== false ? "رتبه‌بندی معتبر برای شروع آینده آماده نیست. رتبهٔ آماده‌سازی به‌عنوان سفارش یا سهم خریداری‌شده نمایش داده نمی‌شود." : "وضعیت snapshot نیازمند بررسی منبع رسمی است؛ تا تأیید snapshot معتبر جدول رتبه نمایش داده نمی‌شود."}</p><p className="mt-1 text-xs leading-6 text-slate-500">ارزیابی آینده هنوز آغاز نشده است. جدول معامله و نمودار بازده آینده تا شروع رسمی با دادهٔ تاریخی یا نمونه پُر نمی‌شود.</p></>}</details>


    </div>}

    {tab === "paper" && <PaperTrialPanel />}

    {tab === "method" && <div className="space-y-4">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 leading-7 dark:border-slate-700 dark:bg-slate-800"><h2 className="text-lg font-bold">جزئیات روش و قرارداد قفل‌شده</h2><p className="mt-2 text-sm">عامل‌ها و وزن‌ها از قرارداد V12.28 خوانده می‌شوند. اگر قرارداد دریافت نشود یا وزن‌ها با فهرست عامل‌ها هم‌اندازه نباشند، جدول نمایش داده نمی‌شود.</p><p className="text-sm">فیلتر اضافی پوشش مالی: ندارد (G0)؛ قواعد داخلی امتیازدهی و کیفیت داده برقرارند. وزن نقدشوندگی در هر دو مدل صفر است؛ محدودیت اجرا جدا از امتیازدهی بررسی می‌شود.</p>
        {!loaded && !error ? <p role="status" className="mt-3">در حال خواندن قرارداد…</p> : error ? <p role="alert" className="mt-3">جزئیات قرارداد نمایش داده نشد: {error}</p> : <div className="mt-4 space-y-4">{weights.map(({ method, rows }) => <details key={method.method_id} className="rounded-xl border p-3 dark:border-slate-700" open={method.method_id === "P1"}><summary className="cursor-pointer font-bold">{method.method_id} · {method.weight_id} · وزن عامل‌ها</summary><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[390px] text-right text-sm"><thead><tr className="border-b dark:border-slate-700"><th className="p-2">عامل</th><th className="p-2">وزن</th></tr></thead><tbody>{rows.map(({ factor, weight }) => <tr key={factor} className="border-b last:border-0 dark:border-slate-700"><td className="p-2">{factorNames[factor] ?? factor}</td><td className="p-2 tabular-nums">{fmt(weight, 4)}٪</td></tr>)}</tbody></table></div></details>)}</div>}
        {loaded && <div className="mt-4 grid gap-2 text-sm sm:grid-cols-2"><p>تعداد هدف: {fmt(loaded.contract.portfolio.target_count)} سهم · رتبهٔ خروج: {fmt(loaded.contract.portfolio.exit_rank)}</p><p>بازبینی: هر {fmt(loaded.contract.portfolio.review_cadence_sessions)} جلسه · تقویم {loaded.contract.calendar.id}</p><p>سرمایه: {fmt(loaded.contract.capital.per_method_initial_toman)} تومان برای هر حساب مستقل</p><p>وزن نقدشوندگی: {fmt(loaded.contract.liquidity.score_weight)}٪ در هر دو مدل</p></div>}
        {loaded && <details className="mt-4 rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-900"><summary className="cursor-pointer font-semibold">قواعد امتیازدهی، دادهٔ مفقود و جریمه</summary><ul className="mt-2 list-disc space-y-2 px-5 leading-7"><li>پوشش مالی اضافی: {loaded.contract.scoring.financial_eligibility}.</li><li>{loaded.contract.scoring.missing_and_zero}</li><li>{loaded.contract.scoring.penalty_components}</li><li>{loaded.contract.scoring.default_mask_dq_tiebreak}</li><li>قاعدهٔ تقویم: {loaded.contract.calendar.review_rule}</li></ul></details>}
        <div className="mt-4 flex flex-wrap gap-3 text-sm"><a className="underline" href={`${base}contract.json`} download>قرارداد ماشین‌خوان</a><a className="underline" href={`${base}contract.sha256`} download>هش قرارداد</a><a className="underline" href={`${base}snapshot-schema.json`} download>قالب snapshot آینده</a><a className="underline" href={`${base}readiness.fa.csv`} download>جدول آمادگی داده</a></div>
      </section>
    </div>}

    {tab === "archive" && <div className="space-y-4">
      <section className="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700 dark:bg-slate-800">
        <h2 className="font-bold">نماهای آزمایشی پیشین</h2>
        <p className="mt-2 text-sm leading-7 text-slate-500">این رتبه‌ها متعلق به مدل منتخب نیستند؛ فقط برای مرور نگهداری شده‌اند.</p>
        <div className="mt-3 grid gap-3 sm:grid-cols-3">{[["/ranking/legacy-cash", "ارزندگی با پشتوانهٔ نقد"], ["/qvt", "تحلیل QVT"], ["/ranking/research", "پژوهش تاریخی S2"]].map(([path, label]) => <Link key={path} to={path} className="rounded-xl border border-slate-200 p-3 text-sm font-semibold hover:bg-slate-50 dark:border-slate-700 dark:hover:bg-slate-900">{label} ←</Link>)}</div>
      </section>
      <section className="rounded-2xl border border-slate-200 p-4 dark:border-slate-700"><h2 className="text-lg font-bold">آرشیو پژوهش تاریخی</h2><p className="mt-2 text-sm leading-7">نسخه‌ها و آزمایش‌های قبلی صرفاً برای مرور تاریخی‌اند. وضعیت محدودکنندهٔ هر نسخه حفظ شده و هیچ نتیجهٔ میانی به‌عنوان انتخاب فعلی ارائه نمی‌شود.</p></section>
      <div className="space-y-2">{archiveVersions.map(([version, title, state, file]) => <details key={version} className="rounded-xl border border-slate-200 bg-white p-3 dark:border-slate-700 dark:bg-slate-800"><summary className="cursor-pointer"><span className="font-bold">{version}</span><span className="mx-2">·</span>{title}<span className="mt-1 block text-xs leading-6 text-slate-500">{state}</span></summary><div className="mt-2 flex flex-wrap gap-3 text-sm"><a className="underline" href={`${import.meta.env.BASE_URL}research/${file}`} target="_blank" rel="noreferrer">بازکردن مصنوع نسخه</a>{version === "V12.27.1" && <a className="underline" href={`${import.meta.env.BASE_URL}research/return-v12-27-1-handoff.fa.md`}>یادداشت تحویل</a>}{version === "V12.22" && <a className="underline" href={`${import.meta.env.BASE_URL}research/return-v12-22.json`}>دادهٔ خلاصه</a>}</div></details>)}</div>
      <details className="rounded-xl border border-slate-200 p-3 dark:border-slate-700"><summary className="cursor-pointer font-semibold">اسناد و اطلاعات فنی V12.28</summary><div className="mt-3 flex flex-wrap gap-3 text-sm"><a className="underline" href={`${base}contract.json`} download>قرارداد</a><a className="underline" href={`${base}contract.sha256`} download>هش قرارداد</a><a className="underline" href={`${base}o00-session-calendar.csv`} download>تقویم O00 موجود</a><a className="underline" href={`${base}readiness.fa.csv`} download>گزارش آمادگی</a><a className="underline" href={`${base}official-state.json`} download>وضعیت دفتر رسمی</a><a className="underline" href={`${base}events.jsonl`} download>دفتر رویداد</a><a className="underline" href={`${base}decisions.jsonl`} download>تصمیم‌های رسمی</a><a className="underline" href={`${base}snapshot-schema.json`} download>قالب snapshot</a></div></details>
    </div>}
  </main>;
}
