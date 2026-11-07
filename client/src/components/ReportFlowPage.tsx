import { apiFetch } from "../utils/request";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

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
const base = `${import.meta.env.BASE_URL}strategies/reportflow-033/`;
const n = (v: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v);
const pct = (v: number) => `${n(v * 100, 1)}٪`;
const day = (value: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value));
const panel = "rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60";
const button = "inline-flex min-h-10 items-center justify-center rounded-xl border border-slate-200 px-4 py-2 text-sm disabled:opacity-50 dark:border-slate-700";

export default function ReportFlowPage() {
  const [expanded, setExpanded] = useState(false);
  return <main dir="rtl" className="mx-auto max-w-7xl space-y-5 p-4 sm:p-6">
    <section className={panel}>
      <p className="text-xs font-semibold text-slate-500">آرشیو پژوهش · ReportFlow-033</p>
      <h1 className="mt-3 text-2xl font-bold">آزمایش قبلی گزارش‌محور</h1>
      <p className="mt-3 text-sm leading-8">این مدل برای آزمایشِ بازبینی سبد با رسیدن هر گزارش ساخته شد. بازده ضعیف‌تر نمودار مربوط به همان آزمایش است؛ مدل نهایی منتخب <b>FactorMix · ماهانه ۱۵</b> است.</p>
      <p className="mt-2 text-sm leading-8 text-slate-500">این صفحه برای حفظ سوابق نگهداری شده است و درخواست بررسی یا اجرای حساب آزمایشی ندارد.</p>
      <div className="mt-4 flex flex-wrap gap-3"><Link className={`${button} bg-violet-700 text-white`} to="/strategy">مدل نهایی · FactorMix ماهانه ۱۵</Link><Link className={button} to="/strategy/performance">نمودار عملکرد مدل نهایی</Link></div>
    </section>
    <button className={button} aria-expanded={expanded} onClick={() => setExpanded(v => !v)}>{expanded ? "بستن گزارش آزمایش قدیمی" : "مشاهدهٔ گزارش آزمایش قدیمی ReportFlow"}</button>
    {expanded && <ReportFlowResearchReport />}
  </main>;
}

