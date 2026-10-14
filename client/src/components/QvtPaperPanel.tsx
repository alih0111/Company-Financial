import { type QvtPaperSummary } from "../utils/api";
import { useState } from "react";

const number = (value: number) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 1 }).format(value);
const outcome = (value: number | null | undefined) => value == null ? "هنوز قابل محاسبه نیست" : `${number(value)}٪`;

export default function QvtPaperPanel({ data, error, onRefresh, sourceChanged, sourceHashes }: {
  data: QvtPaperSummary | null;
  error: string | null;
  onRefresh: () => void;
  sourceChanged: boolean;
  sourceHashes?: Partial<Record<"q" | "v" | "t", string>>;
}) {
  const [cadence, setCadence] = useState<"1m" | "6m">("1m");
  if (!data) return <div className="rounded-2xl border border-gray-200 dark:border-gray-700 p-4 text-sm dark:text-gray-200">
    {error || "در حال دریافت وضعیت آزمایش…"}
    {error && <button onClick={onRefresh} className="mr-3 text-indigo-600 dark:text-indigo-300">تلاش دوباره</button>}
  </div>;
  if (data.historical) {
    const strategyChanged = !!data.strategy && !!sourceHashes && (["q", "v", "t"] as const).some(axis => data.strategy?.source_hashes[axis] !== sourceHashes[axis]);
    const h = data.historical;
    const rebuilt = h.scope === "reconstructed_subset";
    const selected = h.cadences?.find((c) => c.id === cadence);
    const top = selected?.top10 ?? h.top10;
    const benchmark = selected?.benchmark ?? h.benchmark;
    const difference = top.annualized_return_pct - benchmark.annualized_return_pct;
    const dateLabel = (date: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(`${date}T12:00:00Z`));
    return <div className="space-y-3 text-sm text-gray-700 dark:text-gray-200">
      {data.research && <div className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 leading-6">
        <p className="font-bold">وضعیت آماده‌سازی سیستم سرمایه‌گذاری</p>
        <p className="mt-1 text-xs">{data.research.status_label}</p>
        <details className="mt-2 text-xs"><summary className="cursor-pointer">پیشرفت بررسی‌ها</summary>
          <p className="mt-2">{number(data.research.n_comparisons)} مقایسهٔ عوامل و سیاست نگهداری، همراه بررسی مستقل {number(data.research.checked_scenarios)} سناریوی حسابداری و محدودیت اجرا انجام شده است.</p>
          <p>{number(data.research.gaps.live_unscored)} نماد فعلاً امتیاز کامل ندارند؛ علت‌ها ثبت و برای بررسی اولویت‌بندی شده‌اند.</p>
          {!!data.research.gaps.partial_statement_candidates && <p>برخی اقلام صورت‌های مالی در {number(data.research.gaps.partial_statement_candidates)} گزارش تاریخی هنوز کامل نیستند؛ آزمون فقط از عوامل موردنیازِ قابل‌تأیید استفاده می‌کند.</p>}
          {data.research.chronological && <p>{data.research.chronological.status_label}.</p>}
          <p>بازهٔ برآورد اختلاف بازده سالانهٔ مدل فعلی با مرجع همسان: {number(data.research.uncertainty.interval_95[0])} تا {number(data.research.uncertainty.interval_95[1])} واحد درصد. این برآورد بر پایهٔ همین گذشته است و احتمال سود آینده نیست.</p>
        </details>
      </div>}
      {data.strategy && <div className="rounded-xl bg-gray-50 dark:bg-gray-800 p-3 text-xs leading-6">
        <p className="font-bold">برنامهٔ آزمایشی انتخاب سهم</p>
        <p>{strategyChanged ? "رتبه‌بندی تغییر کرده؛ برنامهٔ آزمایشی نیاز به محاسبهٔ مجدد دارد." : data.strategy.status_label}</p>
        {!strategyChanged && data.strategy.snapshot_fresh && <p>{data.strategy.positions.length ? `نامزدهای واجد شرایط این سیاست: ${data.strategy.positions.map(p => p.symbol).join("، ")}. سهم نقد فرضی: ${number(data.strategy.cash_weight * 100)}٪.` : "سهم واجد شرایط این سیاست وجود ندارد؛ برنامهٔ فرضی نقد می‌ماند."}</p>}
        <p className="text-gray-500 dark:text-gray-400">به دارایی‌های واقعی یا کارگزاری متصل نیست؛ این برنامه دستور خرید نیست.</p>
      </div>}
      <div className="rounded-2xl border border-indigo-200 dark:border-indigo-900 bg-indigo-50 dark:bg-indigo-900/15 p-4">
        <h2 className="font-bold">نتیجهٔ بررسی سال‌های قبل</h2>
        <p className="mt-2 leading-6">{Math.abs(difference) < 1 ? "بازده انتخاب ۱۰ سهم برتر و گروه مقایسه در این آزمون نزدیک بوده است." : difference > 0 ? "انتخاب ۱۰ سهم برتر در این آزمون بازده بیشتری از گروه مقایسه داشته است." : "انتخاب ۱۰ سهم برتر در این آزمون بازده کمتری از گروه مقایسه داشته است."}</p>
        <p className="mt-1 text-xs leading-5 text-gray-500 dark:text-gray-400">{rebuilt ? "بخش قابل‌بازسازی بنیادی، ارزندگی و شرایط ورود بررسی شده؛ تمام عوامل و کنترل‌های معاملاتی مدل فعلی بازپخش نشده‌اند." : "این آزمون فقط بخش قابل‌بازسازی شرایط ورود را می‌سنجد؛ نتیجهٔ امتیاز کامل بنیادی، ارزندگی و ورود نیست."}</p>
      </div>
      {h.cadences && <div className="flex gap-2" aria-label="فاصلهٔ تغییر سبد">{(["1m", "6m"] as const).map((id) => <button key={id} onClick={() => setCadence(id)} aria-pressed={cadence === id} className={`rounded-lg px-3 py-2 text-xs ${cadence === id ? "bg-indigo-600 text-white" : "bg-gray-100 dark:bg-gray-800"}`}>{id === "1m" ? "تغییر ماهانهٔ سبد" : "تغییر با فاصلهٔ حداقل ۶ ماه"}</button>)}</div>}
      <div className="overflow-x-auto rounded-xl border border-gray-200 dark:border-gray-700">
        <table className="w-full text-right text-sm">
          <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400"><tr><th className="p-3">معیار</th><th className="p-3">۱۰ سهم برتر{rebuilt ? "" : " ورود"}</th><th className="p-3">گروه مقایسه</th></tr></thead>
          <tbody>
            <tr className="border-t border-gray-100 dark:border-gray-800"><td className="p-3">بازده سالانهٔ فرضی</td><td className="p-3">{outcome(top.annualized_return_pct)}</td><td className="p-3">{outcome(benchmark.annualized_return_pct)}</td></tr>
            <tr className="border-t border-gray-100 dark:border-gray-800"><td className="p-3">بازده کل دوره</td><td className="p-3">{outcome(top.cumulative_return_pct)}</td><td className="p-3">{outcome(benchmark.cumulative_return_pct)}</td></tr>
            <tr className="border-t border-gray-100 dark:border-gray-800"><td className="p-3">بیشترین افت مشاهده‌شده</td><td className="p-3">{outcome(top.max_drawdown_pct)}</td><td className="p-3">{outcome(benchmark.max_drawdown_pct)}</td></tr>
          </tbody>
        </table>
      </div>
      <p className="text-xs leading-6">از {dateLabel(h.start)} تا {dateLabel(h.end)}؛ {number(h.n_dates)} تاریخ تصمیم قابل ارزیابی. هر دو ستون هزینهٔ فرضی ۰٫۵٪ خرید و ۰٫۵٪ فروش دارند. گروه مقایسه میانگین سهم‌های واجد شرایط همان آزمون است، نه شاخص بورس.</p>
      <p className="rounded-xl bg-amber-50 dark:bg-amber-900/15 p-3 text-xs text-amber-800 dark:text-amber-200 leading-6">این نتیجه تضمین عملکرد آینده نیست. {rebuilt ? "مدل کامل و امکان اجرای سفارش در صف هنوز تأیید نشده‌اند. افت سرمایه از قیمت‌های روزانه محاسبه شده است." : "برای آزمون کامل، داده‌های مالی تاریخی باید تکمیل شوند؛ افت سرمایه بر پایهٔ مشاهده‌های ماهانه است."}</p>
      <details className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 text-xs leading-6"><summary className="cursor-pointer">جزئیات و محدودیت‌های آزمون</summary><p className="mt-2">بازده اسمی است و سود نقدی کامل را پوشش نمی‌دهد. جامعهٔ سهام و نگاشت شرکت‌ها محدودیت سوگیری بقا دارند؛ این سال‌ها قبلاً در پژوهش پروژه دیده شده‌اند و آزمون مستقلِ دست‌نخورده نیستند.</p>{rebuilt && <p>در هر تاریخ {number(h.min_complete ?? 0)} تا {number(h.max_complete ?? 0)} سهم عوامل یکسان داشته‌اند. بخش بررسی‌شده {number(h.score_ceiling)} واحد از طراحی ۱۰۰ واحدی است. نسخه‌های اصلاحیه با زمان انتشار خودشان وارد شده‌اند و تعداد سهام از شواهد تاریخ‌دار بازسازی شده است. در تاریخ‌های فاقد تصمیم، دارایی‌ها نگهداری شده‌اند؛ فاصلهٔ روش دوم ممکن است بیشتر از شش ماه باشد.</p>}</details>
      <p className="text-xs text-gray-500 dark:text-gray-400">پایش سبد آینده به درخواست شما غیرفعال شده است. هیچ معاملهٔ واقعی انجام نمی‌شود.</p>
    </div>;
  }
  return <div className="space-y-3">
    <div className="rounded-2xl border border-indigo-200 dark:border-indigo-900 bg-indigo-50 dark:bg-indigo-900/15 p-4">
      <h2 className="font-bold text-gray-800 dark:text-gray-100">آزمایش سبد خودکار</h2>
      <p className="mt-2 text-sm text-gray-700 dark:text-gray-200 leading-6">{data.status_label}. این آزمایش انتخاب‌های مدل را ثبت می‌کند تا عملکردشان را با گذشت زمان بسنجیم.</p>
      <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-5">سرمایه فرضی است و هیچ سفارش واقعی ارسال نمی‌شود. این سبد از دارایی‌های شخصی شما جداست.</p>
      {data.observer?.enabled && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400 leading-5">{data.observer.schedule_label}</p>}
      {data.observer && !data.observer.enabled && <p className="mt-1 text-xs text-gray-500 dark:text-gray-400">پایش روزانه غیرفعال است.</p>}
      {data.observer?.status === "failed" && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{data.observer.message}</p>}
    </div>
    {sourceChanged && <p className="rounded-xl bg-amber-50 dark:bg-amber-900/15 p-3 text-xs text-amber-800 dark:text-amber-200 leading-5">رتبه‌بندی جدیدتر شده، اما انتخاب‌های ثبت‌شدهٔ این دوره حفظ شده‌اند تا نتیجهٔ آزمایش قابل ارزیابی باشد.</p>}
    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
      {[
        ["سرمایهٔ فرضی", data.virtual_capital_rial == null ? "—" : `${number(data.virtual_capital_rial / 10)} تومان`],
        ["سهم نقد در برنامه", data.cash_weight == null ? "—" : `${number(data.cash_weight * 100)}٪`],
        ["بازده فرضی پس از هزینه", outcome(data.return_pct)],
        ["بازده گروه مقایسه", outcome(data.benchmark_return_pct)],
      ].map(([label, value]) => <div key={label} className="rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-800/30 p-3">
        <p className="text-xs text-gray-500 dark:text-gray-400">{label}</p>
        <p className="mt-2 font-bold text-sm text-gray-800 dark:text-gray-100">{value}</p>
      </div>)}
    </div>
    {data.positions.length === 0 ? <p className="text-sm text-gray-500 dark:text-gray-400">در این دوره سهم واجد شرایطی انتخاب نشده؛ سرمایهٔ فرضی نقد می‌ماند.</p> :
      <div className="overflow-x-auto rounded-2xl border border-gray-200 dark:border-gray-700">
        <table className="w-full text-right text-xs">
          <thead className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400"><tr>
            <th className="p-3">نماد</th><th className="p-3">سهم از سبد</th><th className="p-3">وضعیت آزمایش</th><th className="p-3">بازده فرضی</th>
          </tr></thead>
          <tbody>{data.positions.map((p) => <tr key={p.company_id} className="border-t border-gray-100 dark:border-gray-800 text-gray-700 dark:text-gray-200">
            <td className="p-3 font-bold">{p.symbol}</td><td className="p-3">{number(p.weight * 100)}٪</td>
            <td className="p-3">{p.status_label}</td><td className="p-3">{outcome(p.return_pct)}</td>
          </tr>)}</tbody>
        </table>
      </div>}
    <p className="text-xs text-gray-500 dark:text-gray-400 leading-5">برای تکمیل ۱۰ سهم، شرایط را ضعیف نمی‌کنیم. سهم هر نماد حداکثر ۱۰٪ و هر صنعت حداکثر ۳۰٪ در این آزمایش است؛ ظرفیت باقی‌مانده نقد می‌ماند.</p>
    <details className="rounded-xl border border-gray-200 dark:border-gray-700 p-3 text-xs text-gray-600 dark:text-gray-300 leading-6">
      <summary className="cursor-pointer">جزئیات آزمایش</summary>
      <p className="mt-2">{data.note}</p>
      <p>{data.cost_assumption}</p>
      <p>مرجع مقایسه، میانگین سهم‌های دارای عوامل یکسان است؛ شاخص بورس نیست. وجود معامله در روز و قیمت پایانی، امکان اجرای سفارش در صف را اثبات نمی‌کند.</p>
      <p>انتخاب‌های این دوره تا پایان آزمایش تغییر نمی‌کنند. نتایج دوره‌های مختلف مستقل‌اند و هنوز بازده یک سبد پیوسته نیستند.</p>
      {data.frozen_at && <p>ثبت تصمیم: {new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran" }).format(new Date(data.frozen_at))}</p>}
      {data.reference_date && <p>جلسهٔ مرجع: {data.reference_date}؛ آخرین مشاهده: {data.valued_at}</p>}
      {(data.skipped ?? []).map((p) => <p key={p.symbol}>{p.symbol}: {p.reason}</p>)}
    </details>
    <button onClick={onRefresh} className="text-xs text-indigo-600 dark:text-indigo-300">دریافت آخرین وضعیت ثبت‌شده</button>
  </div>;
}
