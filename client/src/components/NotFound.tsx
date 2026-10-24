import { Link } from "react-router-dom";
import { FaChartLine, FaHome } from "react-icons/fa";

const NotFound = () => {
  return (
    <div
      className="relative flex flex-col items-center justify-center min-h-[60vh] text-center gap-4 animate-fade-in-up overflow-hidden"
      dir="rtl"
    >
      {/* پس‌زمینه‌ی تزئینی */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-grid-soft [mask-image:radial-gradient(ellipse_55%_55%_at_50%_45%,black,transparent)] opacity-70" />
        <div className="absolute -top-16 left-1/2 h-64 w-64 -translate-x-1/2 rounded-full bg-emerald-400/15 dark:bg-emerald-500/10 blur-3xl animate-aurora" />
      </div>

      {/* نمودار شناور تزئینی */}
      <div className="animate-float">
        <span className="flex items-center justify-center w-16 h-16 rounded-3xl bg-emerald-500/10 text-emerald-500 dark:text-emerald-400 text-2xl ring-1 ring-emerald-500/20 shadow-lg shadow-emerald-500/10">
          <FaChartLine />
        </span>
      </div>

      <h1 className="text-6xl font-black text-gradient-emerald tabular-nums">۴۰۴</h1>
      <p className="text-lg font-bold text-gray-800 dark:text-white">
        صفحه‌ای که دنبالش بودی پیدا نشد
      </p>
      <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm leading-6">
        ممکن است آدرس تغییر کرده باشد یا این بخش در دسترس شما نباشد.
      </p>
      <Link
        to="/dashboard"
        className="group mt-2 flex items-center gap-2 h-11 px-6 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-bold shadow-lg shadow-emerald-500/25 transition hover:scale-[1.03] hover:shadow-xl hover:shadow-emerald-500/30 active:scale-[0.99]"
      >
        <FaHome size={14} />
        بازگشت به داشبورد
      </Link>
    </div>
  );
};

export default NotFound;
