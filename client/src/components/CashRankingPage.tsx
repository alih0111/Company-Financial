import { Fragment, useEffect, useMemo, useState } from "react";
import { API_BASE } from "../config";
import QvtRankingPage from "./QvtRankingPage";

type Stock = {
  company_id: string; symbol: string; score: number | null; rank?: number;
  financial_period: string | null; financial_age_days: number | null;
  reason?: string; status: string; reasons: string[]; warnings?: string[];
  review_priority?: boolean;
  review_order?: number;
  classification?: { category: "supported" | "watch" | "needs_evidence" | "specialized"; category_label: string;
    family: string; family_label: string; family_verified: boolean; industry: string | null;
    gaps: string[]; concerns: string[]; positive_evidence: string[];
    operating_profit_change_adjacent_ttm?: number; operating_margin_change_adjacent_ttm_pp?: number;
    classification_source?: { template: string; source_url: string; tracing_no: string } | null };
  cash_yield?: number; profit_yield?: number; cash_conversion?: number;
  debt_ratio?: number; current_ratio?: number; health?: number;
  market: { price_date?: string; price_rial?: number; price_source?: string;
    shares_count?: number; shares_observed_at?: string; median_traded_value_20_rial?: number; liquidity_traded_days?: number };
  financial_report?: { tracing_no: string; published_at: string; title: string } | null;
  volume_context?: { period: string; growth: number | null; status: string; window: string; scope: string; used_in_score: false };
};
type Ranking = {
  version: string; name: string; as_of: string; last_market_session: string;
  generated_at: string; snapshot_fresh: boolean; promotion_ready: false; real_orders: 0;
  method: string; limitations: string[]; ranked: Stock[]; unscored: Stock[];
  research: { common_rows: number; common_dates: number; date_range: string[];
    preliminary_pass: boolean; portfolio_scenarios: number; historical_view: string;
    paired_gain_vs_screen: { mean: number | null; lower: number | null; upper: number | null; n: number } };
  classification_summary?: Record<string, number>;
};
const number = (v: number | null | undefined, digits = 1) => v == null || !Number.isFinite(v) ? "—" : new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v);
const percent = (v: number | null | undefined) => v == null ? "—" : `${number(v * 100)}٪`;
const date = (v?: string | null) => v && !Number.isNaN(Date.parse(v)) ? new Intl.DateTimeFormat("fa-IR", { timeZone: "UTC" }).format(new Date(v)) : "—";
const normalize = (v: string) => v.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/[\s\u200c]/g, "");

