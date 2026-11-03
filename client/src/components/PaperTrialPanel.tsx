import { useEffect, useRef, useState } from "react";
import ExperimentalPaperPortfolio from "./ExperimentalPaperPortfolio";
import { getAuthStatus } from "../hooks/useGetUser";
import { getPaperTrialRefreshStatus, startPaperTrialRefresh } from "../utils/api";

type TrialAccount = {outcome:{status:string;reason?:string};review?:{status?:string;reason?:string;candidate?:string;held?:string;sold?:string;new?:string;symbol?:string;sessions_since_fill?:number;cadence_sessions?:number;ranking_evaluation_date?:string};account?:{cash_toman:number;accounting:{total_value_toman:number;profit_loss_toman:number;holdings_value_toman:number};active_decision?:{decision_kind?:string};paper_order?:{side:string;symbol:string;status:string};holdings:Array<{symbol:string;shares:number;last_price_date:string}>;event_log:Array<{event_id:string;type:string;at_utc:string;reason:string}>};};
type Trial = {state:string;updated_at_utc:string;requested_action?:string|null;review_note_fa:string;config:{started_at_utc:string;ends_at_utc:string};accounts:Record<string,TrialAccount>};
type Preview = {reason:string;blocking_reasons?:string[];market_at_utc?:string;last_trade_price_rial?:number;ask?:number;visible_ask_volume?:number};
type Intraday = {status:string;checked_at_utc:string;started_at_utc?:string;finished_at_utc?:string;fill_enabled:boolean;capture_after_market_window?:boolean;capture_grace_used?:boolean;preview_authorization?:boolean;capture_note_fa?:string|null;reason_fa:string;policy?:{poll_interval_minutes:number};schedule?:{next_expected_at_utc:string|null;gap_minutes_beyond_interval:number|null;missed_or_delayed_run_observed:boolean;official_holiday_status?:string;closure_basis?:string};accounts:Record<string,{status:string;reason?:string;reason_for_no_trade?:string;http_status?:number;received_at_utc?:string;last_successful_receive_at_utc?:string;last_valid_preview?:{received_at_utc:string;market_at_utc:string;last_trade_price_rial:number;ask:number;visible_ask_volume:number};preview?:Preview}>};
type AccountAnalysis = {net_return_toman:number|null;net_return_fraction:number|null;cash_toman:number|null;holdings_value_toman:number|null;observed_max_drawdown_fraction:number|null;observed_points:number;observed_run_count?:number;unique_observation_days?:number;scheduled_runs?:number;run_coverage_fraction?:number;outcome_coverage_fraction:number;valid_price_coverage_fraction:number|null;unique_days_without_valid_price?:number;days_without_valid_price?:number;assumed_cost_toman:number;costs_missing_for_transactions:number;transaction_count:number;last_price_dates:string[];last_price_market_date?:string|null;last_price_age_calendar_days?:number|null;last_price_is_stale?:boolean|null;last_price_observed_at_utc:string|null;last_observed_at_utc:string|null};
type Analysis = {schema_version?:number;state:string;period:{started_at_utc:string;ends_at_utc:string;ended:boolean;stop_execution:boolean;execution_stopped_at_utc:string|null;forced_liquidation:boolean};observation_schedule_coverage?:{status:string;fraction:number|null;scheduled_slots:number|null;observed_slots:number|null;missed_slots:number|null;reason?:string};history_integrity?:{status:string;malformed_run_count:number;malformed_runs?:Array<{path:string;error:string}>};accounts:Record<string,AccountAnalysis>;comparison:{benchmark_result:string;common_decision_symbols:string[];common_last_observed_symbols:string[];aligned_observation_count:number;same_symbol_models_are_independent_performance_evidence:boolean|null};limitations:string[]};
const n=(v:number)=>new Intl.NumberFormat("fa-IR").format(v);
const pct=(v:number)=>new Intl.NumberFormat("fa-IR",{style:"percent",maximumFractionDigits:1}).format(v);
const when=(s?:string|null)=>s?new Intl.DateTimeFormat("fa-IR",{dateStyle:"medium",timeStyle:"short",timeZone:"Asia/Tehran"}).format(new Date(s)):"ثبت نشده";
const day=(s?:string|null)=>s?new Intl.DateTimeFormat("fa-IR",{dateStyle:"medium",timeZone:"Asia/Tehran"}).format(new Date(s)):"نامعلوم";
const pnlTone=(v:number)=>v>0?"text-emerald-600 dark:text-emerald-400":v<0?"text-red-600 dark:text-red-400":"";

