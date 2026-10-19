import { useEffect, useState } from 'react';

type Factor = { factor: string; value: number | null; factor_rank: number | null; scoring_rank: number; weight: number; weighted_contribution: number; status: string };
type Row = { rank: number; symbol: string; decision_date: string; score_total: number; score_reconstructed: number; weights_observed_pct: number; data_quality_multiplier: number | null; factors: Factor[] };
type Comparison = { method: string; initial_toman: number; final_toman: number; max_drawdown: number; cost_toman: number; trade_count: number; buy_count?: number | null; sell_count?: number | null };
type NextModel = { as_of: string; family: string; config_id: string; weights_by_factor: Record<string, number>; rules: Record<string, string | number | boolean>; candidate_count: number; automated_orders: boolean };
type Snapshot = { schema_version: number; status: string; method: string; run_id: string; model_id: string; as_of: string; current_ranking_available: boolean; current_ranking_reason: string; universe_count: number; weights: number[]; rules: Record<string, string | number | boolean>; next_model: NextModel; limitations: string[]; comparison: Comparison[]; rows: Row[] };

const faNumber = (x: number, digits = 2) => x.toLocaleString('fa-IR', { maximumFractionDigits: digits });
const dateFa = (s: string) => new Date(`${s}T12:00:00+03:30`).toLocaleDateString('fa-IR', { timeZone: 'Asia/Tehran' });

