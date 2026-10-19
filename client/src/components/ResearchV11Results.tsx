import { useEffect, useState } from 'react';

type Factor = { factor: string; raw_value: number | null; factor_rank: number | null; weight: number; weighted_contribution: number; observed: boolean; default_contribution: number };
type Row = { rank: number; symbol: string; decision_date: string; score_total: number; score_reconstructed: number; weights_observed_pct: number; data_quality_multiplier: number | null; factors: Factor[] };
type Comparison = { method: string; initial_toman: number; final_toman: number; net_pnl_toman: number; max_drawdown: number; fee_toman: number; trades: number; buys: number; sells: number };
type Snapshot = { schema_version: number; run_id: string; status: string; method: string; panel: string; model_id: string; as_of: string; current_ranking_available: boolean; universe_count: number; weights: number[]; rules: Record<string, string | number | boolean>; data_missing_score_share_included: boolean; comparison: Comparison[]; limitations: string[]; rows: Row[] };

const faNumber = (x: number, digits = 2) => x.toLocaleString('fa-IR', { maximumFractionDigits: digits });
const dateFa = (s: string) => new Date(`${s}T12:00:00+03:30`).toLocaleDateString('fa-IR', { timeZone: 'Asia/Tehran' });
const labels: Record<string, string> = {
  v11_selected: 'مدل منتخب V11',
  baseline_exact_current: 'کنترل فعلی با فرمول دقیق',
  baseline_normalized: 'کنترل فعلی با وزن نرمال‌شده',
  repaired_v10_selection: 'انتخاب‌گر ترمیم‌شدهٔ V10',
  winning_weight_base_policy: 'وزن برنده با سیاست پایه',
};

