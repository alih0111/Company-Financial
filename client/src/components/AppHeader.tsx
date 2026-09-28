import React from "react";
import { FaBars, FaMoon, FaSun, FaUserCircle, FaShieldAlt } from "react-icons/fa";

interface AppHeaderProps {
  title: string;
  subtitle?: string;
  darkMode: boolean;
  toggleDarkMode: () => void;
  username: string | null;
  isAdmin: boolean;
  onMenuClick?: () => void;
}

const AppHeader: React.FC<AppHeaderProps> = ({
  title,
  subtitle,
  darkMode,
  toggleDarkMode,
  username,
  isAdmin,
  onMenuClick,
}) => {
  return (
    <header
      dir="rtl"
      className="sticky top-0 z-30 -mx-4 -mt-4 mb-4 px-4 py-3 bg-white/70 dark:bg-gray-800/70 backdrop-blur-xl border-b border-gray-200/70 dark:border-gray-700/50 flex items-center justify-between gap-3"
    >
      <div className="flex items-center gap-3 min-w-0">
        <button
          onClick={onMenuClick}
          aria-label="نمایش منو"
          className="lg:hidden flex items-center justify-center w-9 h-9 rounded-xl border border-gray-200 dark:border-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700/50 transition"
        >
          <FaBars />
        </button>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold tracking-widest text-emerald-600/80 dark:text-emerald-400/80 uppercase">
              RFA
            </span>
            <span className="text-gray-300 dark:text-gray-600">/</span>
            <h1 className="text-lg font-bold text-gray-800 dark:text-white truncate">
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
          className="flex items-center justify-center w-9 h-9 rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 text-gray-600 dark:text-gray-200 hover:scale-105 hover:shadow-md transition-all duration-200"
        >
          {darkMode ? (
            <FaSun className="text-amber-400" />
          ) : (
            <FaMoon className="text-emerald-600" />
          )}
        </button>

        <div className="hidden sm:flex items-center gap-2 pr-2 pl-3 h-9 rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50">
          <FaUserCircle className="text-gray-400 dark:text-gray-300" />
          <span className="text-sm font-medium text-gray-700 dark:text-gray-200">
            {username || "کاربر"}
          </span>
          {isAdmin && (
            <span
              title="ادمین"
              className="flex items-center gap-1 text-[10px] font-bold px-1.5 py-0.5 rounded-md bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
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
