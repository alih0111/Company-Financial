import { useEffect,useState } from "react";
import { API_BASE } from "../config";
import { apiFetch } from "../utils/request";
type Budget={remainingRequests:number;remainingSymbols:number;reset:string;message?:string};
export default function DataUsageNotice(){
 const [budget,setBudget]=useState<Budget|null>(null);const [error,setError]=useState("");
 useEffect(()=>{const controller=new AbortController();
  const update=(event:Event)=>{const next=(event as CustomEvent<Budget>).detail;setBudget(current=>current?.reset===next.reset ? {...next,remainingRequests:Math.min(current.remainingRequests,next.remainingRequests),remainingSymbols:Math.min(current.remainingSymbols,next.remainingSymbols)}:next);};
  window.addEventListener("rfa-data-budget",update);
  apiFetch(`${API_BASE}/data-access`,{signal:controller.signal,cache:"no-store"}).then(async response=>{if(!response.ok)throw new Error("وضعیت سهمیه در دسترس نیست.");return response.json();}).then(data=>{if(!controller.signal.aborted&&!data.unlimited)setBudget({remainingRequests:Math.max(0,data.limits.requests-data.used.requests),remainingSymbols:Math.max(0,data.limits.symbols-data.used.symbols),reset:data.resets_at,message:data.enabled?undefined:"دسترسی دریافت دادهٔ این حساب غیرفعال است."});}).catch(reason=>{if(!controller.signal.aborted)setError(reason.message);});
  return()=>{controller.abort();window.removeEventListener("rfa-data-budget",update);};
 },[]);
 const n=(value:number)=>new Intl.NumberFormat("fa-IR").format(value);
 return <aside className="mb-3 rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-7 text-slate-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-300" aria-label="سهمیهٔ دریافت داده">
  {budget?<><span>باقی‌ماندهٔ امروز: {n(budget.remainingSymbols)} نماد متفاوت و {n(budget.remainingRequests)} درخواست · بازنشانی {new Intl.DateTimeFormat("fa-IR",{dateStyle:"short",timeStyle:"short",timeZone:"Asia/Tehran"}).format(new Date(budget.reset))}</span>{budget.message&&<p role="alert" className="text-amber-700 dark:text-amber-300">{budget.message}</p>}</>:error||"در حال دریافت وضعیت سهمیه…"}
 </aside>;
}
