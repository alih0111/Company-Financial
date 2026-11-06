import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { API_BASE } from "../config";
import { getAuthStatus } from "../hooks/useGetUser";

type Annual = { year: number; final_toman: number; return_fraction: number };
type Account = {
  metrics: { final_toman: number; total_return: number; max_drawdown: number };
  annual: Annual[]; fees_toman: number; slippage_toman: number; fills: number;
  reviews: number; decisions: number;
};
type Backtest = {
  strategy_id: string; actual_start: string; end: string; initial_toman: number;
  accounts: Record<string, Account>;
  path: { date: string; reportflow: number; original: number; same_information_quarterly: number }[];
};
type Paper = {
  state?: string; message?: string; checked_at_utc?: string; market_date?: string;
  final_toman?: number; cash_toman?: number; last_review_date?: string;
  holdings?: Record<string, number>; trades?: { session: string; symbol: string; side: string; gross_toman: number }[];
};
type Live = { automatic_enabled: boolean; running: boolean; status?: Paper; portfolio?: Paper; account?: { started_at_utc: string }; "worker-error"?: { message: string } };
const base = `${import.meta.env.BASE_URL}strategies/reportflow-033/`;
const n = (v: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v);
const pct = (v: number) => `${n(v * 100, 1)}٪`;
const day = (value: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value));
const panel = "rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60";
const button = "inline-flex min-h-10 items-center justify-center rounded-xl border border-slate-200 px-4 py-2 text-sm disabled:opacity-50 dark:border-slate-700";
const headers = () => ({ Authorization: `Bearer ${localStorage.getItem("token")}` });

