import { useEffect, useState } from "react";

type Readiness = {
  status: string;
  formal_start_date: string | null;
  last_compatible_price_effective_date: string | null;
  last_compatible_score_effective_date: string | null;
  last_compatible_calendar_session: string | null;
  stale_calendar_days_to_execution_date: number | null;
  calendar_status: string;
  o00_next_scheduled_date: string | null;
  source_received_at: string | null;
  official_event_count: number;
  missing_inputs: Array<{ input: string; needed_for: string }>;
};
type OfficialState = {
  status: string;
  formal_start_date: string | null;
  last_decision: string | null;
  pending_orders: unknown[] | Record<string, unknown[]>;
  account_results: Record<string, { nav_toman: number | null; net_profit_toman: number | null; valuation_status: string; fees_toman: number }> | null;
  official_event_count: number;
};

const base = `${import.meta.env.BASE_URL}research/future-eval-v12-28-`;
const links = [
  ["قرارداد ماشین‌خوان و قفل‌شده", "contract.json"],
  ["هش قرارداد", "contract.sha256"],
  ["تقویم مهرشدهٔ O00 تا ۲۴ فوریهٔ ۲۰۲۶", "o00-session-calendar.csv"],
  ["جدول آمادگی داده", "readiness.fa.csv"],
  ["وضعیت رسمی دفتر", "official-state.json"],
  ["دفتر رویداد رسمی (خالی تا آغاز)", "events.jsonl"],
  ["تصمیم‌های رسمی (خالی تا آغاز)", "decisions.jsonl"],
  ["قالب snapshot ورودی", "snapshot-schema.json"],
] as const;

export default function FutureEvaluationV1228Section() {
  const [data, setData] = useState<Readiness | null>(null);
  const [official, setOfficial] = useState<OfficialState | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let cancelled = false;
    Promise.all([fetch(`${base}status.json`), fetch(`${base}official-state.json`)])
      .then(async ([readinessResponse, stateResponse]) => {
        if (!readinessResponse.ok || !stateResponse.ok) throw new Error(`HTTP ${readinessResponse.status}/${stateResponse.status}`);
        return [await readinessResponse.json(), await stateResponse.json()] as const;
      })
      .then(([readiness, state]) => { if (!cancelled) { setData(readiness as Readiness); setOfficial(state as OfficialState); } })
      .catch((reason) => { if (!cancelled) setError(String(reason)); });
    return () => { cancelled = true; };
  }, []);

  return (
    <section className="space-y-4 rounded-3xl border border-violet-300 bg-violet-50/50 p-4 sm:p-6 dark:border-violet-900 dark:bg-violet-950/15" dir="rtl" aria-labelledby="future-eval-title">
      <header>
        <h2 id="future-eval-title" className="text-xl font-bold">ارزیابی آینده — قرارداد قفل‌شدهٔ V12.28</h2>
        <p className="mt-2 text-sm leading-7">آماده‌سازی دو حساب کاغذی مستقل؛ هیچ ثبت رسمی یا سفارش واقعی آغاز نشده است. تا شروع رسمی، نتیجه یا نمودار بازده آینده وجود ندارد.</p>
      </header>
      <div className="grid gap-3 sm:grid-cols-2">
        <article className="rounded-2xl border bg-white/70 p-4 dark:bg-black/10">
          <h3 className="font-semibold">نامزد اصلی · P1/O00/G0 · valuation_0</h3>
          <p className="mt-2 text-sm">سرمایهٔ آغاز مستقل: ۱۰۰٬۰۰۰٬۰۰۰ تومان</p>
        </article>
        <article className="rounded-2xl border bg-white/70 p-4 dark:bg-black/10">
          <h3 className="font-semibold">کنترل مقایسه‌ای · P3/O00/G0 · w0</h3>
          <p className="mt-2 text-sm">سرمایهٔ آغاز مستقل: ۱۰۰٬۰۰۰٬۰۰۰ تومان</p>
        </article>
      </div>
      <div className="rounded-2xl border bg-white/70 p-4 text-sm leading-7 dark:bg-black/10" aria-live="polite">
        {error ? <p role="alert">وضعیت محلی بار نشد: {error}</p> : !data ? <p role="status">در حال خواندن وضعیت محلی…</p> : <>
          <p><strong>وضعیت:</strong> {(official?.status ?? data.status) === "WAITING_FOR_DATA" ? "منتظر داده" : (official?.status ?? data.status)}</p>
          <p><strong>آخرین پنل سازگار:</strong> قیمت {data.last_compatible_price_effective_date ?? "ناموجود"} · امتیاز {data.last_compatible_score_effective_date ?? "ناموجود"} · تقویم {data.last_compatible_calendar_session ?? "ناموجود"}</p>
          <p><strong>زمان دریافت snapshot سازگار:</strong> {data.source_received_at ?? "در منبع معتبر ثبت نشده"}</p>
          <p><strong>فاصلهٔ تقویم تا امروز:</strong> {data.stale_calendar_days_to_execution_date ?? "نامعلوم"} روز · <strong>تقویم بعدی:</strong> {data.calendar_status}{data.o00_next_scheduled_date ? ` · ${data.o00_next_scheduled_date}` : "؛ تاریخ قابل تعیین نیست"}</p>
          <p><strong>آغاز رسمی:</strong> {official?.formal_start_date ?? data.formal_start_date ?? "تعیین نشده"} · <strong>آخرین تصمیم:</strong> {official?.last_decision ?? "ثبت نشده"} · <strong>ثبت رسمی:</strong> {official?.official_event_count ?? data.official_event_count} رویداد</p>
          <p><strong>سفارش معلق:</strong> {official ? (Array.isArray(official.pending_orders) ? official.pending_orders.length : Object.values(official.pending_orders).reduce((sum, rows) => sum + rows.length, 0)) : 0}</p>
          {official?.account_results ? <div className="mt-2 grid gap-2 sm:grid-cols-2">{Object.entries(official.account_results).map(([method, result]) => <p key={method} className="rounded-lg bg-violet-100 p-2 dark:bg-violet-900/30"><strong>{method}:</strong> NAV ثبت‌شده {result.nav_toman?.toLocaleString("fa-IR") ?? "نامعلوم"} تومان · سود خالص {result.net_profit_toman?.toLocaleString("fa-IR") ?? "نامعلوم"} · کارمزد {result.fees_toman.toLocaleString("fa-IR")} · {result.valuation_status}</p>)}</div> : <p><strong>نتیجهٔ دو حساب:</strong> تا ثبت معتبر اجرا و ارزش‌گذاری نمایش داده نمی‌شود.</p>}
        </>}
      </div>
      <div>
        <h3 className="font-semibold">ورودی‌های لازم برای آغاز</h3>
        <ul className="mt-2 list-disc space-y-1 px-6 text-xs leading-6">
          {(data?.missing_inputs ?? []).map((item) => <li key={item.input}><strong>{item.input}:</strong> {item.needed_for}</li>)}
        </ul>
      </div>
      <div className="flex flex-wrap gap-3 text-xs">
        {links.map(([label, file]) => <a key={file} className="underline" href={base + file} download>{label}</a>)}
      </div>
    </section>
  );
}
