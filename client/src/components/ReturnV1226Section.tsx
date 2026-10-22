const files: Array<[string, string]> = [
  ["خلاصهٔ ۱۲ روش و ۲ افق", "return-v12-26-summary-12-methods.csv"],
  ["مقایسه‌های جفت‌شده و اثر وزن", "return-v12-26-paired-comparisons.csv"],
  ["تمام مسیرهای ماهانه و پیوسته", "return-v12-26-all-routes.csv"],
  ["دفتر روزانهٔ NAV", "return-v12-26-daily-nav.csv"],
  ["تصمیم‌ها و رتبه‌ها", "return-v12-26-decisions.csv"],
  ["معاملات و کارمزدها", "return-v12-26-trades.csv"],
  ["مشارکت نمادها", "return-v12-26-symbol-contributions.csv"],
  ["دفتر مستقل cash/units/fees/NAV", "return-v12-26-independent-ledger.csv"],
  ["جدول سالانهٔ ۱۲ مسیر پیوسته", "return-v12-26-continuous-annual.csv"],
  ["هشت نمونهٔ قفل‌شده و معاملاتشان", "return-v12-26-selected-samples.csv"],
  ["مشارکت نماد در نمونه‌ها", "return-v12-26-selected-sample-contributions.csv"],
  ["دفتر معاملات نمونه‌ها", "return-v12-26-selected-sample-trades.csv"],
  ["تصمیم‌های سه قاعده در مسیر P1/O00", "return-v12-26-p1-eligibility-comparison.csv"],
  ["پوشش مالی هنگام خرید P1/O00", "return-v12-26-p1-buy-coverage.csv"],
  ["ثبت همهٔ موعدهای پوشش", "return-v12-26-coverage-due-dates.csv"],
  ["پنل کامل پوشش فشرده‌شده", "return-v12-26-coverage-panel.csv.gz"],
  ["گیت پوشش و بازتولید score", "return-v12-26-coverage-gate.json"],
  ["گیت کنترل‌های G0", "return-v12-26-G0-control-gate.json"],
  ["اعتبارسنجی نهایی", "return-v12-26-validation.json"],
  ["ثبت رخدادهای اجرای ممیزی", "return-v12-26-execution-incidents.csv"],
  ["قرارداد قفل‌شده", "return-v12-26-locked-contract.json"],
  ["هش قرارداد", "return-v12-26-locked-contract.sha256"],
  ["manifest و هش مصنوعات", "return-v12-26-delivery-manifest.json"],
  ["گزارش نهایی", "return-v12-26-report.fa.md"],
  ["تحویل و روش بازتولید", "return-v12-26-handoff.fa.md"],
];

export default function ReturnV1226Section() {
  const href = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
  return <section className="space-y-4 rounded-3xl border border-indigo-300 bg-indigo-50/60 p-4 sm:p-6 dark:border-indigo-900 dark:bg-indigo-950/20">
    <h2 className="text-xl font-bold">V12.26 — ممیزی صلاحیت مالی و پایداری P1/O00</h2>
    <p className="text-sm leading-7">در همان مجموعهٔ منجمد V12.23، ۱۲ بازوی ازپیش‌قفل‌شده روی ۶۰ شروع و افق‌های ۱۲۶ و ۲۵۲ جلسه بررسی شدند. گیت پوشش پیش از NAV عبور کرد: ۴٬۲۵۴ موعد لازم، صفر امتیاز مفقود و خطای بازسازی حداکثر ۱٫۴۳×۱۰⁻¹⁴. چهار خانوادهٔ کنترل G0 در ۴۰۴ مسیر، از جمله مسیرهای پیوسته، با صفر شکست و اختلاف NAV کمتر از یک تومان بازتولید شدند.</p>
    <p className="text-sm leading-7">در مسیر پیوستهٔ valuation_0/O00، NAV تاریخی G0 برابر ۱٬۲۳۰٬۰۲۷٬۱۰۹ تومان بود. G1 به ۱٬۰۹۵٬۱۳۱٬۳۰۵ و G50 به ۹۵۱٬۰۷۱٬۶۲۴ تومان رسیدند. بنابراین جلوگیری از خریدهای فاقد حداقل پوشش، سود تاریخی P1 را در این مسیر حفظ نکرد؛ این اختلاف اثر علّی دادهٔ ناقص نیست، چون فیلتر انتخاب‌ها و ترکیب سرمایه را تغییر می‌دهد.</p>
    <p className="text-sm leading-7">در شروع‌های ماهانه، میانهٔ valuation_0/O00/G0 برابر ۱۲۷٫۰۳ میلیون در افق ۱۲۶ و ۱۷۹٫۵۱ میلیون در افق ۲۵۲ بود. تغییر به G1 یا G50 میانهٔ جفت‌شده را بهبود نداد؛ با این حال، نتایج به تقویم حساس‌اند و برتری یک قاعده در همهٔ افق‌ها و شروع‌ها دیده نشد. بالاترین NAV پیوسته متعلق به G0 است (۱٫۲۳۰ میلیارد تومان)؛ بیشترین NAV میان مسیرهای ماهانه در افق ۲۵۲، w0/O00/G0 با ۳۸۸٫۷۳ میلیون تومان بود. در افق ۱۲۶، میانهٔ بالاتر در valuation_0/O00/G0 (۱۲۷٫۰۳ میلیون) دیده شد؛ در افق ۲۵۲ میانهٔ بالای valuation_0/O00 میان سه قاعده برابر بود (۱۷۹٫۵۱ میلیون). این‌ها برندگان تاریخی همین شروع‌ها هستند.</p>
    <div className="flex flex-wrap gap-3 text-xs">{files.map(([label, name]) => <a key={name} className="underline" href={href(name)} download>{label}</a>)}</div>
    <p className="text-xs leading-6">دادهٔ محلی تا ۱۴۰۴/۱۲/۰۵ · وزن و تقویم ثابت · غربال و خروجی‌های قبلی حفظ شدند · شبکه=۰ · کدال=۰ · DB=۰ · نصب بسته=۰ · این بازآزمایی گذشته‌نگر است و آزمون مستقل آینده نیست.</p>
  </section>;
}