export default function ReportFlowPage() {
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState("");
  const [live, setLive] = useState<Live | null>(null);
  const [liveError, setLiveError] = useState("");
  const [requested, setRequested] = useState(false);
  const { isAdmin } = getAuthStatus();
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setError("");
      const response = await fetch(base + "backtest.json", { cache: "no-store", signal });
      if (!response.ok) throw new Error("گزارش بک‌تست مستقل هنوز در دسترس نیست.");
      const body = await response.json() as Backtest;
      if (body.strategy_id !== "RFA-ReportFlow-033-v1.0.0" || !body.accounts?.reportflow || !body.path?.length) throw new Error("گزارش ReportFlow معتبر نیست.");
      setData(body);
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "خواندن گزارش ناموفق بود."); }
  }, []);
  const loadLive = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch(`${API_BASE}/reportflow`, { headers: headers(), cache: "no-store", signal });
      if (!response.ok) throw new Error("وضعیت حساب خودکار در دسترس نیست؛ نسخهٔ جدید سرور باید اجرا شده باشد.");
      setLive(await response.json()); setLiveError("");
    } catch (e) { if (!signal?.aborted) setLiveError(e instanceof Error ? e.message : "خواندن حساب ناموفق بود."); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal); void loadLive(controller.signal);
    const timer = window.setInterval(() => { void loadLive(controller.signal); }, 20000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, [load, loadLive]);
  async function requestReview() {
    setRequested(true); setLiveError("");
    try {
      const response = await fetch(`${API_BASE}/admin/reportflow/review`, { method: "POST", headers: headers() });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error || "ثبت درخواست ناموفق بود.");
      await loadLive();
    } catch (e) { setLiveError(e instanceof Error ? e.message : "ثبت درخواست ناموفق بود."); }
    finally { setRequested(false); }
  }
  const a = data?.accounts.reportflow;
  const old = data?.accounts.original_factormix;
  const portfolio = live?.portfolio;
  return <main dir="rtl" className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
    <section className={panel}>
      <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">ReportFlow-033 · نسخهٔ مستقل ۱٫۰٫۰</p>
      <h1 className="mt-3 text-2xl font-bold">سبد با رسیدن گزارش‌ها بررسی می‌شود</h1>
      <p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">هر گزارش مالی، فروش ماهانه یا اصلاحیهٔ معتبر، بررسی کل سبد را فعال می‌کند. گزارش‌های یک روز تجمیع می‌شوند و در صورت نیاز، تغییر سبد از جلسهٔ بعد پیگیری می‌شود.</p>
      <p className="mt-2 text-xs leading-7 text-slate-500">FactorMix اصلی حفظ شده است. این صفحه بک‌تست و حساب کاغذی جداگانه دارد.</p>
      <Link to="/strategy" className={`${button} mt-4`}>مشاهدهٔ FactorMix اصلی</Link>
    </section>
    {error && <div role="alert" className={panel}><p>{error}</p><button className={`${button} mt-3`} onClick={() => { void load(); }}>تلاش دوباره</button></div>}
    {!data && !error && <p role="status">در حال خواندن نتیجهٔ بک‌تست…</p>}
    {data && a && old && <>
      <section className={panel}>
        <h2 className="text-lg font-bold">مسیر ۱۰۰ میلیون تومان از ۱۴۰۱</h2>
        <p className="mt-2 text-xs leading-7 text-slate-500">از {day(data.actual_start)} تا {day(data.end)} · ارزش اسمی سبد پس از هزینه‌ها · بک‌تست بازسازی‌شده</p>
        <div className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[["ارزش پایان ReportFlow · تومان", n(a.metrics.final_toman)], ["ارزش پایان FactorMix اصلی · تومان", n(old.metrics.final_toman)], ["بیشترین افت ReportFlow", pct(a.metrics.max_drawdown)], ["تعداد اجراهای خرید و فروش", n(a.fills)]].map(([label, value]) => <div key={label} className="rounded-xl bg-slate-50 p-4 dark:bg-slate-900/60"><p className="text-xs leading-6 text-slate-500">{label}</p><p className="mt-2 text-xl font-bold tabular-nums">{value}</p></div>)}
        </div>
        <div className="mt-6 h-80" dir="ltr" aria-label="نمودار ارزش سبد ReportFlow، FactorMix اصلی و کنترل فصلی">
          <ResponsiveContainer width="100%" height="100%"><LineChart data={data.path} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={.15} /><XAxis dataKey="date" minTickGap={70} tickFormatter={value => day(String(value))} tick={{ fontSize: 10 }} /><YAxis width={60} tickFormatter={v => n(Number(v) / 1e6)} tick={{ fontSize: 11 }} label={{ value: "میلیون تومان", angle: -90, position: "insideLeft", fontSize: 10 }} />
            <Tooltip labelFormatter={v => day(String(v))} formatter={(v: number, name: string) => [n(v) + " تومان", name]} /><Legend wrapperStyle={{ fontSize: 11 }} />
            <Line dataKey="reportflow" name="ReportFlow جدید" stroke="#059669" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="original" name="FactorMix اصلی" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="same_information_quarterly" name="کنترل فصلی با اطلاعات یکسان" stroke="#a855f7" dot={false} strokeDasharray="5 4" isAnimationActive={false} />
          </LineChart></ResponsiveContainer>
        </div>
        <p className="mt-4 text-xs leading-7 text-slate-500">{n(a.reviews)} بررسی گزارش و {n(a.decisions)} تصمیم دارای سفارش. کارمزد {n(a.fees_toman)} و لغزش قیمت {n(a.slippage_toman)} تومان، هر دو در ارزش نهایی کسر شده‌اند.</p>
        {a.metrics.final_toman < old.metrics.final_toman && <p className="mt-4 rounded-xl bg-amber-50 p-4 text-sm leading-8 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">در این بک‌تست، بررسی پس از هر گزارش از FactorMix فصلی بازده کمتری داشته است. مدل جدید برای مقایسهٔ مستقل حفظ شده و جایگزین مدل اصلی نشده است.</p>}
      </section>
      <section className={panel}><h2 className="text-lg font-bold">مقایسهٔ نتیجه و حساسیت اجرا</h2>
        <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[580px] text-right text-sm"><thead><tr className="border-b"><th className="p-3">سناریو</th><th className="p-3">ارزش پایان · تومان</th><th className="p-3">بیشترین افت</th><th className="p-3">اجراها</th></tr></thead><tbody>
          {Object.entries({ reportflow: "ReportFlow جدید", original_factormix: "FactorMix اصلی", same_information_quarterly: "فصلی با اطلاعات یکسان", double_cost: "دو برابر هزینه", delay_2_sessions: "دو جلسه تأخیر" }).map(([key, label]) => <tr className="border-b border-slate-100 dark:border-slate-700" key={key}><th className="p-3">{label}</th><td className="p-3">{n(data.accounts[key].metrics.final_toman)}</td><td className="p-3">{pct(data.accounts[key].metrics.max_drawdown)}</td><td className="p-3">{n(data.accounts[key].fills)}</td></tr>)}
        </tbody></table></div>
        <p className="mt-3 text-xs leading-7 text-slate-500">کنترل فصلی از همان اطلاعات بازسازی‌شدهٔ مدل جدید استفاده می‌کند تا اثر زمان‌بندی بهتر مشخص شود. مدل اصلی داده‌های ثبت‌شدهٔ خودش را حفظ کرده است.</p>
      </section>
      <section className={panel}><h2 className="text-lg font-bold">پایان هر سال شمسی</h2><div className="mt-4 overflow-x-auto"><table className="w-full text-right text-sm"><thead><tr className="border-b"><th className="p-3">سال</th><th className="p-3">ReportFlow · تومان</th><th className="p-3">FactorMix · تومان</th><th className="p-3">بازده ReportFlow</th></tr></thead><tbody>{a.annual.map((row, i) => <tr className="border-b border-slate-100 dark:border-slate-700" key={row.year}><th className="p-3">{n(row.year)}{i === a.annual.length - 1 ? " · تا پایان داده" : ""}</th><td className="p-3">{n(row.final_toman)}</td><td className="p-3">{n(old.annual[i].final_toman)}</td><td className="p-3">{pct(row.return_fraction)}</td></tr>)}</tbody></table></div></section>
      <section className={panel}><h2 className="text-lg font-bold">دریافت گزارش و دفتر معاملات</h2><div className="mt-4 flex flex-wrap gap-3">{[["report.fa.md", "گزارش کامل"], ["reportflow_nav.csv", "مسیر روزانهٔ سرمایه"], ["reportflow_trades.csv", "همهٔ خرید و فروش‌ها"], ["reportflow_decisions.csv", "تصمیم‌های سبد"]].map(([file, label]) => <a className={button} key={file} href={base + file} download>{label}</a>)}</div></section>
    </>}
    <section className={panel}>
      <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="text-lg font-bold">حساب کاغذی مستقل از امروز</h2>{isAdmin && <button className={button} disabled={requested || live?.running} onClick={() => { void requestReview(); }}>{requested || live?.running ? "در حال بررسی…" : "درخواست بررسی"}</button>}</div>
      <p className="mt-3 text-sm leading-8">{live?.status?.message || (live?.account ? "حساب مستقل ثبت شده است." : "در انتظار اتصال حساب مستقل به سرور.")}</p>
      {live?.account && <p className="mt-2 text-xs leading-7 text-slate-500">شروع حساب: {day(live.account.started_at_utc)} · بررسی خودکار {live.automatic_enabled ? "فعال" : "غیرفعال"} · سرمایهٔ اولیه ۱۰۰ میلیون تومان</p>}
      {liveError && <p role="alert" className="mt-3 text-sm text-amber-700 dark:text-amber-300">{liveError}</p>}
      {live?.["worker-error"] && <p role="alert" className="mt-3 text-sm text-rose-600">{live["worker-error"].message}</p>}
      {portfolio?.final_toman != null && <><p className="mt-3 text-sm">ارزش حساب: {n(portfolio.final_toman)} تومان · نقد: {n(portfolio.cash_toman ?? 0)} تومان</p><div className="mt-4 flex flex-wrap gap-2">{Object.entries(portfolio.holdings ?? {}).map(([symbol, value]) => <span key={symbol} className="rounded-xl bg-slate-50 p-3 text-sm dark:bg-slate-900">{symbol} · {n(value)} تومان</span>)}</div></>}
      <p className="mt-3 text-xs leading-7 text-slate-500">بررسی پس از جمع‌آوری گزارش‌ها و از ساعت ۱۸ تهران انجام می‌شود؛ هر روز یک نوبت. گزارش‌های بعد از آن نوبت در بررسی روز بعد لحاظ می‌شوند. اجرای فرضی سفارش فقط در جلسهٔ واقعی سهام، با دادهٔ معتبر و پس از تصمیم است. این حساب به کارگزاری متصل نیست.</p>
    </section>
    <section className={panel}><h2 className="text-lg font-bold">قواعد و حدود نتیجه</h2><p className="mt-3 text-sm leading-8">پنج سهم با وزن هدف ۲۰٪؛ نگهداری تا رتبهٔ ۸؛ بازتنظیم وزن با انحراف بیش از ۵ واحد درصد. انتظار گزارش ماهانه از ۱۰ام ماه بعد و گزارش فصلی حدود ۴۰ روز بعد از فصل، جایگزین دریافت واقعی گزارش نمی‌شود. هر طرف معامله با فرض کارمزد ۰٫۵٪، لغزش ۰٫۱٪، سقف ۵٪ ارزش معاملات و انقضای پنج جلسه مدل شده است.</p><p className="mt-3 text-xs leading-8 text-slate-500">زمان دریافت واقعی گزارش‌ها در تاریخچه اثبات نشده؛ بک‌تست بر مبنای انتشار بازسازی شده است. وزن‌های مدل با استفاده از بخشی از همین تاریخ انتخاب شده‌اند. جهان ثابت ۲۵۴ نماد، واحدهای تعدیل‌شده، فرض سرمایه‌گذاری مجدد سود و محدودیت صف معاملات بر نتیجه اثر دارند. ارزش پایان، ارزش دفتری سبد است و به معنی نقد قابل برداشت نیست.</p></section>
  </main>;
}