function ReportFlowResearchReport() {
  const [data, setData] = useState<Backtest | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      setError("");
      const response = await apiFetch(base + "backtest.json", { cache: "no-store", signal });
      if (!response.ok) throw new Error("گزارش بک‌تست مستقل هنوز در دسترس نیست.");
      const body = await response.json() as Backtest;
      if (body.strategy_id !== "RFA-ReportFlow-033-v1.0.0" || !body.accounts?.reportflow || !body.path?.length) throw new Error("گزارش ReportFlow معتبر نیست.");
      setData(body);
    } catch (e) { if (!signal?.aborted) setError(e instanceof Error ? e.message : "خواندن گزارش ناموفق بود."); }
  }, []);
  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);
  const a = data?.accounts.reportflow;
  const old = data?.accounts.original_factormix;
  return <div className="space-y-5" aria-label="گزارش تاریخی آزمایش ReportFlow">
    <section className={panel}>
      <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">ReportFlow-033 · نسخهٔ مستقل ۱٫۰٫۰</p>
      <h2 className="mt-3 text-2xl font-bold">بک‌تست آزمایش قدیمی</h2>
      <p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">در این آزمایش، هر گزارش مالی، فروش ماهانه یا اصلاحیهٔ معتبر بررسی کل سبد را فعال می‌کرد. گزارش‌های یک روز تجمیع می‌شدند و تغییر لازم از جلسهٔ بعد پیگیری می‌شد.</p>
      <p className="mt-2 text-xs leading-7 text-slate-500">FactorMix اصلی حفظ شده است. این صفحه بک‌تست و حساب کاغذی جداگانه دارد.</p>
      <Link to="/strategy" className={`${button} mt-4`}>بازگشت به مدل نهایی ماهانه ۱۵</Link>
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
            <Line dataKey="reportflow" name="ReportFlow · آزمایش قدیمی" stroke="#059669" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="original" name="FactorMix اصلی" stroke="#3b82f6" dot={false} strokeWidth={2} isAnimationActive={false} />
            <Line dataKey="same_information_quarterly" name="کنترل فصلی با اطلاعات یکسان" stroke="#a855f7" dot={false} strokeDasharray="5 4" isAnimationActive={false} />
          </LineChart></ResponsiveContainer>
        </div>
        <p className="mt-4 text-xs leading-7 text-slate-500">{n(a.reviews)} بررسی گزارش و {n(a.decisions)} تصمیم دارای سفارش. کارمزد {n(a.fees_toman)} و لغزش قیمت {n(a.slippage_toman)} تومان، هر دو در ارزش نهایی کسر شده‌اند.</p>
        {a.metrics.final_toman < old.metrics.final_toman && <p className="mt-4 rounded-xl bg-amber-50 p-4 text-sm leading-8 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">در این بک‌تست، بررسی پس از هر گزارش از FactorMix فصلی بازده کمتری داشته است. این آزمایش برای حفظ سوابق باقی مانده؛ مدل منتخب نهایی FactorMix ماهانهٔ ۱۵ است.</p>}
      </section>
      <section className={panel}><h2 className="text-lg font-bold">مقایسهٔ نتیجه و حساسیت اجرا</h2>
        <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[580px] text-right text-sm"><thead><tr className="border-b"><th className="p-3">سناریو</th><th className="p-3">ارزش پایان · تومان</th><th className="p-3">بیشترین افت</th><th className="p-3">اجراها</th></tr></thead><tbody>
          {Object.entries({ reportflow: "ReportFlow · آزمایش قدیمی", original_factormix: "FactorMix اصلی", same_information_quarterly: "فصلی با اطلاعات یکسان", double_cost: "دو برابر هزینه", delay_2_sessions: "دو جلسه تأخیر" }).map(([key, label]) => <tr className="border-b border-slate-100 dark:border-slate-700" key={key}><th className="p-3">{label}</th><td className="p-3">{n(data.accounts[key].metrics.final_toman)}</td><td className="p-3">{pct(data.accounts[key].metrics.max_drawdown)}</td><td className="p-3">{n(data.accounts[key].fills)}</td></tr>)}
        </tbody></table></div>
        <p className="mt-3 text-xs leading-7 text-slate-500">کنترل فصلی از همان اطلاعات بازسازی‌شدهٔ این آزمایش استفاده می‌کند تا اثر زمان‌بندی بهتر مشخص شود. مدل اصلی داده‌های ثبت‌شدهٔ خودش را حفظ کرده است.</p>
      </section>
      <section className={panel}><h2 className="text-lg font-bold">پایان هر سال شمسی</h2><div className="mt-4 overflow-x-auto"><table className="w-full text-right text-sm"><thead><tr className="border-b"><th className="p-3">سال</th><th className="p-3">ReportFlow · تومان</th><th className="p-3">FactorMix · تومان</th><th className="p-3">بازده ReportFlow</th></tr></thead><tbody>{a.annual.map((row, i) => <tr className="border-b border-slate-100 dark:border-slate-700" key={row.year}><th className="p-3">{n(row.year)}{i === a.annual.length - 1 ? " · تا پایان داده" : ""}</th><td className="p-3">{n(row.final_toman)}</td><td className="p-3">{n(old.annual[i].final_toman)}</td><td className="p-3">{pct(row.return_fraction)}</td></tr>)}</tbody></table></div></section>
      <section className={panel}><h2 className="text-lg font-bold">دریافت گزارش و دفتر معاملات</h2><div className="mt-4 flex flex-wrap gap-3">{[["report.fa.md", "گزارش کامل"], ["reportflow_nav.csv", "مسیر روزانهٔ سرمایه"], ["reportflow_trades.csv", "همهٔ خرید و فروش‌ها"], ["reportflow_decisions.csv", "تصمیم‌های سبد"]].map(([file, label]) => <a className={button} key={file} href={base + file} download>{label}</a>)}</div></section>
    </>}
    <section className={panel}><h2 className="text-lg font-bold">قواعد و حدود نتیجه</h2><p className="mt-3 text-sm leading-8">پنج سهم با وزن هدف ۲۰٪؛ نگهداری تا رتبهٔ ۸؛ بازتنظیم وزن با انحراف بیش از ۵ واحد درصد. انتظار گزارش ماهانه از ۱۰ام ماه بعد و گزارش فصلی حدود ۴۰ روز بعد از فصل، جایگزین دریافت واقعی گزارش نمی‌شود. هر طرف معامله با فرض کارمزد ۰٫۵٪، لغزش ۰٫۱٪، سقف ۵٪ ارزش معاملات و انقضای پنج جلسه مدل شده است.</p><p className="mt-3 text-xs leading-8 text-slate-500">زمان دریافت واقعی گزارش‌ها در تاریخچه اثبات نشده؛ بک‌تست بر مبنای انتشار بازسازی شده است. وزن‌های مدل با استفاده از بخشی از همین تاریخ انتخاب شده‌اند. جهان ثابت ۲۵۴ نماد، واحدهای تعدیل‌شده، فرض سرمایه‌گذاری مجدد سود و محدودیت صف معاملات بر نتیجه اثر دارند. ارزش پایان، ارزش دفتری سبد است و به معنی نقد قابل برداشت نیست.</p></section>
  </div>;
}
