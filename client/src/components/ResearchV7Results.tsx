import { useEffect, useState } from 'react';

export interface V7Snapshot {
  schema_version: number; run_id: string; source_V6_run: string; start: string; end: string; status: string;
  comparison: Array<{method: string; label: string; final_toman: number; drawdown_percent: number; cost_toman: number; maximum_weight_percent: number}>;
  initial_hold: {final_toman: number; drawdown_percent: number; cost_toman: number; maximum_weight_percent: number};
  kaspian_growth: Array<{window: string; first_fill: string; mark_date: string; index_price_growth_multiple: number; hypothetical_100m_fully_invested_marked_toman: number; actual_capacity_limited_toman: number; actual_initial_bought_toman: number}>;
  kaspian_decisions: Array<{date: string; rank: number | null; target_weight_percent: number; actual_weight_percent: number; why: string; sell_reason: string; execution: string; holding_reason: string}>;
  case_note: string; winner_note: string; limitations: string[];
}
const n = (x: number) => x.toLocaleString('fa-IR', { maximumFractionDigits: 2 });
const date = (s: string) => new Date(`${s}T12:00:00+03:30`).toLocaleDateString('fa-IR', {timeZone: 'Asia/Tehran'});
export function ResearchV7View({data}: {data: V7Snapshot}) {
  return <section aria-labelledby="v7-title" className="space-y-5 rounded-3xl border border-teal-200 bg-white p-5 dark:border-teal-800 dark:bg-gray-800">
    <h2 id="v7-title" className="text-xl font-bold">V7 · انتخاب بهتر یا نگهداری طولانی‌تر؟</h2>
    <p className="text-sm leading-7">{data.status} مقایسه با سرمایهٔ اولیهٔ ۱۰۰ میلیون تومان، از {date(data.start)} تا {date(data.end)}؛ NAV شاخصی پس از هزینهٔ فرضی، با اقتصاد کامل نامعلوم.</p>
    <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-right text-sm"><caption className="sr-only">مقایسهٔ ثابت انتخاب و نگهداری در V7</caption><thead><tr>{['روش', 'پایانی (میلیون تومان)', 'افت بیشینه', 'هزینه (میلیون تومان)', 'بیشترین وزن سهم'].map(s => <th key={s} scope="col" className="p-3">{s}</th>)}</tr></thead><tbody>{data.comparison.map(r => <tr key={r.method} className="border-t border-gray-100 dark:border-gray-700"><th scope="row" className="p-3">{r.label}</th><td className="p-3">{n(r.final_toman / 1e6)}</td><td className="p-3">{n(r.drawdown_percent)}٪</td><td className="p-3">{n(r.cost_toman / 1e6)}</td><td className="p-3">{n(r.maximum_weight_percent)}٪</td></tr>)}</tbody></table></div>
    <p className="text-sm leading-7">اگر فقط همان ده انتخاب اول S2 را نگه می‌داشتیم: {n(data.initial_hold.final_toman / 1e6)} میلیون تومان، با افت {n(data.initial_hold.drawdown_percent)}٪. کاهش هزینه به‌تنهایی کافی نبود؛ هیچ نامزد تازه‌ای در هر دو بلوک کامل بهتر نشد.</p>
    <div className="rounded-2xl bg-amber-50 p-4 dark:bg-amber-950/30"><h3 className="font-bold">کاسپین · مطالعهٔ موردی با اطلاع از نتیجه</h3><p className="mt-2 text-xs leading-7">{data.case_note}</p>
      {data.kaspian_growth.map(r => <article key={r.window} className="mt-4 border-t border-amber-200 pt-3 dark:border-amber-900"><h4 className="text-sm font-semibold">{r.window === 'V6' ? 'پنجرهٔ یکسان با V6' : 'از ابتدای آبان ۱۴۰۳ تا پایان اسفند ۱۴۰۴؛ فروش انتها تأیید نشده'}</h4><p className="mt-2 text-sm leading-7">نخستین خرید: {date(r.first_fill)}؛ آخرین مشاهدهٔ قیمت: {date(r.mark_date)}. رشد قیمت شاخصی: {n(r.index_price_growth_multiple)} برابر.</p><p className="text-sm leading-7">با فرض سرمایه‌گذاری کامل و بدون قید ظرفیت: {n(r.hypothetical_100m_fully_invested_marked_toman / 1e6)} میلیون تومان ارزش شاخصی. این فرض با ظرفیت مدل قابل اجرا نبود.</p><p className="text-sm leading-7">حساب محدود به ظرفیت: {n(r.actual_capacity_limited_toman / 1e6)} میلیون تومان؛ خرید اولیه فقط {n(r.actual_initial_bought_toman / 1e6)} میلیون تومان و باقی نقد. این عدد، فروش واقعی یا نقد قابل برداشت نیست.</p></article>)}
    </div>
    <details className="rounded-2xl border border-gray-200 p-4 dark:border-gray-700"><summary className="cursor-pointer font-semibold">کاسپین چرا انتخاب شد، نگه داشته شد یا برای فروش رفت؟</summary><p className="mt-3 text-xs leading-7">در شروع رتبهٔ ۱۲ داشت؛ داده کافی بود اما جزو ده سهم اول نبود. تغییر هدف با انجام معامله فرق دارد. فروش جزئی برای بازگرداندن وزن به ۱۰٪ نیز به معنی خروج کامل نیست. در نگهداری ۱۲۰جلسه‌ای تغییر رتبهٔ میان‌دوره خروج اختیاری ایجاد نمی‌کند.</p><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[950px] text-right text-xs"><caption className="sr-only">دلایل و اجرای تصمیم‌های S2 دربارهٔ کاسپین</caption><thead><tr>{['تاریخ تصمیم', 'رتبه', 'وزن واقعی / هدف', 'دلیل انتخاب یا کنارگذاشتن', 'دلیل سفارش فروش', 'اجرای ثبت‌شده'].map(s => <th key={s} scope="col" className="p-3">{s}</th>)}</tr></thead><tbody>{data.kaspian_decisions.map(r => <tr key={r.date} className="border-t border-gray-100 dark:border-gray-700"><th scope="row" className="p-3">{date(r.date)}</th><td className="p-3">{r.rank === null ? 'فاقد رتبهٔ مجاز' : n(r.rank)}</td><td className="p-3">{n(r.actual_weight_percent)}٪ / {n(r.target_weight_percent)}٪</td><td className="p-3 leading-6">{r.why}</td><td className="p-3 leading-6">{r.sell_reason}</td><td className="p-3 leading-6">{r.execution}</td></tr>)}</tbody></table></div></details>
    <p className="text-xs leading-7 text-gray-500 dark:text-gray-300">{data.winner_note}</p>
    <ul className="list-inside list-disc space-y-2 text-xs leading-6 text-gray-500 dark:text-gray-300">{data.limitations.map(s => <li key={s}>{s}</li>)}</ul>
  </section>;
}
export default function ResearchV7Results({sourceRun}: {sourceRun: string}) {
  const [data, setData] = useState<V7Snapshot | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();setData(null);setError('');
    fetch(`${import.meta.env.BASE_URL}research/return-v7.json`, {signal: controller.signal, cache: 'no-cache'}).then(async r => {
      if (!r.ok || !r.headers.get('content-type')?.includes('application/json')) throw new Error('دریافت نتیجهٔ V7 ممکن نشد.');
      const d: V7Snapshot = await r.json();
      if (d.schema_version !== 1 || d.source_V6_run !== sourceRun || !Array.isArray(d.comparison) || !Array.isArray(d.kaspian_decisions)) throw new Error('نسخهٔ V7 با پژوهش مرجع مطابقت ندارد.');
      setData(d);
    }).catch((e: Error) => {if (!controller.signal.aborted) setError(e.message);});
    return () => controller.abort();
  }, [sourceRun, attempt]);
  if (error) return <div role="alert" className="rounded-2xl border p-5"><p>{error}</p><button className="mt-3 underline" onClick={() => setAttempt(a => a + 1)}>تلاش دوباره</button></div>;
  if (!data) return <p role="status">در حال دریافت مقایسهٔ V7…</p>;
  return <ResearchV7View data={data} />;
}