export default function CashRankingPage() {
  const [view, setView] = useState<"cash" | "qvt">("cash");
  const [data, setData] = useState<Ranking | null>(null);
  const [error, setError] = useState("");
  const [query, setQuery] = useState("");
  const [list, setList] = useState<"supported" | "further" | "all">("supported");
  const [expanded, setExpanded] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let retry: number | undefined;
    const load = () => { fetch(`${API_BASE}/ranking/cash-review`, { signal: controller.signal, headers: { Authorization: `Bearer ${localStorage.getItem("token")}` } })
      .then(async response => { if (!response.ok) throw new Error("دریافت رتبه‌بندی جدید ممکن نشد؛ دوباره صفحه را باز کنید."); return response.json() as Promise<Ranking>; })
      .then(result => { if (result.version !== "cash-backed-review-v1" || result.promotion_ready !== false || result.real_orders !== 0) throw new Error("نسخهٔ رتبه‌بندی قابل تأیید نیست."); setData(result); if (!result.classification_summary) { setList("all"); retry = window.setTimeout(load, 15000); } })
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); });
    };
    load();
    return () => { controller.abort(); if (retry != null) window.clearTimeout(retry); };
  }, []);
  const stocks = useMemo(() => (data ? [...data.ranked, ...data.unscored] : []).filter(s =>
    normalize(s.symbol).includes(normalize(query)) && (query.trim() || list === "all" ||
      (list === "supported" ? s.classification?.category === "supported" : s.classification?.category === "watch" || s.classification?.category === "needs_evidence"))), [data, list, query]);
  const categoryTone = (category?: string) => category === "supported" ? "bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-200" : category === "watch" ? "bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200" : "bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300";
  return <div dir="rtl" className="space-y-5">
    <div className="flex flex-wrap gap-2">
      <button onClick={() => setView("cash")} className={`rounded-xl px-4 py-2 text-sm ${view === "cash" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-800"}`}>رتبه‌بندی جدید</button>
      <button onClick={() => setView("qvt")} className={`rounded-xl px-4 py-2 text-sm ${view === "qvt" ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-800"}`}>مقایسه با QVT قبلی</button>
    </div>
    {view === "qvt" ? <QvtRankingPage /> : <>
      <div className="rounded-2xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-900 space-y-3">
        <div className="flex flex-wrap items-center gap-3"><h1 className="text-xl font-bold">ارزندگی با پشتوانهٔ نقد</h1><span className="rounded-full bg-amber-100 px-3 py-1 text-xs text-amber-800 dark:bg-amber-900/40 dark:text-amber-200">در حال ارزیابی</span></div>
        <p className="text-sm leading-7 text-gray-600 dark:text-gray-300">سهم‌هایی بالاتر می‌آیند که سودشان پشتوانهٔ جریان نقد دارد، نسبت به ارزش بازار مناسب‌اند و ترازنامهٔ سالم‌تری دارند. امتیاز، احتمال سود یا دستور خرید نیست.</p>
        {data && <p className="text-xs text-gray-500">قیمت پایان معامله: {date(data.last_market_session)} · {number(data.classification_summary?.supported, 0)} نماد با شواهد کافی برای فهرست بررسی · {number(data.ranked.length, 0)} نماد دارای امتیاز پایه</p>}
        {data && !data.snapshot_fresh && <p role="status" className="rounded-lg bg-amber-50 p-3 text-sm text-amber-800 dark:bg-amber-950/40 dark:text-amber-200">این یک تصویر قدیمی از بازار است؛ پیش از بررسی امروز باید اطلاعات به‌روز شود.</p>}
        {data && !data.classification_summary && <p role="status" className="text-sm text-gray-500">بازبینی دسته‌بندی در حال انجام است؛ امتیازهای قبلی فعلاً در دسترس‌اند.</p>}
      </div>
      {error && <p role="alert" className="rounded-xl bg-rose-50 p-4 text-rose-700 dark:bg-rose-950/40 dark:text-rose-200">{error}</p>}
      {!data && !error && <p role="status" className="p-5 text-gray-500">در حال دریافت رتبه‌بندی…</p>}
      {data && <>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap gap-2">{([["supported", "فهرست بررسی"], ["further", "بررسی بیشتر"], ["all", "همهٔ نمادها"]] as const).map(([key, label]) => <button key={key} onClick={() => setList(key)} className={`rounded-lg px-3 py-2 text-sm ${list === key ? "bg-indigo-100 text-indigo-800 dark:bg-indigo-950 dark:text-indigo-200" : "text-gray-500"}`}>{label}</button>)}</div>
          <input aria-label="جستجو در همه نمادها" placeholder="جستجو در همهٔ نمادها…" value={query} onChange={e => setQuery(e.target.value)} className="rounded-xl border border-gray-200 bg-white px-4 py-2 text-sm dark:border-gray-700 dark:bg-gray-900" />
        </div>
        <p className="text-xs leading-6 text-gray-500">فهرست بررسی به شواهد مثبت در دو گزارش پیاپی نیاز دارد. «بررسی بیشتر» می‌تواند ناشی از اطلاعات ناقص یا نگرانی واقعی باشد؛ دلیل هر نماد مشخص است. شرکت‌های دارای مدل متفاوت در «همهٔ نمادها» دیده می‌شوند. این دسته‌ها تأیید خرید نیستند.</p>
        {query.trim() && <p className="text-xs text-gray-500">نتیجهٔ جستجو از تمام نمادهاست.</p>}
        <div className="overflow-x-auto rounded-2xl border border-gray-200 dark:border-gray-700">
          <table className="w-full text-right text-sm"><thead className="bg-gray-50 text-gray-500 dark:bg-gray-800"><tr><th className="p-3">{list === "supported" && !query.trim() ? "اولویت" : "رتبهٔ امتیاز"}</th><th className="p-3">نماد</th><th className="p-3">امتیاز پایه</th><th className="p-3">دسته و دلیل بررسی</th><th className="p-3">تاریخ مالی</th><th className="p-3">جزئیات</th></tr></thead>
            <tbody>{stocks.map(s => <Fragment key={s.company_id}>
              <tr className="border-t border-gray-100 bg-white dark:border-gray-800 dark:bg-gray-900"><td className="p-3 text-gray-500">{number(list === "supported" && !query.trim() ? s.review_order : s.rank, 0)}</td><td className="p-3 font-bold whitespace-nowrap">{s.symbol}<p className="mt-1 max-w-36 truncate text-xs font-normal text-gray-500" title={s.classification?.industry || ""}>{s.classification?.industry}</p></td><td className="p-3 font-semibold tabular-nums">{number(s.score)}</td><td className="p-3 min-w-64"><span className={`inline-block rounded-full px-2 py-1 text-xs ${categoryTone(s.classification?.category)}`}>{s.classification?.category_label || s.status}</span><p className="mt-2 text-xs leading-6">{s.status}</p>{s.reason && <p className="text-xs text-gray-500">{s.reason}</p>}</td><td className="p-3 whitespace-nowrap text-gray-500">{date(s.financial_period)}</td><td className="p-3"><button aria-expanded={expanded === s.company_id} onClick={() => setExpanded(expanded === s.company_id ? null : s.company_id)} className="text-indigo-600 dark:text-indigo-300">{expanded === s.company_id ? "بستن" : "ببین"}</button></td></tr>
              {expanded === s.company_id && <tr className="bg-gray-50 dark:bg-gray-800/60"><td colSpan={6} className="p-5 space-y-3">
                {s.classification && <div className="space-y-2 text-xs leading-6"><p>نوع شرکت: <b>{s.classification.family_label}</b> · {s.classification.family_verified ? "با گزارش رسمی تطبیق داده شد" : "تطبیق رسمی کامل نیست"}{s.rank != null ? ` · رتبهٔ امتیاز پایه: ${number(s.rank, 0)}` : ""}</p>{s.classification.positive_evidence.length > 0 && <p>شواهد مثبت: {s.classification.positive_evidence.join("؛ ")}</p>}{s.classification.concerns.length > 0 && <p className="text-amber-700 dark:text-amber-300">نگرانی مشاهده‌شده: {s.classification.concerns.join("؛ ")}</p>}{s.classification.gaps.length > 0 && <p className="text-gray-500">بررسی تکمیل‌نشده: {s.classification.gaps.join("؛ ")}</p>}{s.classification.operating_profit_change_adjacent_ttm != null && <p>تغییر سود عملیاتی دوازده‌ماهه نسبت به گزارش قبلی: {percent(s.classification.operating_profit_change_adjacent_ttm)}؛ تغییر حاشیهٔ سود: {number(s.classification.operating_margin_change_adjacent_ttm_pp)} واحد درصد.</p>}</div>}
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4"><p>بازده سود محدود به نقد: <b>{percent(s.cash_yield)}</b></p><p>جریان نقد ÷ سود خالص: <b>{percent(s.cash_conversion)}</b></p><p>بدهی ÷ دارایی: <b>{percent(s.debt_ratio)}</b></p><p>نسبت جاری: <b>{number(s.current_ratio, 2)}</b></p></div>
                <p className="text-xs leading-6 text-gray-600 dark:text-gray-300">قیمت خام: {number(s.market.price_rial, 0)} ریال در {date(s.market.price_date)}؛ تعداد سهام مشاهده‌شده: {number(s.market.shares_count, 0)} در {date(s.market.shares_observed_at)}. میانهٔ ارزش معاملات در {number(s.market.liquidity_traded_days, 0)} روز معامله‌شده: {number(s.market.median_traded_value_20_rial == null ? null : s.market.median_traded_value_20_rial / 10_000_000_000)} میلیارد تومان.</p>
                {s.financial_report && <p className="text-xs text-gray-500">گزارش کدال {s.financial_report.tracing_no}؛ انتشار {date(s.financial_report.published_at)}؛ {s.financial_report.title}</p>}
                {s.classification?.classification_source?.source_url.startsWith("https://www.codal.ir/Reports/") && <p><a href={s.classification.classification_source.source_url} target="_blank" rel="noreferrer" className="text-xs text-indigo-600 dark:text-indigo-300">گزارش رسمیِ مبنای نوع شرکت</a></p>}
                {s.volume_context && <p className="text-xs leading-6 text-gray-500">حجم فروش گروه‌های قابل مقایسه: {percent(s.volume_context.growth)} تا {date(s.volume_context.period)}. {s.volume_context.window}. {s.volume_context.scope}. این داده در امتیاز دخالت ندارد. {s.volume_context.growth == null ? s.volume_context.status : ""}</p>}
                {[...s.reasons, ...(s.warnings || [])].length > 0 && <p className="text-sm text-amber-700 dark:text-amber-300">{[...s.reasons, ...(s.warnings || [])].join("؛ ")}</p>}
                {s.market.price_source?.startsWith("https://cdn.tsetmc.com/") && <a target="_blank" rel="noreferrer" href={s.market.price_source} className="text-xs text-indigo-600 dark:text-indigo-300">منبع قیمت تاریخ‌دار</a>}
              </td></tr>}
            </Fragment>)}</tbody>
          </table>{stocks.length === 0 && <p className="p-6 text-center text-gray-500">نمادی پیدا نشد.</p>}
        </div>
        <details className="rounded-2xl border border-gray-200 p-5 text-sm dark:border-gray-700"><summary className="cursor-pointer font-semibold">روش محاسبه و نتیجهٔ بررسی تاریخی</summary><div className="mt-4 space-y-3 leading-7 text-gray-600 dark:text-gray-300">
          <p>{data.method}</p><p>بررسی روی {number(data.research.common_rows, 0)} مشاهده و {number(data.research.common_dates, 0)} تاریخ انجام شده است. {data.research.historical_view}. همهٔ {number(data.research.portfolio_scenarios, 0)} حالت شبیه‌سازی هزینه، تأخیر و فاصلهٔ بازچینی نگه داشته شده‌اند.</p>
          <p>آزمایش ذخیره‌شده روی طبقه‌بندی قبلی شرکت‌ها انجام شده است. با اصلاح نوع شرکت‌ها و دسته‌بندی شواهد، نسخهٔ فعلی باید دوباره ارزیابی تاریخی شود؛ نتایج قبلی، اثبات برتری این فهرست نیستند.</p>
          <p>دسته‌بندی تازه بر شواهد نوع شرکت، پایداری سود و گزارش‌های ماهانهٔ فعلی تکیه دارد. این فهرست هنوز ارزیابی تاریخی مستقل ندارد و مجوز معاملهٔ خودکار نیست.</p>
          {data.limitations.map(text => <p key={text}>• {text}</p>)}
          <p className="text-xs">ساخت تصویر: {date(data.generated_at)}؛ سفارش واقعی: صفر. نقدشوندگی و شرایط ورود باید جداگانه بررسی شوند.</p>
        </div></details>
      </>}
    </>}
  </div>;
}
