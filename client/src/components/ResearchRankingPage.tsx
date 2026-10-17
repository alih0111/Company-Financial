import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import ResearchTradeHistory from "./ResearchTradeHistory";
import ResearchV7Results from "./ResearchV7Results";
import { FaArrowLeft, FaCheckCircle, FaFlask, FaSyncAlt } from "react-icons/fa";

export interface ResearchRow {
  rank: number;
  symbol: string;
  name: string;
  reason1: string;
  reason2: string;
  data_date: string;
  financial_period_end: string;
  data_status: string;
}

export interface ResearchSnapshot {
  schema_version: number;
  research_version?: string;
  universe_count?: number;
  coverage_status?: string;
  coverage_breakdown?: Record<string, number>;
  run_id: string;
  status: "historical_research" | "unavailable";
  method: string;
  method_version?: string;
  as_of?: string;
  eligible_count?: number;
  price_archive_endpoint?: string;
  current_ranking_available?: boolean;
  current_ranking_reason?: string;
  note?: string;
  reason?: string;
  input_sha256?: string;
  method_sha256?: string;
  limitations?: string[];
  validity_label?: string;
  performance_status?: string;
  performance_note?: string;
  economic_example?: string;
  metadata_completeness?: string;
  freshness_note?: string;
  v6_details?: { model_features: string[]; coefficients: Array<{block_start: string; feature: string; coefficient: number}>; trained_blocks: number; fallback_blocks: number; training_note: string };
  buffer_portfolios?: Array<{ method: string; as_of: string; symbols: string[] }>;
  performance?: Array<{ method: string; final_toman: number; start: string; end: string; max_drawdown_percent: number; ledger: string; book_cash_toman: number; economic_final_toman: number | null }>;
  rows: ResearchRow[];
}

function dateLabel(value?: string) {
  if (!value) return "احراز نشده";
  const date = new Date(`${value}T12:00:00+03:30`);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("fa-IR", {
    year: "numeric", month: "long", day: "numeric", timeZone: "Asia/Tehran",
  }).format(date);
}

