const files = [
  ["مقایسهٔ جفت‌شدهٔ شخصی، جهانی و ترکیبی", "return-v12-23-personal-global-composite.csv"],
  ["خلاصهٔ R1 در برابر R3", "return-v12-23-R1-R3-summary.csv"],
  ["شروع‌های جفت‌شدهٔ R1/R3", "return-v12-23-R1-R3-starts.csv"],
  ["بازده سالانهٔ مسیرهای پیوسته", "return-v12-23-continuous-annual.csv"],
  ["اثر تغییر dataset", "return-v12-23-dataset-change.csv"],
  ["هشت نمونهٔ حدی", "return-v12-23-extreme-examples.csv"],
  ["معاملات نمونه‌ها", "return-v12-23-extreme-trades.csv"],
  ["مشارکت نمادها در نمونه‌ها", "return-v12-23-extreme-symbol-contributions.csv"],
  ["NAV روزانهٔ نمونه‌ها", "return-v12-23-extreme-daily-nav.csv"],
  ["قرارداد قفل‌شده", "return-v12-23-contract.json"],
  ["گزارش نهایی فارسی", "return-v12-23-report.fa.md"],
];

export default function ReturnV1223Section() {
  const href = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
  return <section className="space-y-3 rounded-3xl border border-sky-300 bg-sky-50/60 p-4 sm:p-6 dark:border-sky-900 dark:bg-sky-950/20">
    <h2 className="text-xl font-bold">V12.23 — dataset تازه؛ قابل مقایسه درون همین اجرا</h2>
    <p className="text-sm leading-7">گیت مجموعه و پوشش مسیرها PASS شد. ۲۵۰ تاریخ score برای cohort برابر ۲۵۴ نماد بازسازی شد. در ۸۹ کنترل مهرشده، ۳۸ تاریخ اختلاف عامل خام داشتند (۲۳۸ سلول ارزش معامله، ۲۱ نوسان و ۲ مومنتوم)؛ وضعیت V12.22 همچنان <strong>RECONSTRUCTION_MISMATCH</strong> است.</p>
    <p className="text-sm leading-7">در R1 در برابر R3، افق ۱۲۶ جلسه: ۵۳ شروع، ۲۵ برد / ۲۷ باخت / ۱ مساوی، میانهٔ اختلاف −۱٬۸۹۸٬۹۵۲ تومان. افق ۲۵۲: ۴۷ شروع، ۱۹ برد / ۲۸ باخت / بدون مساوی، میانه −۸٬۳۹۲٬۰۷۲ تومان. برتری تقویم شخصی یک‌سویه و تکرارپذیر نبود. جدول‌های پیوسته شامل ۵۰ ردیف سالانهٔ تاریخ‌دارند.</p>
    <div className="flex flex-wrap gap-3 text-xs">{files.map(([label, name]) => <a key={name} className="underline" href={href(name)} download>{label}</a>)}<a className="underline" href={href("return-v12-23.json")} download>خلاصهٔ اجرا</a><a className="underline" href={href("return-v12-23-execution.fa.md")} download>برنامهٔ اجرا</a></div>
    <p className="text-xs">خط مبنای تاریخی تازه · وزن‌ها و پیش‌فرض غربال ثابت · شبکه ۰ · کدال ۰ · DB ۰ · نصب بسته ۰ · وضعیت V12.22 حفظ شد.</p>
  </section>;
}
