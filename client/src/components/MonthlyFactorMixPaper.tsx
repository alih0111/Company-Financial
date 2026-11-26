import { useEffect, useState } from "react";
import { API_BASE } from "../config";
import { sessionHeaders } from "../hooks/useGetUser";
import { apiFetch } from "../utils/request";

type Review = { session: string; kind?: "initial_entry" | "monthly"; state: "decided" | "missed" | "blocked"; target_weights?: Record<string, number>; report_coverage?: { complete: boolean } };
type Account = {
  session: string | null;
  cash_toman: number;
  nav_toman: number;
  holdings: { symbol: string; value_toman: number }[];
  open_batch: { pending: string[] } | null;
  reviews: Review[];
  trades: { session: string; decision: string; symbol: string; side: "BUY" | "SELL"; gross_toman: number; fee_toman: number }[];
};
type Paper = { account: Account | null; starting: boolean; status: { state: string; started_at_utc: string; report_coverage?: { complete: boolean } } | null };

const money = new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 0 });
const percent = new Intl.NumberFormat("fa-IR", { style: "percent", maximumFractionDigits: 1 });
const calendar = new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" });
const day = (value: string) => calendar.format(new Date(`${value}T12:00:00Z`));
const statusText: Record<string, string> = {
  ready: "دفتر تا آخرین جلسهٔ دریافت‌شده به‌روز است.",
  running: "دریافت داده و بررسی سبد در جریان است.",
  before_cutoff: "بررسی امروز از ساعت ۱۷ به وقت تهران انجام می‌شود.",
  weekly_closed: "تعطیلی هفتگی بازار.",
  no_session_data: "دادهٔ جلسهٔ امروز هنوز تأیید نشده است.",
  decision_blocked: "مدرک کیفیت داده یا اعتبار رتبه‌بندی برای تصمیم این جلسه کافی نبود.",
  failed: "آخرین بررسی کامل نشد. دفتر تا آخرین جلسهٔ ثبت‌شده نمایش داده می‌شود.",
};

export default function MonthlyFactorMixPaper() {
  const [paper, setPaper] = useState<Paper | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await apiFetch(`${API_BASE}/admin/factormix/paper`, {
          headers: sessionHeaders(), cache: "no-store", signal: controller.signal,
        });
        if (!response.ok) throw new Error("خواندن دفتر کاغذی ناموفق بود.");
        const result = await response.json();
        if (!controller.signal.aborted) {
          setPaper(result);
          setError("");
        }
      } catch {
        if (!controller.signal.aborted) setError("خواندن دفتر کاغذی ناموفق بود.");
      }
    }
    void load();
    const timer = window.setInterval(load, 15000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);

  const account = paper?.account;
  const state = paper?.starting ? "running" : paper?.status?.state;
  const staleRun = state === "running" && !paper?.starting && paper?.status &&
    Date.now() - Date.parse(paper.status.started_at_utc) > 4 * 60 * 60 * 1000;
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(account, null, 2)], { type: "application/json" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "factormix-m15-paper.json";
    link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  return <section className="rounded-2xl border border-violet-200 bg-white p-4 sm:p-6 dark:border-violet-800 dark:bg-slate-800/60" aria-labelledby="monthly-paper-title">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 id="monthly-paper-title" className="text-xl font-black">سبد کاغذی ماهانه ۱۵</h2>
      {account && <button type="button" onClick={download} className="rounded-lg border px-3 py-2 text-sm dark:border-slate-600">دانلود دفتر کامل</button>}
    </div>
    <p role="status" className="mt-2 text-sm leading-7">{error || (staleRun ? "اجرای اخیر بدون گزارش پایان مانده است." : state ? statusText[state] : paper ? "دفتر در انتظار اولین اجراست." : "در حال خواندن دفتر…")}</p>
    {paper?.status?.report_coverage?.complete === false && <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">پوشش دریافت گزارش‌های کدال در آخرین اجرا ناقص بود.</p>}
    <p className="mt-1 text-xs leading-7 text-slate-500 dark:text-slate-400">دکمهٔ دریافت قیمت روزانه بررسی این سبد را هم درخواست می‌کند. تصمیم پس از بازار در موعد ماهانه ثبت می‌شود و سفارش‌های فرضی از جلسهٔ بعد بررسی می‌شوند.</p>
    {account && <div className="mt-4 space-y-3 text-sm leading-7">
      <p>ارزش سبد <b>{money.format(account.nav_toman)} تومان</b> · نقد <b>{money.format(account.cash_toman)} تومان</b>{account.session && <> · جلسهٔ {day(account.session)}</>}</p>
      <p>دارایی‌ها · {account.holdings.map(row => `${row.symbol} (${money.format(row.value_toman)} تومان)`).join("، ") || "فعلاً نقد"}</p>
      <p>سفارش‌های در انتظار · {account.open_batch?.pending.join("، ") || "فعلاً سفارشی در انتظار نیست"}</p>
      <details open>
        <summary className="cursor-pointer font-bold">تصمیم‌های سبد · {money.format(account.reviews.length)}</summary>
        {!account.reviews.length && <p>هنوز تصمیمی ثبت نشده است.</p>}
        <ul className="list-inside list-disc">{[...account.reviews].reverse().map(review =>
          <li key={review.session}>{day(review.session)} · {review.kind === "initial_entry" && "ورود اولیه · "}{review.state === "missed" ? "موعد گذشته؛ تصمیم هم‌روز ثبت نشد." : review.state === "blocked" ? "تصمیم به‌علت اعتبارسنجی داده یا رتبه‌بندی متوقف شد." :
            Object.entries(review.target_weights ?? {}).map(([symbol, weight]) => `${symbol} ${percent.format(weight)}`).join("، ") || "سبد هدف نقد"}
            {review.report_coverage?.complete === false && " · پوشش ناقص کدال"}</li>)}</ul>
      </details>
      <details>
        <summary className="cursor-pointer font-bold">اجراهای فرضی · {money.format(account.trades.length)}</summary>
        <ul className="list-inside list-disc">{account.trades.slice(-10).reverse().map((trade, index) =>
          <li key={index}>{day(trade.session)} · {trade.side === "BUY" ? "خرید" : "فروش"} {trade.symbol} · {money.format(trade.gross_toman)} تومان · کارمزد {money.format(trade.fee_toman)} تومان</li>)}</ul>
      </details>
    </div>}
  </section>;
}