export default function ResearchV11Results() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/return-v11.json`, { signal: controller.signal, cache: 'no-cache' })
      .then(async response => {
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('گزارش پژوهشی V11 در دسترس نیست.');
        const result = await response.json() as Snapshot;
        if (result.schema_version !== 1 || !Array.isArray(result.rows) || !result.run_id || !result.as_of) throw new Error('ساختار گزارش V11 معتبر نیست.');
        setData(result);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);

  if (error) return <section role="alert" dir="rtl" className="rounded-3xl border border-amber-200 bg-white p-5 text-sm dark:bg-gray-800">{error}</section>;
  if (!data) return <section role="status" dir="rtl" className="rounded-3xl bg-white p-5 text-sm text-gray-500 dark:bg-gray-800">در حال دریافت نتایج پژوهش V11…</section>;
  const control = data.comparison.find(x => x.method === 'baseline_exact_current');
  const chosen = data.comparison.find(x => x.method === 'v11_selected');
  const under = !!(control && chosen && chosen.final_toman < control.final_toman);
  const positiveWeights = data.weights.map((w, i) => ({ factor: data.rows[0]?.factors[i]?.factor ?? `عامل ${i + 1}`, weight: w })).filter(x => x.weight > 0);

  return <section dir="rtl" aria-labelledby="v11-title" className="space-y-5 rounded-3xl border border-violet-200 bg-white p-5 text-gray-800 dark:border-violet-800 dark:bg-gray-800 dark:text-gray-100">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold text-violet-700 dark:text-violet-300">آزمون پژوهشی</p><h2 id="v11-title" className="mt-1 text-xl font-bold">بازسازی داده و جست‌وجوی مشترک · V11</h2></div>
      <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200">تاریخی · سفارش ایجاد نمی‌کند</span>
    </div>
    <p className="text-sm leading-7">پنل اصلی P3 · تاریخ آخرین تصمیم: {dateFa(data.as_of)} · جامعهٔ ثابت: {faNumber(data.universe_count, 0)} هویت. در هر بلوک همان مدل با بیشترین سرمایهٔ پایانی در ۱۲ ماه انتخابی مستقر شده است.</p>
    {under && <div role="note" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-7 text-rose-950 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100"><strong>V11 از کنترل فعلی عقب ماند.</strong> سرمایهٔ پایانی مسیر V11 {faNumber(chosen!.final_toman / 1e6)} میلیون و کنترل {faNumber(control!.final_toman / 1e6)} میلیون تومان شد؛ بنابراین این نتیجه جایگزین رتبه‌بندی پیش‌فرض نیست.</div>}
    <div className="overflow-x-auto"><table className="w-full min-w-[650px] text-right text-sm"><caption className="sr-only">مقایسه مسیرهای بیرونی V11 روی پنل P3</caption><thead><tr>{['مسیر', 'سرمایهٔ پایانی (میلیون تومان)', 'افت بیشینه', 'هزینهٔ معامله (میلیون)', 'تعداد معامله'].map(x => <th key={x} scope="col" className="p-3">{x}</th>)}</tr></thead><tbody>{data.comparison.map(x => <tr key={x.method} className="border-t border-gray-100 dark:border-gray-700"><th scope="row" className="p-3">{labels[x.method] ?? x.method}</th><td className="p-3">{faNumber(x.final_toman / 1e6)}</td><td className="p-3">{faNumber(x.max_drawdown * 100)}٪</td><td className="p-3">{faNumber(x.fee_toman / 1e6)}</td><td className="p-3">{faNumber(x.trades, 0)} ({faNumber(x.buys, 0)} خرید / {faNumber(x.sells, 0)} فروش)</td></tr>)}</tbody></table></div>
    <details className="rounded-2xl border border-violet-100 p-4 text-sm dark:border-violet-900"><summary className="cursor-pointer font-semibold">وزن‌ها و قواعد آخرین مدل</summary><p className="mt-2 text-xs leading-7">وزن مثبت: {positiveWeights.map(x => `${x.factor} ${faNumber(x.weight, 2)}`).join(' · ') || 'ندارد'}</p><p className="text-xs leading-7">N={String(data.rules.n)}؛ بازنگری هر {String(data.rules.cadence)} جلسه؛ خروج پس از رتبهٔ {String(data.rules.exit_mult)}N؛ تخصیص {String(data.rules.allocation)}. سهم عامل‌های پیش‌فرضِ دادهٔ مفقود در امتیاز لحاظ و جداگانه نمایش داده شده است.</p></details>
    <div className="overflow-x-auto"><table className="w-full min-w-[540px] text-right text-sm"><caption className="sr-only">رتبه‌بندی تاریخی V11</caption><thead><tr>{['رتبه', 'نماد', 'امتیاز', 'وزن مشاهده‌شده', 'تجزیهٔ عامل‌ها'].map(x => <th key={x} scope="col" className="p-3">{x}</th>)}</tr></thead><tbody>{data.rows.slice(0, 25).map(row => <tr key={row.symbol} className="border-t border-gray-100 align-top dark:border-gray-700"><td className="p-3">{faNumber(row.rank, 0)}</td><th scope="row" className="p-3">{row.symbol}</th><td className="p-3">{faNumber(row.score_total, 4)}</td><td className="p-3">{faNumber(row.weights_observed_pct)}٪</td><td className="p-3"><details><summary className="cursor-pointer text-violet-700 dark:text-violet-300">مقدار، وزن و سهم پیش‌فرض</summary><div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-xs"><thead><tr>{['عامل', 'مقدار', 'وزن', 'سهم امتیاز', 'سهم پیش‌فرض'].map(x => <th key={x} className="p-1">{x}</th>)}</tr></thead><tbody>{row.factors.map(f => <tr key={f.factor} className="border-t border-gray-100 dark:border-gray-700"><th className="p-1">{f.factor}</th><td className="p-1">{f.raw_value === null ? '—' : faNumber(f.raw_value, 4)}</td><td className="p-1">{faNumber(f.weight, 2)}</td><td className="p-1">{faNumber(f.weighted_contribution, 4)}</td><td className="p-1">{faNumber(f.default_contribution, 4)}</td></tr>)}</tbody></table><p className="mt-2 text-xs">امتیاز بازسازی‌شده {faNumber(row.score_reconstructed, 6)} · امتیاز نهایی {faNumber(row.score_total, 6)}</p></div></details></td></tr>)}</tbody></table></div>
    <details className="rounded-2xl border border-gray-200 p-4 text-xs leading-7 dark:border-gray-700"><summary className="cursor-pointer font-semibold">محدودیت‌ها و شناسهٔ اجرا</summary><ul className="list-inside list-disc">{data.limitations.map(x => <li key={x}>{x}</li>)}</ul><p>اجرا: {data.run_id} · مدل: {data.model_id} · تاریخ رتبه‌بندی تاریخی است و به‌روزرسانی زنده ندارد.</p></details>
  </section>;
}
