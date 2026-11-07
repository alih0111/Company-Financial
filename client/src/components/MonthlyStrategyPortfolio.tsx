import { useEffect, useState } from "react";
import { FaArrowDown, FaArrowUp, FaDownload, FaSyncAlt } from "react-icons/fa";
import { normalizeSymbol } from "./monthlyBasketPlan.js";
import { validateMonthlyPortfolio, type MonthlyPortfolio } from "./monthlyPortfolioData.js";

const base = `${import.meta.env.BASE_URL}strategies/factormix-033/performance/`;
const n = (value: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(value);
const pct = (value: number) => new Intl.NumberFormat("fa-IR", { style: "percent", maximumFractionDigits: 1 }).format(value);
const day = (value: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(`${value}T12:00:00Z`));
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-xs font-medium transition hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:hover:bg-slate-700";
const tone = (value: number) => value < 0 ? "text-rose-700 dark:text-rose-300" : "text-emerald-700 dark:text-emerald-300";

export default function MonthlyStrategyPortfolio() {
  const [data, setData] = useState<MonthlyPortfolio | null>(null);
  const [error, setError] = useState("");
  const [attempt, setAttempt] = useState(0);
  const [tab, setTab] = useState<"holdings" | "trades">("holdings");
  const [side, setSide] = useState<"ALL" | "BUY" | "SELL">("ALL");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError("");
    fetch(`${base}from-1401-monthly15-portfolio.json`, { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error("گزارش دارایی‌ها و معاملات در دسترس نیست.");
        return validateMonthlyPortfolio(await response.json());
      })
      .then(value => { if (!controller.signal.aborted) setData(value); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "گزارش سبد خوانده نشد."); });
    return () => controller.abort();
  }, [attempt]);

  const trades = data?.trades.map((trade, index) => ({ ...trade, index })).reverse()
    .filter(trade => (side === "ALL" || trade.side === side) && normalizeSymbol(trade.symbol).includes(normalizeSymbol(search))) ?? [];
  const pages = Math.max(1, Math.ceil(trades.length / 10));
  const currentPage = Math.min(page, pages - 1);
  const latestSession = data?.trades[data.trades.length - 1]?.session;
  const latest = data?.trades.filter(trade => trade.session === latestSession) ?? [];
  const latestSymbols = (direction: "BUY" | "SELL") => [...new Set(latest.filter(t => t.side === direction).map(t => t.symbol))];
  const unfilled = data?.positions.filter(p => p.action === "EXIT_UNFILLED") ?? [];

  return <section id="strategy-portfolio" aria-labelledby="strategy-portfolio-title" className="min-w-0 scroll-mt-4 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold text-violet-700 dark:text-violet-300">FactorMix · ماهانه ۱۵</p><h2 id="strategy-portfolio-title" className="mt-2 text-xl font-black">سبد و خریدوفروش‌ها</h2></div>
      <button type="button" className={button} onClick={() => setAttempt(value => value + 1)} disabled={!data && !error}><FaSyncAlt size={11} />بازخوانی سبد</button>
    </div>
    {!data && !error && <p role="status" className="mt-6 text-sm text-slate-500">در حال خواندن دارایی‌ها و معاملات…</p>}
    {error && <p role="alert" className="mt-5 text-sm leading-7 text-rose-700 dark:text-rose-300">{error}</p>}
    {data && <>
      <div className="mt-4 flex flex-wrap items-center gap-2 text-xs leading-7"><span className="rounded-lg bg-violet-50 px-3 py-1 font-semibold text-violet-800 dark:bg-violet-950/40 dark:text-violet-200">آخرین وضعیت ثبت‌شده · {day(data.as_of)}</span><span className="text-slate-500 dark:text-slate-400">بازپخش تاریخی از {day(data.start)} با ۱۰۰ میلیون تومان</span></div>
      <p className="mt-2 text-xs leading-7 text-slate-500 dark:text-slate-400">دارایی‌ها و اجراهای مدل تا تاریخ بالا نمایش داده می‌شوند. این گزارش حساب کارگزاری نیست؛ به‌روزرسانی رتبه‌ها یا پیشنهاد ماهانه، معامله‌ای به آن اضافه نمی‌کند.</p>
      <dl className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[["ارزش کل سبد · تومان", n(data.nav_toman)], ["نقد باقی‌مانده · تومان", n(data.cash_toman)], ["نماد موجود در سبد", n(data.positions.length)], ["معاملات ثبت‌شده", `${n(data.buy_count)} خرید · ${n(data.sell_count)} فروش`]].map(([label, value]) => <div key={label} className="col-span-1 min-w-0 rounded-xl bg-slate-50 p-3 first:col-span-2 last:col-span-2 sm:p-4 sm:first:col-span-1 sm:last:col-span-1 dark:bg-slate-900/50"><dt className="text-xs leading-6 text-slate-500 dark:text-slate-400">{label}</dt><dd className="mt-2 break-words text-lg font-black tabular-nums sm:text-xl">{value}</dd></div>)}
      </dl>
      <div className="mt-5 flex flex-wrap gap-2 border-b border-slate-200 pb-3 dark:border-slate-700" role="group" aria-label="نمایش سبد">
        {([ ["holdings", "دارایی‌های فعلی"], ["trades", "سابقهٔ خریدوفروش"] ] as const).map(([id, label]) => <button key={id} type="button" aria-pressed={tab === id} className={`${button} ${tab === id ? "!border-violet-600 !bg-violet-700 !text-white" : ""}`} onClick={() => setTab(id)}>{label}<span className="opacity-70">{n(id === "holdings" ? data.positions.length : data.trades.length)}</span></button>)}
      </div>
      {tab === "holdings" ? <div aria-label="دارایی‌های فعلی مدل" className="mt-5 space-y-4">
        <p className="text-xs leading-7 text-slate-500 dark:text-slate-400">وزن هر دارایی از کل ارزش سبد است. آخرین تصمیم سبد: {day(data.last_decision.date)}.</p>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">{data.positions.map(position => <article key={position.symbol} className="min-w-0 rounded-xl border border-slate-200 p-4 dark:border-slate-700">
          <div className="flex items-start justify-between gap-2"><h3 className="text-lg font-black">{position.symbol}</h3><span className={`rounded-lg px-2 py-1 text-xs ${position.action === "EXIT_UNFILLED" ? "bg-amber-50 text-amber-800 dark:bg-amber-950/40 dark:text-amber-200" : "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200"}`}>{position.action === "EXIT_UNFILLED" ? "فروش اجرا نشده" : "در سبد"}</span></div>
          <p className="mt-4 text-xl font-bold tabular-nums">{n(position.market_value_toman)} <span className="text-xs font-normal text-slate-500">تومان</span></p>
          <div className="mt-3 flex justify-between text-xs"><span className="text-slate-500 dark:text-slate-400">سهم از سبد</span><b>{pct(position.weight)}</b></div>
          <div aria-hidden="true" className="mt-2 h-1.5 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-700"><div className="h-full rounded-full bg-violet-500" style={{ width: `${position.weight * 100}%` }} /></div>
          <div className="mt-4 flex flex-wrap justify-between gap-2 text-xs"><span className="text-slate-500 dark:text-slate-400">سود / زیان باز</span><span className={`font-semibold tabular-nums ${tone(position.unrealized_pnl_toman)}`}>{n(position.unrealized_pnl_toman)} تومان · {pct(position.unrealized_pnl_toman / position.cost_basis_toman)}</span></div>
          <p className={`mt-3 text-xs leading-7 ${position.price_age_days ? "text-amber-700 dark:text-amber-300" : "text-slate-500 dark:text-slate-400"}`}>قیمت مبنا: {day(position.price_date)}{position.price_age_days > 0 && ` · ${n(position.price_age_days)} روز قدیمی‌تر از گزارش`}</p>
          <button type="button" className="mt-3 min-h-10 text-xs font-semibold text-violet-700 underline underline-offset-4 dark:text-violet-300" onClick={() => { setSearch(position.symbol); setSide("ALL"); setPage(0); setTab("trades"); }}>خریدوفروش‌های {position.symbol}</button>
        </article>)}</div>
        {!data.positions.length && <p className="py-6 text-center text-sm text-slate-500">دارایی بازی در این سبد ثبت نشده است.</p>}
        {unfilled.length > 0 && <p className="rounded-xl bg-amber-50 p-3 text-xs leading-7 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">{unfilled.map(p => p.symbol).join("، ")} هنوز فروخته نشده و در دارایی‌ها حساب می‌شود؛ به همین دلیل تعداد نمادها می‌تواند از هدف پنج سهم بیشتر باشد. مبلغ این دارایی وجه نقد قابل خرید نیست.</p>}
      </div> : <div className="mt-5 space-y-4" aria-label="دفتر خریدوفروش مدل">
        {latestSession && <div className="rounded-xl bg-slate-50 p-3 text-xs leading-7 dark:bg-slate-900/50"><p className="font-semibold">آخرین روز معامله · {day(latestSession)}</p><p className="mt-1"><span className="text-emerald-700 dark:text-emerald-300">خرید: </span>{latestSymbols("BUY").join("، ") || "نداشته"}<span className="mx-2 text-slate-400">/</span><span className="text-rose-700 dark:text-rose-300">فروش: </span>{latestSymbols("SELL").join("، ") || "نداشته"}</p></div>}
        <div className="flex flex-wrap items-end justify-between gap-3">
          <label className="grid w-full gap-2 text-xs sm:w-60">جست‌وجو در معاملات<input type="search" placeholder="نام نماد…" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} className="min-h-10 min-w-0 rounded-xl border border-slate-200 bg-transparent px-3 dark:border-slate-700" /></label>
          <div role="group" aria-label="نوع معامله" className="flex flex-wrap gap-2">{([["ALL", "همه"], ["BUY", "خریدها"], ["SELL", "فروش‌ها"]] as const).map(([value, label]) => <button type="button" key={value} aria-pressed={side === value} className={`${button} ${side === value ? "!border-violet-500 !bg-violet-50 !text-violet-800 dark:!bg-violet-950/40 dark:!text-violet-200" : ""}`} onClick={() => { setSide(value); setPage(0); }}>{label}</button>)}</div>
        </div>
        <p className="text-xs leading-7 text-slate-500 dark:text-slate-400">{n(trades.length)} اجرا · تازه‌ترین‌ها ابتدا · مبلغ پرداختی خرید یا دریافتی فروش با کارمزد؛ لغزش در مبلغ معامله منظور شده است.</p>
        <ol className="divide-y divide-slate-100 dark:divide-slate-700">{trades.slice(currentPage * 10, (currentPage + 1) * 10).map(trade => <li key={trade.index} className="grid grid-cols-2 items-center gap-3 py-4 sm:grid-cols-[1fr_1.3fr_1.5fr_1fr]">
          <div className="flex items-center gap-2"><span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-bold ${trade.side === "BUY" ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-200" : "bg-rose-50 text-rose-800 dark:bg-rose-950/40 dark:text-rose-200"}`}>{trade.side === "BUY" ? <FaArrowDown size={10} /> : <FaArrowUp size={10} />}{trade.side === "BUY" ? "خرید" : "فروش"}</span><b className="text-sm">{trade.symbol}</b></div>
          <div className="text-left text-xs leading-6 sm:text-right"><time dateTime={trade.session}>{day(trade.session)}</time><p className="text-slate-500 dark:text-slate-400">تصمیم {day(trade.decision)}</p></div>
          <p className="text-sm font-bold tabular-nums">{n(trade.gross_toman + (trade.side === "BUY" ? trade.fee_toman : -trade.fee_toman))} <span className="text-xs font-normal text-slate-500">تومان</span></p>
          <p className="text-left text-xs leading-6 text-slate-500 dark:text-slate-400 sm:text-right">کارمزد · تومان<br />{n(trade.fee_toman)}</p>
        </li>)}</ol>
        {!trades.length && <p role="status" className="py-6 text-center text-sm text-slate-500">معامله‌ای با این فیلتر پیدا نشد.</p>}
        <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4 dark:border-slate-700"><div className="flex items-center gap-3"><button type="button" className={button} disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>قبلی</button><span className="text-xs" aria-live="polite">صفحهٔ {n(currentPage + 1)} از {n(pages)}</span><button type="button" className={button} disabled={currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>بعدی</button></div><a className={button} href={base + data.downloads.trades} download><FaDownload size={11} />دریافت همهٔ معاملات</a></div>
      </div>}
    </>}
  </section>;
}
