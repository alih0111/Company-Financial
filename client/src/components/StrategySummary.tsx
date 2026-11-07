import { useEffect,useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../config";
import { apiFetch } from "../utils/request";
type Summary={cases:{id:string;start_year:number;start:string;as_of:string;initial_toman:number;account:{final_toman:number;total_return:number;max_drawdown:number;cagr:number};annual:{year:number;initial_toman:number;final_toman:number;return_fraction:number}[]}[]};
const n=(value:number)=>new Intl.NumberFormat("fa-IR",{maximumFractionDigits:1}).format(value);
export default function StrategySummary(){
 const [summary,setSummary]=useState<Summary|null>(null);const [error,setError]=useState("");const [selected,setSelected]=useState(0);
 useEffect(()=>{const controller=new AbortController();apiFetch(`${API_BASE}/strategy/summary`,{signal:controller.signal,cache:"no-store"}).then(async response=>{if(!response.ok)throw new Error("خلاصهٔ عملکرد در دسترس نیست.");return response.json();}).then(value=>{if(!controller.signal.aborted)setSummary(value);}).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});return()=>controller.abort();},[]);
 const data=summary?.cases[selected];
 return <section dir="rtl" className="space-y-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60"><h1 className="text-xl font-bold">خلاصهٔ عملکرد FactorMix · ماهانه ۱۵</h1>
  <p className="text-sm leading-8 text-slate-500">این نما نتیجهٔ تجمیعی آزمایش تاریخی است. فایل‌های ورودی، رتبه‌بندی کامل، دفتر معاملات و آرشیو پژوهش در دسترسی عمومی قرار ندارند. نتیجهٔ گذشته تضمین عملکرد آینده نیست.</p>
  {error&&<p role="alert" className="text-rose-600">{error}</p>}
  {!summary&&!error&&<p role="status">در حال دریافت خلاصه…</p>}
  {summary&&<nav className="flex gap-3" aria-label="بازهٔ آزمایش">{summary.cases.map((item,index)=><button key={item.id} aria-pressed={selected===index} className="rounded-lg border px-3 py-2 text-sm" onClick={()=>setSelected(index)}>شروع {n(item.start_year)}</button>)}</nav>}
  {data&&<><p className="text-sm">سرمایهٔ آغازین {n(data.initial_toman)} تومان · از {data.start} تا {data.as_of}</p><div className="grid gap-3 sm:grid-cols-3">{[["ارزش پایان · تومان",n(data.account.final_toman)],["بازده کل",`${n(data.account.total_return*100)}٪`],["بیشترین افت سرمایه",`${n(data.account.max_drawdown*100)}٪`]].map(([label,value])=><div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-900/50" key={label}><p className="text-xs text-slate-500">{label}</p><p className="mt-2 text-xl font-bold">{value}</p></div>)}</div><div className="overflow-x-auto"><table className="w-full text-right text-sm"><thead><tr>{["سال","سرمایهٔ ابتدا · تومان","سرمایهٔ پایان · تومان","بازده"].map(label=><th className="p-3" scope="col" key={label}>{label}</th>)}</tr></thead><tbody>{data.annual.map(year=><tr className="border-t" key={year.year}><th className="p-3" scope="row">{n(year.year)}</th><td>{n(year.initial_toman)}</td><td>{n(year.final_toman)}</td><td>{n(year.return_fraction*100)}٪</td></tr>)}</tbody></table></div></>}
  <Link className="inline-block text-sm underline" to="/strategy">مشاهدهٔ رتبه‌بندی و بررسی سبد ماهانه</Link>
 </section>;
}
