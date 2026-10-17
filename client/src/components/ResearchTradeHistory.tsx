import { useEffect, useState } from 'react';

interface Fill { fill_id: number; date: string; decision_time: string; symbol: string; side: 'buy' | 'sell'; index_units: number; index_price_rial: number; gross_rial: number; fee_rial: number }
interface History { schema_version: number; run_id: string; method: string; start: string; end: string; fills: Fill[] }
const number = (n: number) => n.toLocaleString('fa-IR', { maximumFractionDigits: 2 });
const price = (rial: number) => (rial / 10).toLocaleString('fa-IR', { maximumSignificantDigits: 8 });
const date = (s: string) => new Date(s + 'T12:00:00+03:30').toLocaleDateString('fa-IR', { timeZone: 'Asia/Tehran' });
const normalize = (s: string) => s.replace(/ي/g, 'ی').replace(/ك/g, 'ک').trim();

export default function ResearchTradeHistory({ runId }: { runId: string }) {
  const [data, setData] = useState<History | null>(null);
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [symbol, setSymbol] = useState('');
  const [side, setSide] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [limit, setLimit] = useState(50);
  useEffect(() => {
    const controller = new AbortController();
    setData(null); setError('');
    fetch(`${import.meta.env.BASE_URL}research/return-v6-trades.json`, { signal: controller.signal, cache: 'no-cache' })
      .then(async r => {
        if (!r.ok || !r.headers.get('content-type')?.includes('application/json')) throw new Error('دریافت تاریخچه ممکن نشد.');
        const d: History = await r.json();
        if (d.schema_version !== 1 || d.run_id !== runId || d.method !== 'S2_publication' || !Array.isArray(d.fills)) throw new Error('تاریخچه با نسخهٔ پژوهش مطابقت ندارد.');
        setData(d);
      }).catch((e: Error) => { if (!controller.signal.aborted) setError(e.message); });
    return () => controller.abort();
  }, [runId, attempt]);
  const rows = (data?.fills ?? []).filter(r => normalize(r.symbol).includes(normalize(symbol)) && (!side || r.side === side) && (!from || r.date >= from) && (!to || r.date <= to)).sort((a, b) => b.date.localeCompare(a.date) || a.fill_id - b.fill_id);
  const field = 'rounded-lg border border-gray-300 bg-white p-2 text-sm dark:border-gray-600 dark:bg-gray-900';
  return <section aria-labelledby="trade-history-title" className="rounded-3xl border border-gray-200 bg-white p-5 dark:border-gray-700 dark:bg-gray-800">
    <h2 id="trade-history-title" className="text-lg font-bold">تاریخچهٔ خرید و فروش · S2 دوهفته‌ای</h2>
    <p className="mt-2 text-sm leading-7">معاملات شبیه‌سازی روش حفظ‌شده در آخرین پژوهش، با سرمایهٔ اولیهٔ ۱۰۰ میلیون تومان. مقدار، واحد شاخصی است و تعداد واقعی سهام نیست؛ مبلغ‌ها تومان‌اند. قیمت واحد شاخصی، قیمت خام تابلو نیست. بازده اقتصادی کامل هنوز نامعلوم است.</p>
    {data && <p className="mt-2 text-xs text-gray-500">بازهٔ حساب: {date(data.start)} تا {date(data.end)}؛ این معاملات مربوط به فهرست رتبه‌بندی مهر ۱۴۰۵ نیستند.</p>}
    {error ? <div role="alert" className="mt-4"><p>{error}</p><button className={field} onClick={() => setAttempt(a => a + 1)}>تلاش دوباره</button></div> : !data ? <p role="status" className="mt-4">در حال دریافت معاملات…</p> : <>
      <div className="mt-4 flex flex-wrap gap-3">
        <label className="flex flex-col gap-1 text-xs">نماد<input className={field} value={symbol} onChange={e => { setSymbol(e.target.value); setLimit(50); }} placeholder="جست‌وجوی نماد" /></label>
        <label className="flex flex-col gap-1 text-xs">نوع معامله<select className={field} value={side} onChange={e => { setSide(e.target.value); setLimit(50); }}><option value="">همه</option><option value="buy">خرید</option><option value="sell">فروش</option></select></label>
        <label className="flex flex-col gap-1 text-xs">از تاریخ اجرا (میلادی)<input type="date" className={field} value={from} onChange={e => { setFrom(e.target.value); setLimit(50); }} /></label>
        <label className="flex flex-col gap-1 text-xs">تا تاریخ اجرا (میلادی)<input type="date" className={field} value={to} onChange={e => { setTo(e.target.value); setLimit(50); }} /></label>
        <button className={field} onClick={() => { setSymbol(''); setSide(''); setFrom(''); setTo(''); setLimit(50); }}>پاک‌کردن فیلترها</button>
      </div>
      <p role="status" className="mt-4 text-sm">{number(rows.length)} معامله؛ خرید {number(rows.filter(r => r.side === 'buy').reduce((s, r) => s + r.gross_rial / 10, 0))} تومان؛ فروش {number(rows.filter(r => r.side === 'sell').reduce((s, r) => s + r.gross_rial / 10, 0))} تومان (ناخالص، در فیلتر فعلی)</p>
      {rows.length === 0 ? <p className="py-6">معامله‌ای با این فیلترها وجود ندارد.</p> : <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[850px] text-right text-sm"><caption className="sr-only">معاملات تاریخی S2؛ جدیدترین تاریخ در ابتدا</caption><thead><tr>{['تاریخ اجرا', 'تاریخ تصمیم', 'نماد', 'عملیات', 'واحد شاخصی', 'مبلغ ناخالص (تومان)', 'هزینه (تومان)', 'قیمت واحد شاخصی (تومان)'].map(s => <th key={s} scope="col" className="p-3">{s}</th>)}</tr></thead><tbody>{rows.slice(0, limit).map(r => <tr key={r.fill_id} className="border-t border-gray-100 dark:border-gray-700"><td className="p-3" title={r.date}>{date(r.date)}</td><td className="p-3" title={r.decision_time}>{date(r.decision_time)}</td><th scope="row" className="p-3">{r.symbol}</th><td className={`p-3 ${r.side === 'buy' ? 'text-emerald-700 dark:text-emerald-300' : 'text-red-700 dark:text-red-300'}`}>{r.side === 'buy' ? 'خرید' : 'فروش'}</td><td className="p-3">{number(r.index_units)}</td><td className="p-3">{number(r.gross_rial / 10)}</td><td className="p-3">{number(r.fee_rial / 10)}</td><td className="p-3" dir="ltr">{price(r.index_price_rial)}</td></tr>)}</tbody></table></div>}
      {rows.length > limit && <button className={`${field} mt-4`} onClick={() => setLimit(n => n + 50)}>نمایش ۵۰ معاملهٔ دیگر</button>}
    </>}
  </section>;
}
