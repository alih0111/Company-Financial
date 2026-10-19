import { Fragment, useEffect, useMemo, useState } from "react";

type CurrentRow = { security_id:string; company_id:string; symbol:string; rank:number; rank_delta:number; score:number; observed_factors:number; price_date:string|null; stale_price:boolean; latest_financial_period:string; financial_collected_at:string; source_reports:string[]; factors:Array<{factor:string;raw_value:number|null;percentile:number;weight:number;weighted_contribution:number;missing_reason:string|null}> };
type CurrentSnapshot = { schema_version:number; run_id:string; information_cutoff:string; generated_at:string; price_asof:string|null; scored_count:number; identity_count:number; excluded_count:number; universe_hash:string; models:Record<string,{weights:number[];weights_hash:string}>; rows_by_model:Record<string,CurrentRow[]>; limitations:string[] };
const labels:Record<string,string>={current_without_liquidity:"وزن پایه بدون نقدشوندگی",staged_v12_last_block:"وزن دقیق آخرین بلوک staged"};
const number=(value:number)=>value.toLocaleString("fa-IR",{maximumFractionDigits:4});

export default function ResearchV123Current({factorNames}:{factorNames:Record<string,string>}) {
  const [data,setData]=useState<CurrentSnapshot|null>(null);
  const [error,setError]=useState("");
  const [model,setModel]=useState("current_without_liquidity");
  const [query,setQuery]=useState("");
  const [expanded,setExpanded]=useState<string|null>(null);
  const [attempt,setAttempt]=useState(0);
  const [loading,setLoading]=useState(false);
  useEffect(()=>{
    const controller=new AbortController();let active=true;
    setLoading(true);setError("");
    fetch(`${import.meta.env.BASE_URL}research/return-v12-3.json`,{signal:controller.signal,cache:"no-cache"})
      .then(async response=>{
        if(!response.ok||!response.headers.get("content-type")?.includes("application/json")) throw new Error("snapshot محدود هنوز در دسترس نیست.");
        const value=await response.json() as CurrentSnapshot;
        if(value.schema_version!==1||!value.rows_by_model?.current_without_liquidity?.length||!value.rows_by_model?.staged_v12_last_block?.length) throw new Error("ساختار snapshot معتبر نیست.");
        if(active)setData(value);
      }).catch(e=>{if(active&&!controller.signal.aborted)setError(e instanceof Error?e.message:"دریافت داده ناموفق بود.");})
      .finally(()=>{if(active)setLoading(false);});
    return()=>{active=false;controller.abort();};
  },[attempt]);
  const rows=useMemo(()=>(data?.rows_by_model[model]??[]).filter(row=>row.symbol.includes(query.trim())),[data,model,query]);
  const download=()=>{
    if(!data)return;
    const quote=(value:unknown)=>{let text=String(value??"");if(/^[=+@\-]/.test(text))text="'"+text;return `"${text.replace(/"/g,'""')}"`;};
    const lines=[["شناسه ابزار","نماد","مدل","رتبه","امتیاز","تاریخ قیمت","دوره مالی","وضعیت","cutoff"],...rows.map(row=>[row.security_id,row.symbol,model,row.rank,row.score,row.price_date,row.latest_financial_period,"پوشش محدود؛ آخرین گزارش احراز نشده",data.information_cutoff])];
    const url=URL.createObjectURL(new Blob(["\ufeff"+lines.map(line=>line.map(quote).join(",")).join("\r\n")],{type:"text/csv;charset=utf-8"}));
    const link=document.createElement("a");link.href=url;link.download=`${data.run_id}-${model}.csv`;link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  };
  return <section dir="rtl" className="space-y-4 rounded-3xl border border-teal-300 bg-white p-4 sm:p-6 dark:border-teal-800 dark:bg-gray-800">
    <h2 className="text-xl font-bold">رتبه با داده‌های موجود — پوشش محدود V12.3</h2>
    <p className="text-sm leading-7">دادهٔ قیمت تازه‌تر با صورت‌های مالی دارای منشأ ترکیب شده است. آخرین گزارش همهٔ شرکت‌ها و پوشش کل بازار احراز نشده‌اند؛ این جدول، رتبهٔ کامل بازار امروز نیست.</p>
    {error&&<p role="alert" className="text-sm text-red-700 dark:text-red-300">{error} {data&&"آخرین snapshot موفق حفظ شده است."}</p>}
    {loading&&!data&&<p role="status">در حال دریافت رتبه‌ها…</p>}
    {data&&<>
      <p className="text-sm">{number(data.scored_count)} نماد امتیازگرفته از {number(data.identity_count)} هویت بررسی‌شده؛ {number(data.excluded_count)} فاقد ورودی مالی تأییدشده. تاریخ آخرین قیمت در داده: <span dir="ltr">{data.price_asof??"نامعلوم"}</span>. زمان قطع اطلاعات: <span dir="ltr">{data.information_cutoff}</span>.</p>
      <ul className="list-inside list-disc text-sm leading-7 text-amber-800 dark:text-amber-200">{data.limitations.map(text=><li key={text}>{text}</li>)}</ul>
      <div className="flex flex-wrap gap-3">
        <label className="min-w-52 flex-1 text-sm">مدل رتبهٔ محدود<select className="mt-1 w-full rounded-lg border bg-white p-3 dark:bg-gray-900" value={model} onChange={e=>setModel(e.target.value)}>{Object.keys(data.models).map(key=><option key={key} value={key}>{labels[key]??key}</option>)}</select></label>
        <label className="min-w-40 flex-1 text-sm">جست‌وجو در رتبهٔ محدود<input className="mt-1 w-full rounded-lg border bg-white p-3 dark:bg-gray-900" value={query} onChange={e=>setQuery(e.target.value)} /></label>
        <button className="self-end rounded-lg bg-teal-700 p-3 text-sm text-white" onClick={download}>CSV رتبهٔ محدود</button>
      </div>
      <div className="max-h-[600px] overflow-auto"><table className="w-full min-w-[700px] text-right text-sm"><thead><tr>{["رتبه","نماد","امتیاز","اختلاف با پایه","عامل دارای مقدار","تاریخ قیمت","دورهٔ مالی","جزئیات"].map(label=><th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{rows.map(row=><Fragment key={row.security_id}><tr className="border-t dark:border-gray-700"><td className="p-2">{number(row.rank)}</td><th className="p-2">{row.symbol}</th><td className="p-2">{number(row.score)}</td><td className="p-2">{number(row.rank_delta)}</td><td className="p-2">{number(row.observed_factors)} / ۲۱</td><td className="p-2">{row.price_date??"نامعلوم"}{row.stale_price&&" · قدیمی"}</td><td className="p-2">{row.latest_financial_period}</td><td className="p-2"><button className="text-teal-700 underline dark:text-teal-300" aria-expanded={expanded===row.security_id} onClick={()=>setExpanded(expanded===row.security_id?null:row.security_id)}>شرح عوامل</button></td></tr>{expanded===row.security_id&&<tr><td colSpan={8} className="p-3"><p className="mb-2 text-xs">زمان دریافت مالی: {row.financial_collected_at}. شناسهٔ نامه‌های استفاده‌شده: {row.source_reports.join("، ")}. سهم وزنی قبل از جریمهٔ گروه و ضریب کیفیت است.</p><table className="w-full text-xs"><thead><tr>{["عامل","مقدار خام","رتبه درصدی","وزن","سهم وزنی","وضعیت"].map(label=><th key={label} className="p-2">{label}</th>)}</tr></thead><tbody>{row.factors.map(f=><tr key={f.factor}><th className="p-2">{factorNames[f.factor]??f.factor}</th><td className="p-2">{f.raw_value===null?"—":number(f.raw_value)}</td><td className="p-2">{number(100*f.percentile)}٪</td><td className="p-2">{number(f.weight)}</td><td className="p-2">{number(f.weighted_contribution)}</td><td className="p-2">{f.missing_reason?"ورودی ناقص / پیش‌فرض":"دارای مقدار منبع"}</td></tr>)}</tbody></table></td></tr>}</Fragment>)}</tbody></table></div>
      {rows.length===0&&<p role="status">نمادی برای این جست‌وجو پیدا نشد.</p>}
      <details className="text-xs"><summary>وزن‌ها و شناسهٔ مدل</summary><p dir="ltr" className="my-2 break-all">{data.models[model].weights_hash}</p><ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">{data.models[model].weights.map((weight,index)=><li key={index}>{Object.values(factorNames)[index]??index}: {number(weight)}</li>)}</ul></details>
    </>}
    <button className="rounded-lg border p-2 text-sm" disabled={loading} onClick={()=>setAttempt(value=>value+1)}>دریافت دوبارهٔ snapshot</button><p className="text-xs text-gray-500">این دکمه فایل ساخته‌شده را دوباره دریافت می‌کند؛ جمع‌آوری اطلاعات جدید انجام نمی‌دهد. جست‌وجو رتبه‌های محاسبه‌شده را تغییر نمی‌دهد.</p>
  </section>;
}
