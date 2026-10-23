import { useEffect, useMemo, useState } from "react";

type MethodRow = { rank: number | null; score: number | null; financial_factor_coverage: number; quality: string; scoreability_reason: string | null };
type RankingRow = {
  symbol: string; company_id: string; symbol_index: number; identity_status: string; current_trading_status: string;
  evaluation_date: string; price_effective_date: string | null; publication_cutoff_at: string; received_at: string | null;
  financial_period_end?: string | null; financial_latest_published_at?: string | null; financial_factor_period_end?: string | null;
  monthly_sales_latest_period?: string | null; monthly_sales_latest_published_at?: string | null;
  dq: number; methods: { P1: MethodRow; P3: MethodRow }; raw_factors: Record<string, number | null>;
  observed_factors: Record<string, boolean>; defaulted_factors: string[]; masked_factors: string[]; scoreability_reason: string | null;
};
type Ranking = {
  status: "HISTORICAL" | "PREPARATION_UNCONFIRMED"; status_detail: string; model: { primary: { id: string; name: string }; comparison: { id: string; name: string } };
  contract_id: string; contract_sha256: string; scorer_version: string; evaluation_date: string; publication_cutoff_at: string;
  computed_at_tehran: string; received_at: string | null; received_at_status: string; universe_count: number;
  scored_count: Record<string, number>; unscored_count: Record<string, number>; factor_observed_counts: Record<string, number>;
  source: { dataset_id: string; path: string; sha256: string };
  limitations: string[]; rows: RankingRow[]; artifact_sha256: string;
  source_provenance?: { TSETMC?: { retrieved_at_range_utc?: string[] }; financial_archive?: { latest_published_at?: string; latest_period_end?: string; received_at_status?: string }; monthly_sales_archive?: { latest_published_at?: string; latest_event_period?: string; received_at_status?: string } };
};

const labels: Record<string, string> = {
  sales_growth_12m: "رشد فروش ۱۲ماهه", sales_growth_3m: "رشد فروش ۳ماهه", revenue_growth: "رشد درآمد",
  operating_profit_growth: "رشد سود عملیاتی", net_profit_growth: "رشد سود خالص", operating_margin: "حاشیهٔ عملیاتی",
  net_margin: "حاشیهٔ خالص", roe: "بازده حقوق صاحبان سهام", margin_trend: "روند حاشیهٔ سود",
  interest_coverage: "پوشش هزینهٔ مالی", cash_conversion: "تبدیل سود به وجه نقد", earnings_quality: "کیفیت سود",
  pe: "P/E", ps: "P/S", pb: "P/B", avg_trade_value_30d: "ارزش معاملات ۳۰روزه", sales_stability: "پایداری فروش",
  leverage: "اهرم مالی", current_ratio: "نسبت جاری", volatility_30d: "نوسان ۳۰روزه", price_momentum_30d: "شتاب قیمت ۳۰روزه",
};
const fmt = (n: number | null | undefined, digits = 3) => n == null ? "—" : new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(n);
const date = (s: string | null | undefined) => s ? new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "UTC" }).format(new Date(`${s.slice(0, 10)}T00:00:00Z`)) : "ثبت نشده";

