import { getAuthStatus } from "../hooks/useGetUser";
import { Link } from "react-router-dom";
import CurrentFactorMixRanking from "./CurrentFactorMixRanking";
import MonthlyStrategyPortfolio from "./MonthlyStrategyPortfolio";

const panel = "rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60";
const button = "inline-flex min-h-10 items-center justify-center rounded-xl border border-slate-200 px-4 py-2 text-sm dark:border-slate-700";

export default function MonthlyFactorMixPage() {
  return <main dir="rtl" className="mx-auto max-w-[1500px] space-y-5 text-slate-800 dark:text-slate-100">
    <header className={panel}>
      <p className="text-xs font-semibold text-violet-700 dark:text-violet-300">مدل نهایی منتخب · نسخهٔ ۱٫۰٫۰</p>
      <h1 className="mt-3 text-2xl font-black sm:text-3xl">FactorMix · ماهانه ۱۵</h1>
      <p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">گزارش‌های مالی، فروش ماهانه و اصلاحیه‌ها در طول ماه جمع می‌شوند. بازبینی سبد پس از پایان بازارِ پانزدهم هر ماه، یا اولین جلسهٔ سهام بعد از آن، انجام می‌شود. تغییرهای لازم از جلسهٔ بعد پیگیری می‌شوند.</p>
      <div className="mt-4 flex flex-wrap gap-2"><Link className={`${button} bg-violet-700 text-white`} to="/strategy/performance">عملکرد مدل نهایی</Link><a className={button} href="#monthly-planner-title">بررسی سبد ماهانه</a>{getAuthStatus().isAdmin && <a className={button} href={`${import.meta.env.BASE_URL}strategies/factormix-033/performance/from-1401-monthly15-guide.fa.md`} download>راهنمای نسخهٔ ثبت‌شده</a>}</div>
    </header>
    <MonthlyStrategyPortfolio />
    <section className={panel} aria-label="قواعد مدل نهایی">
      <h2 className="text-lg font-bold">قواعد همین مدل</h2>
      <p className="mt-2 text-sm leading-8">هدف پنج سهم با وزن ۲۰٪ است. سهم موجودِ واجد شرایط تا رتبهٔ ۸ اولویت نگهداری دارد؛ جای خالی از رتبه‌های بالاتر پر می‌شود. انحراف بیش از ۵ واحد درصد از وزن هدف باعث پیشنهاد تنظیم وزن می‌شود.</p>
      <p className="mt-2 text-xs leading-7 text-slate-500">ابتدا جمع‌آوری گزارش‌ها و قیمت‌ها را تمام کنید، سپس امتیازها را به‌روز کنید و ارزش روز دارایی‌ها و نقد همین سبد را در فرم پایین وارد کنید. فرم پیشنهاد می‌سازد؛ ارسال سفارش کارگزاری یا ثبت معامله انجام نمی‌دهد.</p>
    </section>
    <CurrentFactorMixRanking />
    <footer className="flex flex-wrap gap-4 border-t border-slate-200 pt-4 text-xs leading-7 text-slate-500 dark:border-slate-700"><span>مدل منتخب: FactorMix · ماهانه ۱۵</span><Link className="underline" to="/strategy/history">آرشیو نسخهٔ فصلی قدیمی</Link><Link className="underline" to="/strategy/reportflow">آرشیو آزمایش ReportFlow</Link></footer>
  </main>;
}