const dailyCause=(v:TrialAccount)=>{
 const status=v.outcome?.status??"";
 if(status==="FILL_APPLIED")return v.account?.paper_order?.side==="SELL"?"فروش فرضی (بستن سبد) ثبت شد":"خرید فرضی ثبت شد";
 if(status==="MARK_APPLIED")return "ارزش روز به‌روزرسانی شد";
 if(status==="NO_NEW_MARK")return "قیمت تازه‌ای برای ارزش روز نبود";
 if(status==="NO_NEW_SESSION")return "هنوز جلسهٔ تازه‌ای برای سفارش نبود";
 if(status==="ERROR")return "خطا در اجرای روزانه";
 return "وضعیت اجرا: "+(status||"نامعلوم");
};

const orderSide=(v:TrialAccount)=>{
 const order=v.account?.paper_order;const decision=v.account?.active_decision;
 return order?.side ?? (decision?.decision_kind?.includes("_SELL_")?"SELL":decision?.decision_kind?.includes("_BUY_")?"BUY":undefined);
};

const orderLine=(v:TrialAccount)=>{
 const side=orderSide(v);const status=v.account?.paper_order?.status;
 if(side==="SELL"){
  if(status==="PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE")return "فرمان بستن سبد ثبت شده؛ در انتظار نخستین جلسهٔ واجد شرایط";
  if(status==="EXPIRED_NO_FILL")return "سفارش فروش منقضی شد؛ برای تکرار، Close را دوباره اجرا کن";
  if(status==="PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE")return "فروش فرضی ثبت شد";
  return "وضع سفارش فروش نامعلوم است";
 }
 if(side==="BUY"){
  if(status==="PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE")return "خرید فرضی ثبت شده است";
  if(status==="PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE")return "سفارش خرید در انتظار نخستین جلسهٔ واجد شرایط";
  if(status==="EXPIRED_NO_FILL")return "سفارش خرید منقضی شد؛ خریدی ثبت نشد";
  return "وضع سفارش خرید نامعلوم است";
 }
 return "سفارشی در انتظار اجرا نیست";
};

const positionChip=(v:TrialAccount)=>{
 const side=orderSide(v);const status=v.account?.paper_order?.status;const has=(v.account?.holdings?.length??0)>0;
 if(side==="SELL"&&status!=="PAPER_FILLED_DAILY_CLOSE_LIMITED_QUEUE")return ["در انتظار بستن","bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"];
 if(has)return ["موقعیت باز","bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"];
 if(side==="BUY"&&status==="PENDING_FIRST_ELIGIBLE_SESSION_EVIDENCE")return ["در انتظار خرید","bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-200"];
 return ["نقد","bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"];
};

const intradayLabel=(s:string)=>s==="PREVIEW_AVAILABLE"?"پیش‌نمایش لحظه‌ای موجود است":s==="MONITOR_ONLY_EXECUTION_BLOCKED"||s==="FINAL_TICK_CAPTURE_ONLY"?"پایش فعال؛ فقط پیش‌نمایش، بدون معامله":s==="MONITOR_ERROR"||s==="LOCK_NOT_ACQUIRED"?"خطای پایش":s==="TRIAL_ENDED"?"دوره پایان یافته":s==="OUTSIDE_MARKET_WINDOW"||s==="OUTSIDE_WINDOW"?"بیرون از ساعات بازار":"در حال بررسی";

