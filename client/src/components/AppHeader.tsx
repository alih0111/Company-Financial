import React from "react";
import { FaBars, FaMoon, FaSun, FaShieldAlt } from "react-icons/fa";

interface AppHeaderProps {
  title: string;
  subtitle?: string;
  darkMode: boolean;
  toggleDarkMode: () => void;
  username: string | null;
  isAdmin: boolean;
  onMenuClick?: () => void;
  menuOpen?: boolean;
}

const AppHeader: React.FC<AppHeaderProps> = ({
  title,
  subtitle,
  darkMode,
  toggleDarkMode,
  username,
  isAdmin,
  onMenuClick,
  menuOpen = false,
}) => {
  return (
    <header
      dir="rtl"
      className="app-header relative z-30 shrink-0 px-4 sm:px-5 py-3 bg-white/90 dark:bg-[#0e1729]/95 border-b border-gray-200/70 dark:border-white/[0.06] flex items-center justify-between gap-3"
    >
      {/* خط گرادیانی تزئینی بالای هدر */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-l from-transparent via-emerald-500/40 to-transparent" />
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onMenuClick}
          aria-label="نمایش منو"
          aria-controls="app-sidebar"
          aria-expanded={menuOpen}
          className="lg:hidden shrink-0 flex items-center justify-center w-9 h-9 rounded-xl border border-gray-200 dark:border-white/10 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-white/5 transition"
        >
          <FaBars />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white text-[9px] font-black shadow-sm shadow-emerald-500/25">
              RFA
            </span>
            <h1 className="text-base sm:text-lg font-bold text-gray-800 dark:text-white truncate" title={title}>
              {title}
            </h1>
          </div>
          {subtitle && (
            <p className="text-xs text-gray-500 dark:text-gray-400 truncate mt-0.5">
              {subtitle}
            </p>
          )}
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        <button
          onClick={toggleDarkMode}
          aria-label={darkMode ? "حالت روشن" : "حالت تاریک"}
          className="flex items-center justify-center w-9 h-9 rounded-xl border border-gray-200 dark:border-white/10 bg-white/60 dark:bg-white/5 text-gray-600 dark:text-gray-200 hover:scale-110 hover:shadow-md transition-all duration-300 active:scale-95"
        >
          {darkMode ? (
            <FaSun className="text-amber-400" />
          ) : (
            <FaMoon className="text-emerald-600" />
          )}
        </button>

        <div className="hidden sm:flex items-center gap-2.5 pr-2 pl-3 h-9 max-w-52 rounded-xl border border-gray-200 dark:border-white/10 bg-white/60 dark:bg-white/5">
          <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white text-[10px] font-black shadow-sm">
            {(username || "ک").trim().charAt(0).toUpperCase()}
          </span>
          <span className="truncate text-sm font-medium text-gray-700 dark:text-gray-200" title={username || "کاربر"}>
            {username || "کاربر"}
          </span>
          {isAdmin && (
            <span
              title="ادمین"
              className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/20"
            >
              <FaShieldAlt size={9} /> ادمین
            </span>
          )}
        </div>
      </div>
    </header>
  );
};

export default AppHeader;
