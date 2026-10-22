const files = [
  ["جدول مشترک ۱۰ روش در افق‌های ۱۲۶ و ۲۵۲", "return-v12-24-ten-method-summary.csv"],
  ["تفکیک اثر وزن و تقویم", "return-v12-24-weight-calendar-effects.csv"],
  ["اثر dataset؛ شامل هشت NAV پیوستهٔ قدیم/تازه", "return-v12-24-dataset-change.csv"],
  ["گزارش کامل فارسی", "return-v12-24-report.fa.md"],
  ["فایل خلاصهٔ اجرا", "return-v12-24-summary.json"],
];

export default function ReturnV1224Section() {
  const href = (name: string) => `${import.meta.env.BASE_URL}research/${name}`;
  return <section className="space-y-3 rounded-3xl border border-violet-300 bg-violet-50/60 p-4 sm:p-6 dark:border-violet-900 dark:bg-violet-950/20">
    <h2 className="text-xl font-bold">V12.24 — جمع‌بندی frozen V12.23</h2>
    <p className="text-sm leading-7">این خلاصه فقط از خروجی‌های ذخیره‌شدهٔ V12.23 ساخته شده است. همهٔ ۱۰ روش در هر افق روی {"۵۳ شروع مشترک (۱۲۶ جلسه) و ۴۷ شروع مشترک (۲۵۲ جلسه)"} سنجیده شدند. بالاترین NAV پیوستهٔ تاریخی میان P1 در تقویم شخصی R1 و P1 در فاز جهانی ۰ مشترک بود: حدود ۱٫۲۳۰ میلیارد تومان تا ۱۴۰۴/۱۲/۰۵.</p>
    <p className="text-sm leading-7">میانهٔ سرمایهٔ پایان شروع‌های ماهانه در هر دو افق برای P1/O00 بالاترین بود؛ نتیجهٔ جفت‌شده با تغییر فاز عوض می‌شود. برای نمونه، میانهٔ R1−P1/O00 در افق ۱۲۶ منفی و در برابر P1/O42 مثبت است؛ در افق ۲۵۲ نیز R1−P1/O42 مثبت و R1−P1/O00 منفی است. اثر وزن جداگانه و به‌صورت جفت‌شده در تقویم یکسان گزارش شده است.</p>
    <p className="text-sm font-semibold leading-7">هیچ روشی در معیارهای مختلف برتری سازگار ندارد؛ نتیجه به افق، تقویم و معیار وابسته است.</p>
    <p className="text-sm leading-7">P2: <strong>نتیجهٔ اجرای قبلی؛ در V12.23 بازآزمایی نشده</strong>.</p>
    <div className="flex flex-wrap gap-3 text-xs">{files.map(([label, name]) => <a key={name} className="underline" href={href(name)} download>{label}</a>)}</div>
    <p className="text-xs">آفلاین و فقط از خروجی منجمد · وزن‌ها، تقویم‌ها و پیش‌فرض غربال ثابت · شبکه ۰ · کدال ۰ · DB ۰ · نصب بسته ۰. ممیزی false negative و آزمون‌های رگرسیون در گزارش آمده‌اند.</p>
  </section>;
}
