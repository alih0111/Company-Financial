const files = [
  ["گزارش نهایی فارسی", "return-v12-25-report.fa.md"],
  ["دفتر تصمیم‌ها، رتبه، امتیاز و عوامل", "return-v12-25-decision-dossier.csv"],
  ["دفتر fillها و تطبیق قیمت/هویت نماد", "return-v12-25-trade-price-audit.csv"],
  ["دسترسی تاریخی؛ جهان و نمادهای منتخب", "return-v12-25-financial-access-summary.csv"],
  ["جزئیات ورودی مالی و timestamp منابع", "return-v12-25-financial-access-detail.csv"],
  ["جهش‌های بیش از ۲۵٪ هنگام نگهداری", "return-v12-25-held-jumps.csv"],
  ["بررسی رویداد شرکتی سپیدار، ساروم و دفرا", "return-v12-25-corporate-action-review.csv"],
  ["دفتر مستقل سود هر نماد", "return-v12-25-symbol-ledger.csv"],
  ["آشتی مستقل سود و NAV", "return-v12-25-nav-reconciliation.csv"],
  ["مشارکت نمادهای دارای ابهام داده", "return-v12-25-ambiguity-exposure.csv"],
  ["خلاصهٔ اجرا و محدودیت‌ها", "return-v12-25-summary.json"],
  ["manifest و hash منابع", "return-v12-25-manifest.json"],
];

export default function ReturnV1225Section() {
  const href = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
  return <section className="space-y-3 rounded-3xl border border-amber-300 bg-amber-50/60 p-4 sm:p-6 dark:border-amber-900 dark:bg-amber-950/20">
    <h2 className="text-xl font-bold">V12.25 — ممیزی اعتبار سود P1/O00</h2>
    <p className="text-sm leading-7">NAV منجمد ۱٬۲۳۰٬۰۲۷٬۱۰۹ تومان از نظر حسابداری مستقل تأیید شد: ۳۵ fill، تطبیق کامل open تعدیل‌شده و هویت نماد، و اختلاف کمتر از یک میکروتومان در آشتی FIFO تا NAV. این، اعتبار اقتصادی مستقل را ثابت نمی‌کند؛ زمان دسترسی واقعی به دادهٔ خام و علت جهش تعدیل‌شدهٔ غگیلا در cache محلی تأیید نشده‌اند.</p>
    <p className="text-sm leading-7">در نخستین انتخاب، snapshot هیچ عامل مالی غیرخالی برای نماد رتبه‌اول نداشت. یک جهش غگیلا در ۱۴۰۰/۰۲/۲۹ برابر +۴۱٫۶۳٪ و اثر mark آن روز حدود +۳۹٫۹۴ میلیون تومان بود؛ شاهد رویداد شرکتی موجود نیست. سپیدار، ساروم و دفرا جداگانه ممیزی شدند و جهش بالای ۲۵٪ هنگام نگهداری نداشتند. بازده اصلاح‌شده ساخته نشد.</p>
    <p className="text-sm leading-7">هیچ خطای پیاده‌سازی یا حسابداری مستند پیدا نشد. سود تحقق‌یافتهٔ FIFO حدود ۱٫۳۳۰ میلیارد و سود/زیان تحقق‌نیافتهٔ زکشت حدود ‎−۲۰۰٫۰۳۷ میلیون تومان است؛ کارمزد کل ۷۹٫۵۹۹ میلیون تومان.</p>
    <div className="flex flex-wrap gap-3 text-xs">{files.map(([label, name]) => <a key={name} className="underline" href={href(name)} download>{label}</a>)}</div>
    <p className="text-xs">فقط مصنوعات منجمد V12.23 · شبکه ۰ · کدال ۰ · DB ۰ · نصب بسته ۰ · وزن، تقویم، غربال و خروجی‌های قبلی ثابت ماندند.</p>
  </section>;
}
