import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { API_BASE } from "../config";
import { apiFetch } from "../utils/request";
import { errorMessage } from "../utils/errorMessage";

type Row={company_id:string;company_name:string;symbol:string;quant_score:number;data_quality_score:number;latest_price:number|null;pe_approx:number|null;sales_growth_12m:number|null};
const n=(value:number|null|undefined)=>value==null?"—":new Intl.NumberFormat("fa-IR",{maximumFractionDigits:2}).format(value);
const field="min-h-10 rounded-xl border border-slate-300 bg-transparent px-3 py-2 text-sm dark:border-slate-600";
export default function MarketScreenerPage(){
 const [query,setQuery]=useState("");const [search,setSearch]=useState("");const [page,setPage]=useState(1);const [sort,setSort]=useState("quant_score");
 const [rows,setRows]=useState<Row[]>([]);const [total,setTotal]=useState(0);const [busy,setBusy]=useState(false);const [error,setError]=useState("");const [retry,setRetry]=useState(0);
 useEffect(()=>{const controller=new AbortController();setBusy(true);setError("");setRows([]);
  const params=new URLSearchParams({page:String(page),page_size:"20",q:search,sort,order:sort==="company_name"?"asc":"desc"});
  apiFetch(`${API_BASE}/summary?${params}`,{signal:controller.signal,cache:"no-store"}).then(async response=>{
   if(!response.ok){const body=await response.json().catch(()=>null);throw new Error(body?.error||"دریافت جدول ناموفق بود.");}
   const body=await response.json();if(!Array.isArray(body))throw new Error("پاسخ جدول معتبر نیست.");
   if(!controller.signal.aborted){setRows(body);setTotal(Number(response.headers.get("X-Total-Count")||body.length));}
  }).catch(reason=>{if(!controller.signal.aborted)setError(errorMessage(reason,"دریافت جدول ناموفق بود."));}).finally(()=>{if(!controller.signal.aborted)setBusy(false);});
  return()=>controller.abort();
 },[page,search,sort,retry]);
 const pages=Math.max(1,Math.ceil(total/20));
 return <section dir="rtl" className="space-y-5 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60">
  <h1 className="text-xl font-bold">غربال بازار</h1><p className="text-sm leading-7 text-slate-500">هر صفحه حداکثر ۲۰ شرکت دارد. برای جزئیات، شرکت موردنظر را باز کنید. دریافت اطلاعات هر شرکت و صفحه در سهمیهٔ روزانهٔ حساب محاسبه می‌شود.</p>
  <form className="flex flex-wrap gap-3" onSubmit={event=>{event.preventDefault();setPage(1);setSearch(query.trim());}}>
   <label className="grid gap-1 text-xs">نام یا نماد<input className={field} maxLength={80} value={query} onChange={event=>setQuery(event.target.value)}/></label>
   <label className="grid gap-1 text-xs">مرتب‌سازی<select className={field} value={sort} onChange={event=>{setPage(1);setSort(event.target.value);}}><option value="quant_score">امتیاز کل</option><option value="company_name">نام شرکت</option><option value="latest_price">قیمت</option></select></label>
   <button className={`${field} self-end`} disabled={busy}>جست‌وجو</button>
  </form>
  {error&&<div role="alert" className="text-sm leading-7 text-rose-600"><p>{error}</p><button className="mt-2 underline" onClick={()=>setRetry(value=>value+1)}>تلاش دوباره</button></div>}
  {busy?<p role="status">در حال دریافت همین صفحه…</p>:!error&&<><div className="overflow-x-auto"><table className="w-full min-w-[640px] text-right text-sm"><thead><tr>{["شرکت","امتیاز کل","کیفیت داده","قیمت · ریال","P/E","رشد فروش · درصد"].map(label=><th className="p-3" key={label} scope="col">{label}</th>)}</tr></thead><tbody>{rows.map(row=><tr className="border-t border-slate-100 dark:border-slate-700" key={row.company_id}><th scope="row" className="p-3"><Link className="underline" to={`/dashboard?companyname=${encodeURIComponent(row.company_name)}`}>{row.symbol||row.company_name}</Link><p className="mt-1 text-xs font-normal text-slate-500">{row.company_name}</p></th><td>{n(row.quant_score)}</td><td>{n(row.data_quality_score)}</td><td>{n(row.latest_price)}</td><td>{n(row.pe_approx)}</td><td>{n(row.sales_growth_12m)}</td></tr>)}</tbody></table></div>{!rows.length&&<p>شرکتی پیدا نشد.</p>}</>}
  <div className="flex items-center gap-3 text-sm"><button className={field} disabled={busy||page<=1} onClick={()=>setPage(value=>value-1)}>قبلی</button><span>{n(page)} / {n(pages)}</span><button className={field} disabled={busy||page>=pages} onClick={()=>setPage(value=>value+1)}>بعدی</button></div>
 </section>;
}
