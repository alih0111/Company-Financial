import React from "react";
import { FaChartLine, FaMoon, FaSun } from "react-icons/fa";

type Props = {
  darkMode: boolean;
  toggleDarkMode: () => void;
  children: React.ReactNode;
};

// قالب مشترک صفحه‌های ورود / ثبت‌نام — کارت شیشه‌ای روی پس‌زمینه‌ی Aurora
const AuthLayout: React.FC<Props> = ({ darkMode, toggleDarkMode, children }) => {
  return (
    <div dir="rtl" className="relative min-h-screen flex items-center justify-center overflow-hidden px-4 py-10">
      {/* پس‌زمینه */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute inset-0 bg-grid-soft [mask-image:radial-gradient(ellipse_60%_60%_at_50%_40%,black,transparent)]" />
        <div className="absolute -top-32 -right-24 h-96 w-96 rounded-full bg-emerald-400/20 dark:bg-emerald-500/10 blur-3xl animate-aurora" />
        <div
          className="absolute -bottom-32 -left-24 h-96 w-96 rounded-full bg-teal-400/20 dark:bg-teal-500/10 blur-3xl animate-aurora"
          style={{ animationDelay: "1.2s" }}
        />
        <div
          className="absolute top-1/3 left-1/4 h-72 w-72 rounded-full bg-indigo-400/10 dark:bg-indigo-500/10 blur-3xl animate-aurora"
          style={{ animationDelay: "0.6s" }}
        />
      </div>

      {/* دکمه‌ی تم */}
      <button
        onClick={toggleDarkMode}
        aria-label={darkMode ? "حالت روشن" : "حالت تاریک"}
        className="absolute top-5 left-5 flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 text-gray-600 dark:text-gray-200 backdrop-blur transition hover:scale-105 hover:shadow-md"
      >
        {darkMode ? <FaSun className="text-amber-400" /> : <FaMoon className="text-emerald-600" />}
      </button>

      <div className="w-full max-w-md animate-scale-in">
        {/* لوگو */}
        <div className="mb-6 flex flex-col items-center gap-3">
          <div className="flex h-14 w-14 items-center justify-center rounded-3xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-xl shadow-emerald-500/25 text-2xl animate-float">
            <FaChartLine />
          </div>
          <div className="text-center leading-tight">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-emerald-600/80 dark:text-emerald-400/80">
              RFA
            </p>
            <h2 className="text-xl font-bold text-gray-800 dark:text-white">بینش شرکت‌ها</h2>
          </div>
        </div>

        {/* کارت شیشه‌ای */}
        <div className="rounded-3xl border border-gray-200/70 dark:border-gray-700/50 bg-white/80 dark:bg-gray-800/70 backdrop-blur-xl shadow-2xl shadow-emerald-500/10 p-7">
          {children}
        </div>

        <p className="mt-5 text-center text-[11px] text-gray-400 dark:text-gray-500">
          سامانهٔ تحلیل بنیادی و کوانت شرکت‌های بورسی
        </p>
      </div>
    </div>
  );
};

export default AuthLayout;
