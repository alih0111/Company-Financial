type Gate = {
  status:string;v21_due_rows:number;v21_unique_due_dates:number;v21_unique_dates_with_any_exact_score:number;v21_unique_dates_without_any_exact_score:number;v21_missing_score_rows:number;sealed_score_dates:number;control_dates:number;control_dates_with_any_raw_mismatch:number;control_dates_with_rank_mismatch:number;score_mismatch_control_dates:Record<string,number>;top1_order_mismatch_control_dates:Record<string,number>;mismatch_fields:Record<string,{control_dates:number;cells:number}>;local_remedy:string;
};
export type V1222={run_id:string;status:string;gate:Gate;download_files:string[];browser_status:string};
const n=(x:unknown)=>Number(x??0).toLocaleString("fa-IR");
export default function ReturnV1222Section({data}:{data:V1222|null}){
 if(!data)return null;
 const download=(name:string)=><a key={name} className="underline" href={`${import.meta.env.BASE_URL}research/${name}`} download>{name.replace("return-v12-22-","")}</a>;
 const g=data.gate;
 return <section className="space-y-3 rounded-3xl border border-rose-300 bg-rose-50/60 p-4 sm:p-6 dark:border-rose-900 dark:bg-rose-950/20">
  <h2 className="text-xl font-bold">V12.22 — تشخیص و بازسازی محلی score</h2>
  <p className="text-sm leading-7">در V12.21، {n(g.v21_due_rows)} ردیف موعد به {n(g.v21_unique_due_dates)} تاریخ یکتا تعلق داشت؛ {n(g.v21_unique_dates_without_any_exact_score)} تاریخ یکتا هیچ score دقیقی برای دو نامزد نداشت. score مهرشده فقط برای {n(g.sealed_score_dates)} تاریخ ساخته شده بود. علت اولیه، ساخت پنل روی تاریخ‌های نمونه‌برداری‌شده بود.</p>
  <p className="rounded-xl border border-rose-400 p-3 text-sm font-semibold leading-7">بازسازی محلی از گیت تطبیق عبور نکرد: {n(g.control_dates_with_any_raw_mismatch)} از {n(g.control_dates)} کنترل در عوامل خام اختلاف داشت و ترتیب مقطعی در ۲ کنترل R1 و ۳ کنترل R3 عوض شد. NAV، بازده و مقایسه محاسبه نشد.</p>
  <p className="text-sm leading-7">عامل‌های اختلاف‌دار: میانگین ارزش معاملهٔ ۳۰روزه در ۳۸ تاریخ/۲۳۸ سلول، نوسان ۳۰روزه در ۱۶ تاریخ/۲۱ سلول، مومنتوم ۳۰روزه در ۲ تاریخ/۲ سلول. نسخهٔ خام قیمت تاریخی که V8 مصرف کرده بود فایل‌به‌فایل مهر نشده است؛ آرشیو محلی فعلی تطبیق دقیق را بازتولید نکرد. رفع محلی: بازیابی همان نسخهٔ آرشیو با SHA-256 و اجرای دوبارهٔ کنترل‌ها.</p>
  <div className="flex flex-wrap gap-3 text-xs">{data.download_files.map(download)}<a className="underline" href={`${import.meta.env.BASE_URL}research/return-v12-22.json`} download>خلاصهٔ کامل V12.22</a><a className="underline" href={`${import.meta.env.BASE_URL}research/return-v12-22-report.fa.md`} download>گزارش نهایی</a></div>
  <p className="text-xs">شبکه ۰ · کدال ۰ · DB ۰ · پیش‌فرض غربال ثابت · مصنوعات قبلی حفظ شدند · مرورگر اجرا نشد.</p>
 </section>;
}
