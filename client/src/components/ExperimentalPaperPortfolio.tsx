import { useEffect, useState } from "react";
import PaperPortfolioTab from "./PaperPortfolioTab";

type Account = {
  account_id: string; cash_toman: number; initial_capital_toman: number; realized_pnl_toman: number;
  created_at_utc: string; ranking: { evaluation_date: string; status: string; top_candidate: { symbol: string } };
  accounting: { total_value_toman: number; holdings_value_toman: number; profit_loss_toman: number };
  holdings: Array<{ company_id: string; symbol: string; shares: number; last_price_rial: number; last_price_date: string; market_value_toman: number; unrealized_pnl_toman: number }>;
  paper_order: { side?: string; symbol: string; status: string; created_at_utc: string; waiting_reason: string; fill_event_id: string | null };
  event_log: Array<{ event_id: string; type: string; at_utc: string; reason: string; details: string }>;
};
type View = { profile: string; updated_at_utc: string; account: Account; limitations: string[]; outcome: { status: string; reason?: string }; strict_decision_authorized: boolean };
const number = (n: number) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 }).format(n);
const time = (s: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran" }).format(new Date(s));
const labels: Record<string, string> = {
  PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE: "منتظر قیمت و حجم نخستین جلسه پس از تصمیم",
  PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE: "معاملهٔ فرضی ثبت شد",
  EXPIRED_NO_FILL: "سفارش منقضی شد؛ معامله‌ای ثبت نشد",
  BLOCKED_EXECUTION: "به‌روزرسانی انجام نشد؛ جزئیات در پایین",
  NO_NEW_SESSION: "هنوز جلسهٔ تازه‌ای پس از تصمیم تأیید نشده",
  NO_NEW_MARK: "قیمت تازه برای ارزش‌گذاری نداریم",
  MARK_APPLIED: "ارزش روز به‌روزرسانی شد",
  CASH_ONLY: "حساب نقد است",
  FILL_APPLIED: "معاملهٔ فرضی در حساب ثبت شد",
  FILL_ALREADY_APPLIED: "این معامله قبلاً ثبت شده؛ ثبت تکراری انجام نشد",
  FILL_ELIGIBLE_PREVIEW_ONLY: "شرایط اجرای فرضی فراهم است؛ این اجرا فقط پیش‌نمایش بود",
  LATE_FILL_TIMING_AMBIGUOUS: "شواهد دیر رسیده‌اند؛ معامله به گذشته منتقل نمی‌شود",
  DECISION_RECORDED: "تصمیم تازه ثبت شد؛ منتظر جلسهٔ بعد",
  STATUS_ONLY: "نمایش آخرین وضعیت ذخیره‌شده",
};
const eventNames: Record<string, string> = {
  PUBLIC_PAPER_DRAFT_CREATED: "ساخت حساب", EXPERIMENTAL_PROFILE_ACCEPTED: "شروع آزمایش",
  PAPER_BUY_DECISION_RECORDED: "تصمیم خرید", PAPER_SELL_DECISION_RECORDED: "تصمیم فروش",
  PAPER_ORDER_PENDING: "سفارش منتظر", PAPER_FILL_DAILY_CLOSE_LIMITED_QUEUE: "خرید فرضی",
  PAPER_SELL_DAILY_CLOSE_LIMITED_QUEUE: "فروش فرضی", PAPER_MARK_TO_MARKET: "ارزش‌گذاری",
};

export default function ExperimentalPaperPortfolio() {
  const [view, setView] = useState<View | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  useEffect(() => {
    const ctl = new AbortController();
    setError("");
    fetch(`${import.meta.env.BASE_URL}research/paper-experimental/status.json`, { signal: ctl.signal, cache: "no-store" })
      .then(async r => { if (!r.ok) throw new Error("وضعیت سبد آزمایشی در دسترس نیست."); return r.json() as Promise<View>; })
      .then(x => {
        if (x.profile !== "EXPERIMENTAL_PAPER_V1" || x.strict_decision_authorized !== false ||
          x.account.cash_toman + x.account.accounting.holdings_value_toman !== x.account.accounting.total_value_toman)
          throw new Error("خروجی حساب ناسازگار است؛ از نمایش اعداد نامعتبر خودداری شد.");
        setView(x);
      }).catch(e => { if (!ctl.signal.aborted) { setView(null); setError(String(e.message)); } });
    return () => ctl.abort();
  }, [reload]);
  const account = view?.account;
  return <section dir="rtl" className="space-y-5">
    <header className="flex flex-wrap items-center justify-between gap-3">
      <div><h2 className="text-xl font-black">سبد کاغذی آزمایشی</h2><p className="mt-1 text-sm text-slate-500">با دادهٔ موجود · ثبت خرید، فروش و ارزش روز · بدون سفارش واقعی</p></div>
      <button type="button" onClick={() => setReload(x => x + 1)} className="rounded-lg border px-4 py-2 text-sm">بازخوانی گزارش</button>
    </header>
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 text-sm text-amber-950 dark:bg-amber-950 dark:text-amber-100">
      کیفیت کامل دادهٔ مالی تأیید نشده است. این حساب برای آزمایش است و عملکرد رسمی P1/P3 محسوب نمی‌شود.
    </div>
    {error && <p role="alert" className="text-red-600">{error}</p>}
    {account && view && <>
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {[["نقد", account.cash_toman], ["ارزش دارایی", account.accounting.holdings_value_toman], ["کل سبد", account.accounting.total_value_toman], ["سود / زیان", account.accounting.profit_loss_toman]].map(([label, value]) =>
          <div key={String(label)} className="rounded-xl border p-4"><p className="text-sm text-slate-500">{label}</p><p className="mt-2 text-xl font-bold" dir="auto">{number(Number(value))} <span className="text-xs">تومان</span></p></div>)}
      </div>
      <div className="rounded-xl border p-4 space-y-2">
        <h3 className="font-bold">{account.paper_order.side === "SELL" ? "فروش" : "خرید"} {account.paper_order.symbol}</h3>
        <p>{labels[account.paper_order.status] ?? account.paper_order.status}</p>
        {!account.paper_order.fill_event_id && <p className="text-sm">{account.paper_order.waiting_reason}</p>}
        <p className="text-sm text-slate-500">تصمیم: {time(account.paper_order.created_at_utc)} · دادهٔ رتبه‌بندی: {account.ranking.evaluation_date}</p>
        <p className="text-sm">آخرین بررسی: {time(view.updated_at_utc)} · {labels[view.outcome.status] ?? view.outcome.status}</p>
        {view.outcome.reason && view.outcome.status === "BLOCKED_EXECUTION" && <details className="text-sm text-amber-700"><summary>علت توقف بررسی</summary><p className="break-words" dir="auto">{view.outcome.reason}</p></details>}
      </div>
      <div className="overflow-x-auto rounded-xl border p-4"><h3 className="mb-3 font-bold">دارایی‌ها</h3>
        {account.holdings.length === 0 ? <p className="text-sm">سهمی در حساب نیست. تا ثبت خرید فرضی، وجه نقد حفظ می‌شود.</p> :
          <table className="w-full text-right text-sm"><thead><tr>{["نماد", "تعداد", "آخرین قیمت (ریال)", "تاریخ قیمت", "ارزش (تومان)", "سود/زیان باز"].map(h => <th key={h} className="p-2">{h}</th>)}</tr></thead>
            <tbody>{account.holdings.map(h => <tr key={h.company_id}><td className="p-2">{h.symbol}</td><td>{number(h.shares)}</td><td>{number(h.last_price_rial)}</td><td>{h.last_price_date}</td><td>{number(h.market_value_toman)}</td><td>{number(h.unrealized_pnl_toman)}</td></tr>)}</tbody></table>}
        <p className="mt-3 text-sm">سود/زیان تحقق‌یافته: {number(account.realized_pnl_toman ?? 0)} تومان</p>
      </div>
      <details className="rounded-xl border p-4" open><summary className="cursor-pointer font-bold">دفتر خرید و فروش</summary>
        <ol className="mt-3 space-y-3">{[...account.event_log].reverse().map(e => <li key={e.event_id} className="border-t pt-3"><p className="font-semibold">{eventNames[e.type] ?? e.type} · {time(e.at_utc)}</p><p className="text-sm">{e.reason}</p><details className="mt-1 text-xs text-slate-500"><summary>جزئیات ثبت</summary><p className="break-words" dir="auto">{e.details}</p></details></li>)}</ol>
      </details>
      <details className="rounded-xl border p-4"><summary className="cursor-pointer font-bold">فرض‌ها و محدودیت‌ها</summary><ul className="mt-3 list-inside list-disc space-y-2 text-sm">{view.limitations.map(l => <li key={l}>{l}</li>)}</ul></details>
    </>}
    <div className="rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-900"><p>برای دریافت قیمت و بررسی سفارش، فایل <b>Update-Paper-Portfolio.cmd</b> در پوشهٔ پروژه را اجرا کن. «بازخوانی گزارش» فقط نمایش را تازه می‌کند. زمان‌بندی خودکار فعال نشده است.</p></div>
    <details className="rounded-xl border p-4"><summary className="cursor-pointer font-bold">حساب قبلی و گزارش‌های پژوهشی</summary><div className="mt-4"><PaperPortfolioTab /></div></details>
  </section>;
}
