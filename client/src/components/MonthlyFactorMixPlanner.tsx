import { useState } from "react";
import { Link } from "react-router-dom";
import { monthlyBasketPlan, parseToman, type MonthlyRanking, type MonthlyPlan } from "./monthlyBasketPlan.js";

const n = (value:number) => new Intl.NumberFormat("fa-IR",{maximumFractionDigits:0}).format(value);
const pct = (value:number) => new Intl.NumberFormat("fa-IR",{style:"percent",maximumFractionDigits:1}).format(value);
const button = "min-h-10 rounded-xl border border-slate-300 px-3 py-2 text-sm disabled:opacity-50 dark:border-slate-600";
const field = "min-h-10 min-w-0 rounded-xl border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600";

export default function MonthlyFactorMixPlanner({ranking,busy}:{ranking:MonthlyRanking|null;busy:boolean}) {
  const [cash,setCash] = useState("");
  const [holdings,setHoldings] = useState<{symbol:string;value:string}[]>([]);
  const [result,setResult] = useState<MonthlyPlan|null>(null);
  const [error,setError] = useState("");
  const today = new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Tehran",year:"numeric",month:"2-digit",day:"2-digit"}).format(new Date());
  const current = result && ranking && result.ranking_computed_at_utc === ranking.computed_at_utc && !busy;
  const fresh = ranking?.date === today;
  const snapshotNote = !fresh ? "امتیازها مربوط به امروز نیستند؛ برای تصمیم جدید ابتدا «به‌روزرسانی امتیازها» را بزنید." : "تاریخ قیمت را هم بررسی کنید؛ محاسبهٔ امروز با قیمت قدیمی، به معنی آماده بودن دادهٔ جلسهٔ پانزدهم نیست.";
  function review() {
    setError(""); setResult(null);
    try {
      if (!ranking) throw new Error("ابتدا امتیازهای FactorMix را به‌روز کنید.");
      setResult(monthlyBasketPlan(ranking,holdings.map(h=>({symbol:h.symbol,value_toman:parseToman(h.value)})),parseToman(cash)));
    } catch (e) { setError(e instanceof Error ? e.message : "بررسی ناموفق بود."); }
  }
  function download() {
    if (!result || !current) return;
    const url = URL.createObjectURL(new Blob([JSON.stringify({...result,created_at_utc:new Date().toISOString()},null,2)],{type:"application/json"}));
    const a = document.createElement("a"); a.href=url; a.download=`factormix-m15-plan-${result.ranking_date}.json`; a.click();
    window.setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  return <section className="mt-6 rounded-2xl border border-violet-200 p-4 sm:p-5 dark:border-violet-900" aria-labelledby="monthly-planner-title">
    <h2 id="monthly-planner-title" className="text-lg font-bold">بررسی سبد ماهانه · پانزدهم هر ماه</h2>
    <p className="mt-2 text-sm leading-8 text-slate-600 dark:text-slate-300">گزارش‌های جدید را در طول ماه جمع کنید. روز ۱۵، یا اولین جلسهٔ سهام بعد از آن، پس از پایان بازار گزارش‌ها و قیمت‌ها را به‌روز و سپس امتیازها را محاسبه کنید. تغییرهای لازم از جلسهٔ بعد بررسی و اجرا می‌شوند.</p>
    <p className="mt-2 text-xs leading-7 text-slate-500">ارزش روز همهٔ دارایی‌های همین سبد و نقد را وارد کنید. برای شروع با پول نقد، دارایی اضافه نکنید. این فرم پیشنهاد می‌سازد؛ سفارش کارگزاری و ثبت معامله انجام نمی‌دهد. ورودی‌ها با خروج از صفحه پاک می‌شوند.</p>
    <p role="status" className="mt-2 text-xs leading-7 text-amber-700 dark:text-amber-300">{snapshotNote} بررسی خارج از موعد، پیش‌نمایش است.</p>
    <label className="mt-4 grid max-w-xs gap-2 text-xs">نقد فعلی سبد · تومان<input className={field} inputMode="numeric" value={cash} placeholder="مثلاً ۱۰۰٬۰۰۰٬۰۰۰" onChange={e=>{setCash(e.target.value);setResult(null);}} /></label>
    <datalist id="monthly-model-symbols">{ranking?.rows.map(r=><option value={r.symbol} key={r.symbol}/>)}</datalist>
    <div className="mt-3 space-y-3">{holdings.map((h,i)=><div className="flex flex-wrap items-end gap-2" key={i}>
      <label className="grid min-w-0 flex-1 gap-2 text-xs">نماد دارایی {n(i+1)}<input className={field} list="monthly-model-symbols" value={h.symbol} onChange={e=>{setHoldings(holdings.map((row,k)=>k===i?{...row,symbol:e.target.value}:row));setResult(null);}} /></label>
      <label className="grid min-w-0 flex-1 gap-2 text-xs">ارزش روز دارایی {n(i+1)} · تومان<input className={field} inputMode="numeric" value={h.value} onChange={e=>{setHoldings(holdings.map((row,k)=>k===i?{...row,value:e.target.value}:row));setResult(null);}} /></label>
      <button className={button} aria-label={`حذف دارایی ${n(i+1)}`} onClick={()=>{setHoldings(holdings.filter((_,k)=>k!==i));setResult(null);}}>حذف</button>
    </div>)}</div>
    <div className="mt-4 flex flex-wrap gap-2"><button className={button} onClick={()=>{setHoldings([...holdings,{symbol:"",value:""}]);setResult(null);}}>افزودن دارایی</button><button className={`${button} bg-violet-700 text-white`} disabled={!ranking || busy} onClick={review}>بررسی سبد ماهانه</button><Link className={button} to="/strategy/performance">نمودار عملکرد و نسخهٔ ثبت‌شده</Link></div>
    {error && <p className="mt-3 text-sm text-rose-600" role="alert">{error}</p>}
    {result && !current && <p className="mt-3 text-sm text-amber-700" role="status">امتیازها تغییر کرده‌اند؛ برای پیشنهاد تازه دوباره بررسی کنید.</p>}
    {result && current && <div className="mt-5 space-y-3" aria-label="پیشنهاد سبد ماهانه">
      <p className="text-sm leading-8">ارزش ورودی سبد: <b>{n(result.nav_toman)} تومان</b> · {result.changes ? `${n(result.changes)} پیشنهاد تغییر` : "تغییری لازم نیست"}</p>
      <div className="overflow-x-auto"><table className="w-full min-w-[700px] text-right text-xs"><thead><tr>{["نماد / رتبه","عملیات پیشنهادی","وزن فعلی","وزن هدف","تغییر مبلغ پیش از هزینه · تومان","علت"].map(h=><th className="p-3" scope="col" key={h}>{h}</th>)}</tr></thead><tbody>{result.rows.map(r=><tr className="border-t border-slate-200 dark:border-slate-700" key={r.symbol}><th className="p-3" scope="row">{r.symbol} · {r.rank===null?"فاقد شرایط":n(r.rank)}</th><td className="p-3">{r.action==="BUY"?"خرید":r.action==="SELL"?"فروش":"نگهداری"}</td><td className="p-3">{pct(r.current_weight)}</td><td className="p-3">{pct(r.target_weight)}</td><td className="p-3" dir="ltr">{n(r.delta_toman)}</td><td className="p-3 leading-7">{r.reason}</td></tr>)}</tbody></table></div>
      <p className="text-xs leading-7 text-slate-500">مبالغ اختلاف هدف پیش از کارمزد و لغزش‌اند؛ اجرای سفارش در قیمت جلسهٔ بعد می‌تواند متفاوت باشد. فروش اجرا نشده را نقد خرید حساب نکنید. سهم‌های موجودِ واجد شرایط تا رتبهٔ ۸ اولویت نگهداری دارند؛ هر بار پنج رتبهٔ اول جایگزین نمی‌شوند.{result.missing_slots>0 ? ` برای ${n(result.missing_slots)} جای خالی، وجه نقد نگه داشته می‌شود.` : ""}</p>
      <button className={button} onClick={download}>دریافت پیشنهاد JSON</button>
    </div>}
  </section>;
}