const reviewLine=(v:TrialAccount)=>{
 const r=v.review;if(!r)return null;
 const s=r.status??"";
 if(s==="REVIEW_ROTATE_SELL_RECORDED")return `چرخش مدل: فروش ${r.sold} ثبت شد؛ خرید ${r.new} پس از تسویهٔ فروش`;
 if(s==="REVIEW_REBUY_RECORDED")return `خرید جایگزین مدل: ${r.symbol} — در انتظار نخستین جلسهٔ واجد شرایط`;
 if(s==="REVIEW_HOLD")return `بازبینی مدل (${r.ranking_evaluation_date}): نفر اول تازه همان ${r.candidate} است؛ نگهداری`;
 if(s==="REVIEW_HOLD_RANKING_STALE")return "بازبینی مدل: رتبه‌بندی تازه بیشتر از حد مجاز قدیمی است؛ نگهداری بدون چرخش";
 if(s==="REVIEW_WAITING")return `بازبینی مدل: جلسهٔ ${n((r.sessions_since_fill??0)+1)} از هر ${n(r.cadence_sessions??1)} جلسه`;
 if(s==="REVIEW_ALREADY_RECORDED")return `بازبینی این جلسه قبلاً ثبت شده؛ نگهداری ${r.candidate}`;
 return null;
};

async function fetchJson<T>(path:string,signal:AbortSignal):Promise<T>{const response=await fetch(`${import.meta.env.BASE_URL}research/paper-experimental/${path}`,{cache:"no-store",signal});if(!response.ok)throw new Error(`${path} ${response.status}`);return response.json() as Promise<T>;}