export function ResearchRankingView({ data }: { data: ResearchSnapshot }) {
  return (
    <section dir="rtl" className="space-y-6 text-gray-800 dark:text-gray-100">
      <div className="relative overflow-hidden rounded-3xl border border-emerald-200 bg-gradient-to-bl from-emerald-50 via-white to-teal-50 p-6 sm:p-8 dark:border-emerald-800 dark:from-gray-900 dark:via-gray-900 dark:to-emerald-950">
        <div className="flex flex-wrap items-center justify-between gap-4">
          <span className="inline-flex items-center gap-2 rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"><FaFlask /> پژوهش بازده · {data.research_version ?? "V3"}</span>
          <Link to="/ranking" className="flex items-center gap-2 text-sm text-gray-500 hover:text-emerald-700">رتبه‌بندی اصلی <FaArrowLeft /></Link>
        </div>
        <h1 className="mt-5 text-2xl font-bold sm:text-3xl">رتبه‌بندی نمادهای دارای دادهٔ کافی</h1>
        <p className="mt-3 max-w-3xl text-sm leading-7 text-gray-600 dark:text-gray-300">اولویت بررسی بر پایهٔ تغییر سود عملیاتی فصل نسبت به هم‌فصل سال قبل، با درنظرگرفتن اندازهٔ دارایی‌ها. کاهش زیان به معنی سوددهی نیست.</p>
        {data.validity_label && <p className="mt-3 text-xs leading-6 text-emerald-800 dark:text-emerald-300">{data.validity_label}</p>}
        <div className="mt-6 grid grid-cols-3 gap-2 sm:gap-3">
          <div className="rounded-2xl border border-white/70 bg-white/80 p-4 dark:border-gray-700 dark:bg-gray-800"><p className="text-xs text-gray-500">تاریخ رتبه‌بندی</p><p className="mt-2 font-bold">{dateLabel(data.as_of)}</p><p className="mt-1 text-xs text-gray-500" dir="ltr">{data.as_of}</p></div>
          <div className="rounded-2xl border border-white/70 bg-white/80 p-4 dark:border-gray-700 dark:bg-gray-800"><p className="text-xs text-gray-500">نامزدهای دارای دادهٔ کافی</p><p className="mt-2 text-2xl font-bold">{(data.eligible_count ?? 0).toLocaleString("fa-IR")} <span className="text-sm font-normal text-gray-500">نماد از {(data.universe_count ?? 254).toLocaleString("fa-IR")}</span></p><p className="mt-1 text-xs text-gray-500">جامعهٔ محلی پژوهش؛ پوشش کل بازار نیست</p></div>
          <div className="rounded-2xl border border-white/70 bg-white/80 p-4 dark:border-gray-700 dark:bg-gray-800"><p className="text-xs text-gray-500">روش</p><p className="mt-2 text-xl font-bold" dir="ltr">{data.method}</p><p className="mt-1 text-xs text-gray-500">امتیاز، درصد سود موردانتظار نیست</p></div>
        </div>
      </div>

      {!data.current_ranking_available && <div role="note" className="rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 text-sm leading-7 text-amber-900 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-200"><strong>این فهرست، رتبه‌بندی امروز نیست.</strong> {data.current_ranking_reason} آخرین آرشیو قیمت: {dateLabel(data.price_archive_endpoint)}؛ تاریخ معتبر این فهرست در بالا درج شده است.</div>}

      {data.freshness_note && <section className="rounded-2xl border border-gray-200 bg-white p-5 text-sm leading-7 dark:border-gray-700 dark:bg-gray-800"><h2 className="font-bold">اطلاعات بنیاد در زمان تصمیم</h2><p className="mt-2">{data.freshness_note}</p>{data.v6_details && <details className="mt-3"><summary className="cursor-pointer">جزئیات مدل پژوهشی</summary><p>{data.v6_details.training_note}</p><p>بلوک آموزش‌دیده: {data.v6_details.trained_blocks.toLocaleString("fa-IR")}؛ بلوک با روش جایگزین S2: {data.v6_details.fallback_blocks.toLocaleString("fa-IR")}</p><ul dir="ltr" className="mt-2 text-xs">{data.v6_details.coefficients.map((c) => <li key={`${c.block_start}-${c.feature}`}>{c.block_start} · {c.feature}: {c.coefficient.toFixed(5)}</li>)}</ul></details>}</section>}

      {data.performance && <section aria-labelledby="research-wealth-title" className="rounded-3xl border border-gray-200 bg-white p-5 sm:p-6 dark:border-gray-700 dark:bg-gray-800">
        <h2 id="research-wealth-title" className="text-lg font-bold">اگر ۱۰۰ میلیون سرمایه داشتیم</h2>
        <p className="mt-2 text-sm leading-7">{data.performance_status}</p>
        <p className="mt-2 text-xs leading-6 text-gray-600 dark:text-gray-300">{data.performance_note}</p>
        {data.performance.length === 0 ? <p role="status" className="mt-4 text-sm text-gray-500">مقایسهٔ بازده با دادهٔ کافی در دسترس نیست.</p> : <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">{data.performance.map((result) => <article key={result.method} className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700">
          <h3 className="text-sm font-bold">{{S2_publication:"S2 دوهفته‌ای · جامعهٔ طبیعی",S2_common:"S2 · هم‌جامعه با مدل",equal_feature_ranks:"ترکیب مساوی · هم‌جامعه",ridge_rank:"مدل خطی پژوهشی · هم‌جامعه",existing_choose:"انتخابگر قبلی",S2_monthly:"S2 ماهانه",S2_biweekly:"S2 دوهفته‌ای",balanced:"Balanced",profit_growth:"رشد سود ساده",equal_weight_all:"وزن مساوی همهٔ واجدان شروط",S2_buffer15_monthly:"S2 با نگهداری تا رتبهٔ ۱۵ · ماهانه",S2_buffer15_biweekly:"S2 با نگهداری تا رتبهٔ ۱۵ · دوهفته‌ای"}[result.method] ?? result.method}</h3>
          <span className="mt-2 inline-block rounded-full bg-amber-100 px-2 py-1 text-[11px] text-amber-900 dark:bg-amber-950 dark:text-amber-200">{result.ledger}</span>
          <p className="mt-3 text-xl font-bold">{(result.final_toman / 1_000_000).toLocaleString("fa-IR", {maximumFractionDigits:2})} <span className="text-xs font-normal">میلیون تومان NAV</span></p>
          <p className="mt-2 text-xs leading-6 text-gray-600 dark:text-gray-300">افت بیشینه: {result.max_drawdown_percent.toLocaleString("fa-IR", {maximumFractionDigits:2})}٪</p>
          <p className="mt-1 text-xs leading-6 text-gray-600 dark:text-gray-300">از {dateLabel(result.start)} تا {dateLabel(result.end)}</p>
          {result.method === "equal_weight_all" && <p className="mt-2 text-xs leading-6 text-gray-500">این مرجع می‌تواند بیش از ۱۰ سهم داشته باشد.</p>}
        </article>)}</div>}
        <details className="mt-5 border-t border-gray-100 pt-4 text-xs leading-7 dark:border-gray-700"><summary className="cursor-pointer font-semibold">نقد، مطالبات و فرض‌های شبیه‌سازی</summary><p className="mt-3">بازده اقتصادی کل راهبرد هنوز نامعلوم است. نقد مدل شاخصی، موجودی تسویه‌شدهٔ یک حساب واقعی نیست. بازهٔ قدیمی تا آوریل فقط برای تطبیق پژوهش قبلی نگه داشته شده؛ انتهای کم‌کیفیت قیمت در مقایسهٔ اصلی وارد نشده است.</p><p className="mt-3">{data.economic_example}</p><p className="mt-3">اگر روش نگهداری تا رتبهٔ ۱۵ را مقایسه می‌کنید، سبد آن ممکن است با ۱۰ رتبهٔ اول این فهرست فرق کند. این فهرست همان امتیاز S2 است؛ سبد آن آزمایش جای روش فعلی را نگرفته است.</p>
          {data.buffer_portfolios?.map((portfolio) => <div key={portfolio.method} className="mt-4 rounded-xl bg-gray-50 p-3 dark:bg-gray-900"><h3 className="font-semibold">سبد شاخصی آزمایش نگهداری تا رتبهٔ ۱۵ · {portfolio.method.endsWith("biweekly") ? "دوهفته‌ای" : "ماهانه"}</h3><p>در پایان {dateLabel(portfolio.as_of)}؛ این سبد تاریخی با فهرست مهر ۱۴۰۵ در بالا هم‌تاریخ نیست.</p><p className="mt-2 font-medium">{portfolio.symbols.length ? portfolio.symbols.join("، ") : "بدون موقعیت باز"}</p></div>)}
        </details>
      </section>}

      <div className="overflow-hidden rounded-3xl border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-800">
        <div className="border-b border-gray-100 px-5 py-5 dark:border-gray-700"><h2 className="font-bold">نمادهای اولویت‌دار برای بررسی</h2><p className="mt-2 text-xs leading-6 text-gray-500">رتبهٔ بالاتر فقط نتیجهٔ این معیار پژوهشی در تاریخ داده است. کفایت امتیازدهی، امکان اجرای معامله یا سود آینده را تأیید نمی‌کند.</p></div>
        {data.rows.length === 0 ? <div role="status" className="p-10 text-center leading-8 text-gray-500">نامزد معتبری برای نمایش وجود ندارد.<p className="text-sm">{data.reason ?? "مدارک لازم برای رتبه‌بندی کامل نشده است."}</p></div> : (
          <>
          <ol className="divide-y divide-gray-100 dark:divide-gray-700 md:hidden">
            {data.rows.map((row) => <li key={row.symbol} className="space-y-3 p-5">
              <div className="flex items-center justify-between gap-3"><div className="flex items-center gap-3"><span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-100 font-bold text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">{row.rank.toLocaleString("fa-IR")}</span><h3 className="text-lg font-bold">{row.name}</h3></div><span className="text-xs text-gray-500">{dateLabel(row.data_date)}</span></div>
              <p className="text-sm leading-7">{row.reason1}<span className="block text-xs text-gray-500 dark:text-gray-400">{row.reason2}</span></p>
              <p className="flex items-start gap-2 text-xs leading-6 text-emerald-700 dark:text-emerald-300"><FaCheckCircle className="mt-1 shrink-0" aria-hidden="true" />{row.data_status}</p>
              <p className="text-xs text-gray-500">دورهٔ مالی: {dateLabel(row.financial_period_end)}</p>
            </li>)}
          </ol>
          <div className="hidden overflow-x-auto md:block">
            <table className="w-full min-w-[740px] text-right text-sm">
              <caption className="sr-only">رتبه‌بندی پژوهشی مربوط به {dateLabel(data.as_of)}</caption>
              <thead className="bg-gray-50 text-xs text-gray-500 dark:bg-gray-900/40"><tr><th scope="col" className="px-5 py-4">رتبه</th><th scope="col" className="px-4 py-4">نماد</th><th scope="col" className="px-4 py-4">دلیل حضور</th><th scope="col" className="px-4 py-4">تاریخ داده</th><th scope="col" className="px-4 py-4">کفایت داده</th></tr></thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">{data.rows.map((row) => <tr key={row.symbol} className="hover:bg-emerald-50/50 dark:hover:bg-emerald-950/20"><td className="px-5 py-5"><span className={`inline-flex h-9 w-9 items-center justify-center rounded-xl font-bold ${row.rank <= 3 ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200" : "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-200"}`}>{row.rank.toLocaleString("fa-IR")}</span></td><th scope="row" className="px-4 py-5 text-base font-bold">{row.name}{row.name !== row.symbol && <p className="text-xs font-normal text-gray-500">{row.symbol}</p>}</th><td className="px-4 py-5 leading-7"><p>{row.reason1}</p><p className="text-xs text-gray-500 dark:text-gray-400">{row.reason2}</p></td><td className="px-4 py-5"><p>{dateLabel(row.data_date)}</p><p className="mt-1 text-xs text-gray-500">دورهٔ مالی: {dateLabel(row.financial_period_end)}</p></td><td className="max-w-[190px] px-4 py-5 text-xs leading-6 text-emerald-700 dark:text-emerald-300"><FaCheckCircle className="mb-1" aria-hidden="true" />{row.data_status}</td></tr>)}</tbody>
            </table>
          </div>
          </>
        )}
      </div>
      {data.coverage_breakdown && <details className="rounded-2xl border border-amber-200 bg-amber-50 p-5 text-sm dark:border-amber-900 dark:bg-amber-950/30"><summary className="cursor-pointer font-semibold">پوشش داده و علت کنارگذاشتن نمادها</summary><p className="mt-3 leading-7">کمبود داده به معنی ضعیف‌بودن سهم نیست. عبور از شروط داده نیز امکان اجرای معامله را تأیید نمی‌کند.</p><dl className="mt-4 space-y-3">{Object.entries(data.coverage_breakdown).map(([key, count]) => <div key={key} className="flex justify-between gap-4"><dt>{{rankable_execution_uncertified:"واجد شروط امتیاز پژوهشی؛ اجرا تأیید نشده",outside_economic_model:"خارج از مدل شرکت عملیاتی",rankable_but_trade_filter_failed:"دادهٔ مالی کافی؛ شروط نقدشوندگی برقرار نیست",unprocessed_or_unlinked_report:"گزارش جدید با پردازش یا اتصال ناقص",insufficient_evidence:"شواهد ناکافی برای قضاوت"}[key] ?? key}</dt><dd>{count.toLocaleString("fa-IR")}</dd></div>)}</dl></details>}
      <details className="rounded-2xl border border-gray-200 bg-white p-5 text-sm dark:border-gray-700 dark:bg-gray-800"><summary className="cursor-pointer font-semibold">روش، محدودیت‌ها و نسخهٔ داده</summary><p className="mt-4 leading-7 text-gray-500">{data.note}</p><p className="mt-3 leading-7 text-gray-500">{data.metadata_completeness}</p><ul className="mt-3 list-inside list-disc space-y-2 leading-7 text-gray-500">{data.limitations?.map((line) => <li key={line}>{line}</li>)}</ul><dl className="mt-4 space-y-3 text-xs text-gray-500"><dt>نسخهٔ روش</dt><dd>{data.method_version ?? data.method}</dd><dt>شناسهٔ پژوهش</dt><dd dir="ltr" className="break-all text-right">{data.run_id}</dd><dt>هش ورودی</dt><dd dir="ltr" className="break-all text-right">{data.input_sha256}</dd></dl></details>
    </section>
  );
}

export default function ResearchRankingPage() {
  const [data, setData] = useState<ResearchSnapshot | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    fetch(`${import.meta.env.BASE_URL}research/return-v6.json`, { signal: controller.signal, cache: "no-cache" })
      .then(async (response) => {
        if (!response.ok) throw new Error("دریافت خروجی پژوهش ممکن نشد.");
        if (!response.headers.get("content-type")?.includes("application/json")) throw new Error("فایل خروجی پژوهش هنوز در دسترس نیست؛ کمی بعد دوباره تلاش کنید.");
        const result: unknown = await response.json();
        if (!result || typeof result !== "object" || !("schema_version" in result) || result.schema_version !== 1 || !("rows" in result) || !Array.isArray(result.rows) || !("run_id" in result)) throw new Error("نسخهٔ فایل رتبه‌بندی معتبر نیست.");
        setData(result as ResearchSnapshot);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, [attempt]);
  if (error) return <div role="alert" dir="rtl" className="rounded-2xl border border-red-200 bg-red-50 p-8 text-red-800"><p>{error}</p><button type="button" className="mt-4 inline-flex items-center gap-2 rounded-xl bg-white px-4 py-2" onClick={() => setAttempt((value) => value + 1)}><FaSyncAlt /> تلاش دوباره</button></div>;
  if (!data) return <div role="status" dir="rtl" className="rounded-2xl bg-white p-12 text-center text-gray-500 dark:bg-gray-800">در حال دریافت رتبه‌بندی پژوهشی…</div>;
  return <><ResearchRankingView data={data} /><div dir="rtl" className="mt-6 space-y-6 text-gray-800 dark:text-gray-100"><ResearchV7Results sourceRun={data.run_id} /><ResearchTradeHistory runId={data.run_id} /></div></>;
}