export default function ResearchV10Results() {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    const controller = new AbortController();
    fetch(`${import.meta.env.BASE_URL}research/return-v10.json`, { signal: controller.signal, cache: 'no-cache' })
      .then(async response => {
        if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('خروجی رتبه‌بندی تقویت‌شدهٔ V10 در دسترس نیست.');
        const result = await response.json() as Snapshot;
        if (result.schema_version !== 1 || !Array.isArray(result.rows) || !result.run_id || !result.as_of) throw new Error('ساختار خروجی V10 معتبر نیست.');
        setData(result);
      })
      .catch((reason: Error) => { if (!controller.signal.aborted) setError(reason.message); });
    return () => controller.abort();
  }, []);

  if (error) return <section role="alert" dir="rtl" className="rounded-3xl border border-amber-200 bg-white p-5 text-sm dark:bg-gray-800">{error}</section>;
  if (!data) return <section role="status" dir="rtl" className="rounded-3xl bg-white p-5 text-sm text-gray-500 dark:bg-gray-800">در حال دریافت غربال تقویت‌شدهٔ V10…</section>;

  const currentControl = data.comparison.find(x => x.method === 'current_screen_exact_formula_v10');
  const selectedPath = data.comparison.find(x => x.method === 'selected_nested_v10');
  const selectedBehindControl = currentControl && selectedPath && selectedPath.final_toman < currentControl.final_toman;

  return <section dir="rtl" aria-labelledby="v10-title" className="space-y-5 rounded-3xl border border-indigo-200 bg-white p-5 text-gray-800 dark:border-indigo-800 dark:bg-gray-800 dark:text-gray-100">
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div><p className="text-xs font-semibold text-indigo-700 dark:text-indigo-300">گزینهٔ پژوهشی</p><h2 id="v10-title" className="mt-1 text-xl font-bold">غربال تقویت‌شده · V10</h2></div>
      <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-semibold text-amber-900 dark:bg-amber-950 dark:text-amber-200">تاریخی · سفارش ایجاد نمی‌کند</span>
    </div>
    <p className="text-sm leading-7">تاریخ معتبر: {dateFa(data.as_of)}؛ جامعهٔ آزمون: {faNumber(data.universe_count, 0)} هویت محلی. رتبه‌بندی بر اساس مدل واقعاً فعال در آخرین بلوک آزمون بیرونی ساخته شده است.</p>
    {!data.current_ranking_available && <div role="note" className="rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm leading-7 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100"><strong>این فهرست، رتبه‌بندی امروز نیست.</strong> {data.current_ranking_reason}</div>}
    {selectedBehindControl && <div role="note" className="rounded-2xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm leading-7 text-rose-950 dark:border-rose-900 dark:bg-rose-950/30 dark:text-rose-100"><strong>مدل منتخب V10 از کنترل غربال فعلی عقب ماند.</strong> مسیر بیرونی آن {faNumber(selectedPath.final_toman / 1e6)} میلیون تومان و کنترل {faNumber(currentControl.final_toman / 1e6)} میلیون تومان شد؛ بنابراین V10 نامزد پژوهشی است و جایگزین پیش‌فرض فعلی نمی‌شود.</div>}
    <div className="overflow-x-auto"><table className="w-full min-w-[620px] text-right text-sm"><caption className="sr-only">مقایسهٔ مسیر پیوستهٔ غربال پایه و مدل منتخب V10</caption><thead><tr>{['روش', 'ارزش پایانی (میلیون تومان)', 'افت بیشینه', 'هزینه (میلیون تومان)', 'معامله'].map(x => <th key={x} scope="col" className="p-3">{x}</th>)}</tr></thead><tbody>{data.comparison.map(x => <tr key={x.method} className="border-t border-gray-100 dark:border-gray-700"><th scope="row" className="p-3">{x.method === 'current_screen_exact_formula_v10' ? 'غربال فعلی، فرمول دقیق' : x.method === 'normalized_base_v10' ? 'وزن فعلی نرمال‌شده' : x.method === 'family_base' ? 'خانوادهٔ پایه (۱۸ماهه)' : x.method === 'family_weight' ? 'خانوادهٔ وزن (۱۸ماهه)' : x.method === 'family_trade' ? 'خانوادهٔ معامله (۱۸ماهه)' : x.method === 'family_joint' ? 'خانوادهٔ ترکیبی (۱۸ماهه)' : 'مدل منتخب تو‌در‌تو'}</th><td className="p-3">{faNumber(x.final_toman / 1e6)}</td><td className="p-3">{faNumber(x.max_drawdown * 100)}٪</td><td className="p-3">{faNumber(x.cost_toman / 1e6)}</td><td className="p-3">{faNumber(x.trade_count, 0)} معامله{x.buy_count != null && x.sell_count != null ? ` (${faNumber(x.buy_count, 0)} خرید / ${faNumber(x.sell_count, 0)} فروش)` : ''}</td></tr>)}</tbody></table></div>
    <details className="rounded-2xl border border-indigo-100 p-4 text-sm dark:border-indigo-900"><summary className="cursor-pointer font-semibold">تنظیم جداگانه برای داده‌های بعد از {dateFa(data.next_model.as_of)}</summary><p className="mt-2 text-xs leading-6">این مدل با خانوادهٔ {data.next_model.family} و {faNumber(data.next_model.candidate_count, 0)} نامزد ازپیش‌ثبت‌شده روی داده‌های تا تاریخ بالا بازآموزی شده است؛ بازده بعدی هنوز آزموده نشده است.</p><p className="mt-2 text-xs leading-6">وزن‌های مثبت: {Object.entries(data.next_model.weights_by_factor).filter(([, w]) => w > 0).map(([f, w]) => `${f} ${faNumber(w, 1)}`).join(' · ') || 'ندارد'}</p><p className="text-xs">N={String(data.next_model.rules.n)}؛ فاصلهٔ تصمیم {String(data.next_model.rules.cadence)} جلسه؛ تخصیص {String(data.next_model.rules.allocation)}. سفارش خودکار: خیر.</p></details>
    <div className="overflow-x-auto"><table className="w-full min-w-[500px] text-right text-sm"><caption className="sr-only">رتبه‌بندی تاریخی V10 با تجزیهٔ عامل‌ها</caption><thead><tr>{['رتبه', 'نماد', 'امتیاز', 'پوشش وزن مشاهده‌شده', 'تجزیه'].map(x => <th key={x} scope="col" className="p-3">{x}</th>)}</tr></thead><tbody>{data.rows.slice(0, 30).map(row => <tr key={row.symbol} className="border-t border-gray-100 align-top dark:border-gray-700"><td className="p-3">{faNumber(row.rank, 0)}</td><th scope="row" className="p-3">{row.symbol}</th><td className="p-3">{faNumber(row.score_total, 4)}</td><td className="p-3">{faNumber(row.weights_observed_pct)}٪</td><td className="p-3"><details><summary className="cursor-pointer text-indigo-700 dark:text-indigo-300">عامل‌ها و سهم امتیاز</summary><div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-xs"><thead><tr><th className="p-1">عامل</th><th className="p-1">مقدار</th><th className="p-1">رتبهٔ عامل</th><th className="p-1">وزن</th><th className="p-1">سهم خام</th><th className="p-1">وضعیت</th></tr></thead><tbody>{row.factors.map(f => <tr key={f.factor} className="border-t border-gray-100 dark:border-gray-700"><th className="p-1">{f.factor}</th><td className="p-1">{f.value === null ? '—' : faNumber(f.value, 4)}</td><td className="p-1">{f.factor_rank === null ? '—' : faNumber(f.factor_rank, 3)}</td><td className="p-1">{faNumber(f.weight, 1)}</td><td className="p-1">{faNumber(f.weighted_contribution, 4)}</td><td className="p-1">{f.status}</td></tr>)}</tbody></table><p className="mt-2 text-xs">امتیاز بازسازی‌شده: {faNumber(row.score_reconstructed, 6)}؛ امتیاز نهایی: {faNumber(row.score_total, 6)}</p></div></details></td></tr>)}</tbody></table></div>
    <details className="rounded-2xl border border-gray-200 p-4 text-xs leading-7 dark:border-gray-700"><summary className="cursor-pointer font-semibold">قواعد مدل و محدودیت‌ها</summary><p className="mt-2">N={String(data.rules.n)}، فاصلهٔ تصمیم={String(data.rules.cadence)} جلسه، خروج در رتبهٔ بالاتر از {String(data.rules.exit_mult)}N، تخصیص {String(data.rules.allocation)}؛ نقدشوندگی وزن صفر دارد. تنظیم‌ها می‌توانند بین بلوک‌ها تغییر کنند.</p><ul className="list-inside list-disc">{data.limitations.map(x => <li key={x}>{x}</li>)}</ul><p>شناسهٔ اجرا: {data.run_id} · مدل تاریخی: {data.model_id}</p></details>
  </section>;
}
