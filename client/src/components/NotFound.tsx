import { Link } from "react-router-dom";
import { FaChartLine, FaHome } from "react-icons/fa";

const NotFound = () => {
  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh] text-center gap-4 animate-fade-in-up" dir="rtl">
      <span className="flex items-center justify-center w-16 h-16 rounded-3xl bg-emerald-500/10 text-emerald-500 text-2xl ring-1 ring-emerald-500/20">
        <FaChartLine />
      </span>
      <h1 className="text-6xl font-black text-gradient-emerald tabular-nums">۴۰۴</h1>
      <p className="text-lg font-bold text-gray-800 dark:text-white">
        صفحه‌ای که دنبالش بودی پیدا نشد
      </p>
      <p className="text-sm text-gray-500 dark:text-gray-400 max-w-sm">
        ممکن است آدرس تغییر کرده باشد یا این بخش در دسترس شما نباشد.
      </p>
      <Link
        to="/dashboard"
        className="flex items-center gap-2 h-11 px-6 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-600 text-white font-bold shadow-lg shadow-emerald-500/25 transition hover:scale-[1.03] hover:shadow-xl"
      >
        <FaHome size={14} />
        بازگشت به داشبورد
      </Link>
    </div>
  );
};

export default NotFound;