export default function PaperTrialPanel(){
 const [trial,setTrial]=useState<Trial|null>(null);const [intraday,setIntraday]=useState<Intraday|null>(null);const [analysis,setAnalysis]=useState<Analysis|null>(null);const [error,setError]=useState("");const [reload,setReload]=useState(0);
 const isAdmin=getAuthStatus().isAdmin;const [retryBusy,setRetryBusy]=useState(false);const [retryMessage,setRetryMessage]=useState<{tone:"ok"|"err"|"info";text:string}|null>(null);const autoRetryTried=useRef(false);
 useEffect(()=>{const c=new AbortController();fetchJson<Trial>("trial.json",c.signal).then(setTrial).then(()=>setError("")).catch(e=>{if(!c.signal.aborted)setError(String(e.message));});fetchJson<Intraday>("intraday.json",c.signal).then(setIntraday).catch(()=>{if(!c.signal.aborted)setIntraday(null);});fetchJson<Analysis>("analysis.json",c.signal).then(setAnalysis).catch(()=>{if(!c.signal.aborted)setAnalysis(null);});return()=>c.abort();},[reload]);
 const beginRetry=async()=>{if(retryBusy)return;setRetryBusy(true);setRetryMessage({tone:"info",text:"تلاش دوبارهٔ اجرا شروع شد؛ به‌روزرسانی حساب آزمایشی قبلی و آزمون ۳۰روزهٔ P1/P3 پشت‌سرهم اجرا می‌شوند…"});try{const r=await startPaperTrialRefresh();if(r.already_running)setRetryMessage({tone:"info",text:r.message||"یک اجرای دستی دیگر در جریان است؛ تا پایان آن منتظر می‌مانیم."});}catch(e){setRetryBusy(false);setRetryMessage({tone:"err",text:e instanceof Error?e.message:"شروع تلاش دوباره ناموفق بود."});}};
 useEffect(()=>{if(!retryBusy)return;let alive=true;const t=setInterval(async()=>{try{const s=await getPaperTrialRefreshStatus();if(!alive||s.state==="Running")return;alive=false;setRetryBusy(false);setReload(x=>x+1);setRetryMessage(s.state==="Finished"?{tone:"ok",text:s.message||"اجرای دوبارهٔ سبد کاغذی کامل شد؛ داده‌های صفحه تازه شد."}:{tone:"err",text:(s.message||"اجرای دوبارهٔ سبد کاغذی با خطا تمام شد.")+(s.error?` · ${s.error}`:"")});}catch(e){/* خواندن وضعیت موقتاً شکست خورد؛ نظرسنجی ادامه می‌یابد */}},5000);return()=>{alive=false;clearInterval(t);};},[retryBusy]);
 useEffect(()=>{if(!isAdmin||autoRetryTried.current||retryBusy||!trial||trial.state!=="DAILY_ERRORS")return;autoRetryTried.current=true;const key="paperTrialAutoRetryAt";const last=Number(localStorage.getItem(key)||"0");if(Date.now()-last<30*60*1000)return;localStorage.setItem(key,String(Date.now()));void beginRetry();},[trial,isAdmin,retryBusy]);
 const stateChip=trial?(trial.state==="RUNNING"?["در حال اجرا","bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200"]:trial.state==="ENDED"?["پایان دوره","bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"]:["خطای روزانه","bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-200"]):["",""];
 return <section dir="rtl" className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-bold">آزمایش ۳۰روزهٔ P1 و P3</h2><p className="mt-1 text-xs text-slate-500">شروع {day(trial?.config.started_at_utc)} · پایان {day(trial?.config.ends_at_utc)} · آخرین اجرا {when(trial?.updated_at_utc)}</p></div><div className="flex items-center gap-2">{trial&&<span className={`rounded-full px-3 py-1 text-xs font-bold ${stateChip[1]}`}>{stateChip[0]}</span>}{isAdmin&&<button disabled={retryBusy} onClick={()=>void beginRetry()} className={`rounded-lg px-3 py-1.5 text-xs font-bold disabled:opacity-60 ${trial?.state==="DAILY_ERRORS"?"bg-amber-500 text-white hover:bg-amber-600":"border hover:bg-slate-50 dark:hover:bg-slate-800"}`}>{retryBusy?"در حال تلاش دوباره…":"تلاش دوبارهٔ اجرا"}</button>}<button className="rounded-lg border px-3 py-1.5 text-xs" onClick={()=>setReload(x=>x+1)}>بازخوانی</button></div></div>
 {error&&<p role="alert" className="text-sm text-red-600">گزارش دوره دریافت نشد: {error}</p>}
 {retryMessage&&<p role={retryMessage.tone==="err"?"alert":"status"} className={`text-sm ${retryMessage.tone==="err"?"text-red-600":retryMessage.tone==="ok"?"text-emerald-600":"text-sky-700 dark:text-sky-300"}`}>{retryMessage.text}</p>}
 <p className="text-xs text-slate-500">بستن سبد: <code>Close-Paper-Portfolio.cmd</code> · خرید دوباره: <code>Reopen-Paper-Portfolio.cmd</code> · به‌روزرسانی روزانه: <code>Update-Paper-Portfolio.cmd</code> — خرید/فروش فرضی روی قیمت پایانی نخستین جلسهٔ واجد شرایط بعد از فرمان ثبت می‌شود و به گذشته منتقل نمی‌شود. اگر اجرای روزانه خطا بدهد، بازدید از همین صفحه (برای مدیر) یک بار خودش تلاش دوباره می‌کند و دکمهٔ «تلاش دوبارهٔ اجرا» هم همان به‌روزرسانی رسمی را اجرا می‌کند.</p>
 <div className="grid gap-3 lg:grid-cols-2">{trial&&Object.entries(trial.accounts).map(([method,v])=>{
  const chip=positionChip(v);const a=v.account;const h=a?.holdings?.[0];const isErr=v.outcome?.status==="ERROR";
  return <article key={method} className="space-y-3 rounded-2xl border p-4">
   <div className="flex items-center justify-between"><h3 className="text-base font-bold">{method}</h3><span className={`rounded-full px-3 py-1 text-xs font-bold ${chip[1]}`}>{chip[0]}</span></div>
   {a&&<><div className="grid grid-cols-4 gap-2 text-center">{[["کل سبد",a.accounting.total_value_toman],["نقد",a.cash_toman],["دارایی",a.accounting.holdings_value_toman],["سود/زیان",a.accounting.profit_loss_toman]].map(([label,value])=><div key={String(label)} className="rounded-lg bg-slate-50 p-2 dark:bg-slate-800/60"><p className="text-[10px] text-slate-500">{String(label)}</p><p className={`mt-1 text-sm font-bold tabular-nums ${label==="سود/زیان"?pnlTone(Number(value)):""}`} dir="ltr">{n(Number(value))}</p></div>)}</div>
   <p className="text-sm">{h?`دارایی: ${h.symbol} · ${n(h.shares)} سهم · قیمت ${day(h.last_price_date)}`:"دارایی: نقد"}</p>
   <p className="text-xs text-slate-500">{orderLine(v)}</p>
   <p className="text-xs text-slate-500">{dailyCause(v)} · آخرین بررسی {when(trial.updated_at_utc)}</p>
   {reviewLine(v)&&<p className="text-xs font-semibold text-sky-700 dark:text-sky-300">{reviewLine(v)}</p>}</>}
   {(isErr||v.outcome?.reason)&&<details className="text-xs"><summary className={isErr?"cursor-pointer text-red-600":"cursor-pointer text-slate-500"}>جزئیات فنی این حساب</summary>{isErr&&<p className="mt-1 text-red-600" dir="auto">{v.outcome?.reason}</p>}{!isErr&&v.outcome?.reason&&<p className="mt-1 text-slate-500" dir="auto">{v.outcome.reason}</p>}{a&&<details className="mt-2"><summary className="cursor-pointer">دفتر معاملات</summary>{[...a.event_log].reverse().map(e=><p key={e.event_id} className="border-t py-1.5 text-slate-600 dark:text-slate-300">{when(e.at_utc)} — {e.reason}</p>)}</details>}</details>}
  </article>;})}</div>
 <details className="rounded-2xl border p-4 text-sm"><summary className="cursor-pointer font-bold">پایش ساعات بازار{intraday?`: ${intradayLabel(intraday.status)} · آخرین بررسی ${when(intraday.checked_at_utc)}`:""}</summary>
  {intraday&&<div className="mt-3 space-y-2"><p className="text-xs text-slate-500">{intraday.reason_fa}</p>{intraday.capture_note_fa&&<p className="text-xs" role="status">{intraday.capture_note_fa}</p>}{intraday.schedule?.missed_or_delayed_run_observed&&<p role="status" className="text-xs text-amber-700">شکاف زمان‌بندی: {n(intraday.schedule.gap_minutes_beyond_interval??0)} دقیقه بیش از فاصلهٔ معمول.</p>}
  <div className="grid gap-2 lg:grid-cols-2">{Object.entries(intraday.accounts??{}).map(([method,q])=><div key={method} className="rounded-lg border p-2 text-xs"><b>{method} · {q.status}</b><p>آخرین دریافت موفق: {when(q.last_successful_receive_at_utc??q.received_at_utc)}</p><p>آخرین قیمت صف‌دار معتبر: {q.last_valid_preview?`${when(q.last_valid_preview.market_at_utc)} · ask ${n(q.last_valid_preview.ask)} ریال`:"هنوز ثبت نشده"}</p><p className="text-slate-500">علت معامله‌نکردن: {q.reason_for_no_trade??q.reason??"—"}</p>{q.preview?.blocking_reasons&&<p className="text-slate-500">مسدودکننده‌ها: {q.preview.blocking_reasons.join("، ")}</p>}</div>)}</div>
  <p className="text-xs text-slate-400">پاسخ HTTP 200 به‌تنهایی اعتبار قیمت یا هویت را ثابت نمی‌کند؛ پایش هیچ تغییری در دفتر حساب نمی‌دهد.</p></div>}</details>
 {analysis&&<details className="rounded-2xl border p-4 text-sm"><summary className="cursor-pointer font-bold">گزارش تحلیلی {analysis.state==="FINAL"?"نهایی":"موقت"} دوره</summary>
  <div className="mt-3 space-y-2"><p>آخرین snapshot: {when(analysis.accounts.P1?.last_observed_at_utc)} · ثبت mark: {when(analysis.accounts.P1?.last_price_observed_at_utc)} · {analysis.period.stop_execution?`توقف اجرا: ${when(analysis.period.execution_stopped_at_utc)}`:"دوره در جریان است"}</p><p>پوشش اجرای برنامه: {analysis.observation_schedule_coverage?.status==="KNOWN"&&analysis.observation_schedule_coverage.fraction!==null?`${pct(analysis.observation_schedule_coverage.fraction)} (${n(analysis.observation_schedule_coverage.observed_slots??0)} از ${n(analysis.observation_schedule_coverage.scheduled_slots??0)} نوبت)`:"نامعلوم"}</p><p>{trial?.review_note_fa}</p>
  <div className="grid gap-2 lg:grid-cols-2">{Object.entries(analysis.accounts).map(([method,a])=><div key={method} className="rounded-lg border p-2 text-xs"><b>{method}</b><p>بازده خالص مشاهده‌شده: {a.net_return_toman===null?"نامعلوم":`${n(a.net_return_toman)} تومان · ${pct(a.net_return_fraction??0)}`}</p><p>بیشینه افت بین snapshotها: {a.observed_max_drawdown_fraction===null?"نامعلوم":pct(a.observed_max_drawdown_fraction)}</p><p>قیمت معتبر: {a.valid_price_coverage_fraction===null?"نامعلوم":`${pct(a.valid_price_coverage_fraction)} از نقاط دارای دارایی`} · روزهای بدون قیمت: {n(a.unique_days_without_valid_price??a.days_without_valid_price??0)}</p><p>snapshotها: {n(a.observed_points)} در {n(a.unique_observation_days??0)} روز · هزینهٔ فرضی: {n(a.assumed_cost_toman)} تومان · تراکنش‌ها: {n(a.transaction_count)}</p><p>تاریخ بازارِ قیمت آخر: {a.last_price_market_date??(a.last_price_dates.join("، ")||"ندارد")} · {a.last_price_is_stale===true?`کهنه؛ ${n(a.last_price_age_calendar_days??0)} روز اختلاف`:a.last_price_is_stale===false?"هم‌روز با snapshot":"تازگی نامعلوم"}</p>{a.costs_missing_for_transactions>0&&<p>تراکنش بدون هزینهٔ ثبت‌شده: {n(a.costs_missing_for_transactions)}</p>}</div>)}</div>
  <p className="text-xs">Benchmark: نامعلوم ({analysis.comparison.benchmark_result}) · نماد مشترک: {analysis.comparison.common_decision_symbols.join("، ")||"ندارد"} · اشتراک نماد شاهد مستقل برتری نیست.</p>{analysis.history_integrity?.status==="ISSUES"&&<p role="alert" className="text-xs text-red-600">کیفیت تاریخچه: {n(analysis.history_integrity.malformed_run_count)} اجرای روزانه خراب از تحلیل حذف شد.</p>}<p className="text-xs text-slate-400">افت فقط از نقاط ذخیره‌شده محاسبه شده و افت درون‌روزی نیست؛ قیمت‌های مفقود پر نشده‌اند.</p></div></details>}
 <details className="rounded-2xl border p-4"><summary className="cursor-pointer font-bold text-sm">حساب آزمایشی قبلی — جدا از این مقایسه</summary><div className="mt-3"><ExperimentalPaperPortfolio/></div></details></section>;
}