export default function LatestLockedRanking() {
  const [data, setData] = useState<Ranking | null>(null);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [comparison, setComparison] = useState(false);
  const [version, setVersion] = useState<"v12-37" | "v12-36" | "v12-35" | "v12-34" | "v12-33" | "v12-32" | "v12-31">("v12-37");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    const path = `research/${version}/latest-ranking.json`;
    fetch(`${import.meta.env.BASE_URL}${path}`, { signal: controller.signal, cache: "no-cache" })
      .then(async (response) => { if (!response.ok) throw new Error(`فایل مشخص رتبه‌بندی در دسترس نیست (HTTP ${response.status}).`); return response.json() as Promise<Ranking>; })
      .then((payload) => {
        if (!["HISTORICAL", "PREPARATION_UNCONFIRMED"].includes(payload.status) || payload.model?.primary?.id !== "P1" || payload.model?.comparison?.id !== "P3" ||
            !payload.contract_sha256 || !payload.artifact_sha256 || !Array.isArray(payload.rows) || payload.rows.length !== payload.universe_count || payload.universe_count !== 254 ||
            new Set(payload.rows.map((r) => r.symbol)).size !== payload.universe_count || payload.rows.some((r) => !r.company_id || !r.identity_status || !r.methods?.P1 || !r.methods?.P3)) {
          throw new Error("خروجی رتبه‌بندی ناقص یا ناسازگار است و نمایش داده نمی‌شود.");
        }
        setData(payload);
      })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "خطای خواندن رتبه‌بندی."); });
    return () => controller.abort();
  }, [attempt, version]);

  const rows = useMemo(() => {
    if (!data) return [];
    const q = search.trim().toLocaleLowerCase();
    return [...data.rows].filter((r) => !q || r.symbol.toLocaleLowerCase().includes(q) || r.company_id.toLowerCase().includes(q))
      .sort((a, b) => (a.methods.P1.rank ?? Number.MAX_SAFE_INTEGER) - (b.methods.P1.rank ?? Number.MAX_SAFE_INTEGER) || a.symbol_index - b.symbol_index);
  }, [data, search]);

  return <section aria-labelledby="latest-ranking-title" className="space-y-4 rounded-2xl border-2 border-slate-300 bg-white p-4 shadow-sm dark:border-slate-600 dark:bg-slate-800 sm:p-5">
    <header className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-bold text-amber-700 dark:text-amber-300">{data?.status === "PREPARATION_UNCONFIRMED" ? "آماده‌سازی تأییدنشده · رتبهٔ رسمی نیست" : "تاریخی · رتبهٔ جاری نیست"}</p>
        <h2 id="latest-ranking-title" className="mt-1 text-xl font-black sm:text-2xl">آخرین رتبه‌بندی موجود — P1</h2>
        <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">P1 / valuation_0 · تاریخ ارزیابی {data ? date(data.evaluation_date) : "در حال خواندن…"} · رتبهٔ اول صرفاً رتبه است، نه سفارش خرید.</p>
      </div>
      {data && <span className="rounded-full bg-amber-100 px-3 py-1 text-sm font-bold text-amber-900 dark:bg-amber-950 dark:text-amber-100">{data.status === "HISTORICAL" ? "تاریخی" : "آماده‌سازی تأییدنشده"} · {data.evaluation_date}</span>}
    </header>
    {error ? <div role="alert" className="rounded-xl border border-rose-300 bg-rose-50 p-3 text-sm leading-7 text-rose-950 dark:bg-rose-950/30 dark:text-rose-100"><p>{error}</p><button className="mt-2 underline" onClick={() => setAttempt((v) => v + 1)}>تلاش دوباره</button></div> : !data ? <p role="status" className="text-sm">در حال خواندن خروجی مشخص رتبه‌بندی…</p> : <>
      <div className="grid gap-2 text-xs sm:grid-cols-2 lg:grid-cols-4">
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">ارزیابی مشترک: <b>{date(data.evaluation_date)}</b></p>
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">cutoff انتشار: <b dir="ltr">{data.publication_cutoff_at}</b></p>
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">دریافت TSETMC: <b dir="ltr">{data.source_provenance?.TSETMC?.retrieved_at_range_utc ? `${data.source_provenance.TSETMC.retrieved_at_range_utc[0]} – ${data.source_provenance.TSETMC.retrieved_at_range_utc[1]} UTC` : "ثبت نشده"}</b></p>
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">تازگی مالی: انتشار تا <b>{date(data.source_provenance?.financial_archive?.latest_published_at)}</b> · دوره تا {date(data.source_provenance?.financial_archive?.latest_period_end)} · دریافت {data.source_provenance?.financial_archive?.received_at_status === "UNKNOWN_IN_ARCHIVE" ? "نامعلوم" : "ثبت‌شده"}</p>
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">تازگی فروش: انتشار تا <b>{date(data.source_provenance?.monthly_sales_archive?.latest_published_at)}</b> · دوره {data.source_provenance?.monthly_sales_archive?.latest_event_period || "ثبت نشده"} · دریافت نامعلوم</p>
        <p className="rounded-lg bg-slate-50 p-2 dark:bg-slate-900">P1 امتیازدار: <b>{fmt(data.scored_count.P1, 0)} از {fmt(data.universe_count, 0)}</b> · بی‌امتیاز: <b>{fmt(data.unscored_count.P1, 0)}</b></p>
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <label className="text-sm">نسخهٔ رتبه‌بندی <select value={version} onChange={(e) => setVersion(e.target.value as "v12-37" | "v12-36" | "v12-35" | "v12-34" | "v12-33" | "v12-32" | "v12-31")} className="ms-2 rounded-lg border border-slate-300 bg-transparent px-2 py-2"><option value="v12-37">بازبینی ایمنی زنجیرهٔ مالی، دادهٔ امتیاز بدون تغییر · V12.37</option><option value="v12-36">استخراج اصلاح‌شده از آرشیو محلی · V12.36</option><option value="v12-35">دادهٔ رسمی TSETMC تا 2026-10-21 · V12.35</option><option value="v12-34">بازسازی محلی · 2026-10-14 · V12.34</option><option value="v12-33">بازسازی محلی · 2026-10-03 · V12.33</option><option value="v12-32">بازسازی تاریخی · 2026-02-24 · V12.32</option><option value="v12-31">نسخهٔ تاریخی · V12.31</option></select></label>
        <label className="text-sm">جست‌وجوی نماد <input value={search} onChange={(e) => setSearch(e.target.value)} className="ms-2 rounded-lg border border-slate-300 bg-transparent px-3 py-2" placeholder="نماد یا company_id" /></label>
        <label className="flex items-center gap-2 text-sm"><input type="checkbox" checked={comparison} onChange={(e) => setComparison(e.target.checked)} />نمایش مقایسهٔ P3 / w0</label>
        <a className="text-sm underline" href={`${import.meta.env.BASE_URL}research/${version}/latest-ranking.csv`} download>دریافت CSV همین نسخه</a>
        <a className="text-sm underline" href={`${import.meta.env.BASE_URL}research/${version}/current-ranking-input-gaps.fa.md`} target="_blank" rel="noreferrer">محدودیت‌ها و ورودی‌های مفقود</a>
      </div>
      <div className="max-h-[65vh] overflow-auto rounded-xl border border-slate-200 dark:border-slate-700">
        <table className="w-full min-w-[760px] text-right text-sm">
          <thead className="sticky top-0 bg-slate-100 dark:bg-slate-900"><tr><th className="p-2">رتبهٔ P1</th><th className="p-2">نماد</th><th className="p-2">امتیاز P1</th><th className="p-2">تاریخ ارزیابی</th><th className="p-2">کیفیت / پوشش</th>{comparison && <><th className="p-2">رتبهٔ P3</th><th className="p-2">امتیاز P3</th></>}</tr></thead>
          <tbody>{rows.map((r) => <tr key={r.company_id} className="border-t border-slate-200 align-top dark:border-slate-700">
            <td className="p-2">{fmt(r.methods.P1.rank, 0)}</td><th className="p-2 font-semibold">{r.symbol}<span className="block font-mono text-[10px] font-normal text-slate-500" dir="ltr">{r.company_id}</span></th>
            <td className="p-2">{fmt(r.methods.P1.score)}{r.methods.P1.score == null && <span className="block max-w-52 text-xs text-rose-700 dark:text-rose-300">{r.methods.P1.scoreability_reason || "پوشش وزن‌دار کمتر از ۵۰٪"}</span>}</td>
            <td className="p-2">{date(r.evaluation_date)}<span className="block text-xs text-slate-500">قیمت: {date(r.price_effective_date)}</span><span className="block text-xs text-slate-500">صورت مالی: {date(r.financial_factor_period_end || r.financial_period_end)}</span><span className="block text-xs text-slate-500">فروش: {r.monthly_sales_latest_period || "بدون دورهٔ مجاز"}</span></td>
            <td className="p-2"><span>{r.methods.P1.score == null ? "بدون امتیاز" : data.status === "HISTORICAL" ? "امتیاز تاریخی" : "امتیاز آماده‌سازی"}</span><span className="block text-xs text-slate-500">پوشش {fmt(r.methods.P1.financial_factor_coverage * 100, 1)}٪ · DQ {fmt(r.dq, 2)}</span><span className="block text-[10px] text-slate-500">وضعیت معاملهٔ جاری: نامعلوم</span>
              <details className="mt-1"><summary className="cursor-pointer text-xs underline">جزئیات عوامل و داده</summary><div className="mt-2 max-w-xl"><p className="text-xs">مقادیر null با mask قرارداد مدیریت شده‌اند؛ وضعیت معامله، صلاحیت امتیازدهی نیست.</p><div className="mt-2 grid grid-cols-1 gap-x-4 sm:grid-cols-2">{Object.entries(r.raw_factors).map(([name, value]) => <div key={name} className="border-t border-slate-100 py-1 text-xs dark:border-slate-700"><b>{labels[name] || name}</b>: {fmt(value)} · {r.observed_factors[name] ? "مشاهده‌شده" : "mask/default"}</div>)}</div></div></details>
            </td>
            {comparison && <><td className="p-2">{fmt(r.methods.P3.rank, 0)}</td><td className="p-2">{fmt(r.methods.P3.score)}</td></>}
          </tr>)}</tbody>
        </table>
      </div>
      <details className="text-xs leading-6"><summary className="cursor-pointer font-semibold">منبع و محدودیت‌ها</summary><p>منبع صریح: {data.source.path} · مجموعه {data.source.dataset_id} · SHA-256 {data.source.sha256}. قرارداد {data.contract_id} · SHA-256 {data.contract_sha256}. محاسبه‌گر {data.scorer_version}. زمان محاسبه {data.computed_at_tehran}.</p><p>زمان cutoff انتشار از زمان دریافت جداست؛ منبع زمان دریافت ندارد. این جدول بازپخش امتیاز در تاریخ داده است و تصمیم O00 یا نتیجهٔ ارزیابی آینده نیست.</p><ul className="list-disc px-5">{data.limitations.map((x) => <li key={x}>{x}</li>)}</ul></details>
      <p className="rounded-lg bg-amber-50 p-3 text-xs leading-6 text-amber-950 dark:bg-amber-950/30 dark:text-amber-100">این رتبه‌بندی برای تاریخ دادهٔ {data.evaluation_date} است و «آماده‌سازی تأییدنشده» می‌ماند. دریافت TSETMC زمان‌دار است؛ زمان دریافت آرشیو مالی و فروش ثبت نشده و دسترسی در cutoff گذشته اثبات نمی‌شود. این خروجی ادعای PIT یا رتبهٔ زنده ندارد. عوامل مالی به دورهٔ واقعی صورت مالی متصل‌اند؛ عوامل مفقود طبق mask و پوشش قرارداد مدیریت شده‌اند.</p>
    </>}
  </section>;
}
