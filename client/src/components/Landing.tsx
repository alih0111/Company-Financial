import React from "react";
import { Link } from "react-router-dom";
import {
  FaChartLine,
  FaTable,
  FaBriefcase,
  FaUsers,
  FaShieldAlt,
  FaMoon,
  FaSun,
  FaArrowLeft,
  FaSignInAlt,
  FaBullseye,
  FaDatabase,
  FaLayerGroup,
  FaBolt,
} from "react-icons/fa";
import { getAuthStatus } from "../hooks/useGetUser";

interface LandingProps {
  darkMode: boolean;
  toggleDarkMode: () => void;
}

interface AccessCard {
  to: string;
  title: string;
  description: string;
  icon: React.ReactNode;
  gradient: string;
  ring: string;
  adminOnly?: boolean;
}

const AccessCard: React.FC<{ card: AccessCard; index: number }> = ({
  card,
  index,
}) => (
  <Link
    to={card.to}
    className="group relative flex flex-col gap-4 rounded-3xl border border-gray-200/70 dark:border-gray-700/50 bg-white/70 dark:bg-gray-800/40 backdrop-blur-xl p-6 shadow-lg shadow-emerald-500/5 hover:shadow-2xl hover:shadow-emerald-500/15 hover:-translate-y-1.5 transition-all duration-300 animate-fade-in-up"
    style={{ animationDelay: `${index * 90}ms` }}
  >
    <div
      className={`flex items-center justify-center w-14 h-14 rounded-2xl ring-1 ${card.ring} ${card.gradient} text-white text-2xl shadow-md transition-transform duration-300 group-hover:scale-110 group-hover:rotate-3`}
    >
      {card.icon}
    </div>
    <div>
      <h3 className="text-lg font-bold text-gray-800 dark:text-white">
        {card.title}
      </h3>
      <p className="mt-1 text-sm leading-6 text-gray-500 dark:text-gray-400">
        {card.description}
      </p>
    </div>
    <span className="mt-auto inline-flex items-center gap-2 text-sm font-semibold text-emerald-600 dark:text-emerald-400">
      ورود به بخش
      <FaArrowLeft className="transition-transform duration-300 group-hover:-translate-x-1" />
    </span>
  </Link>
);

const Landing: React.FC<LandingProps> = ({ darkMode, toggleDarkMode }) => {
  const { isAdmin, username } = getAuthStatus();
  const isLoggedIn = Boolean(username);

  const cards: AccessCard[] = [
    {
      to: "/dashboard",
      title: "داشبورد شرکت",
      description:
        "تحلیل بنیادی هر نماد: سود، فروش، امتیاز کوانت و نمودارهای تحلیلی.",
      icon: <FaChartLine />,
      gradient: "bg-gradient-to-br from-emerald-500 to-teal-600",
      ring: "ring-emerald-500/30",
    },
    {
      to: "/Table",
      title: "جدول داده",
      description:
        "غربال و مقایسهٔ تمام شرکت‌های بورسی در یک جدول جامع و قابل مرتب‌سازی.",
      icon: <FaTable />,
      gradient: "bg-gradient-to-br from-indigo-500 to-violet-600",
      ring: "ring-indigo-500/30",
    },
    {
      to: "/portfolio",
      title: "پورتفولیو",
      description:
        "مدیریت دارایی‌های سهامی، ترکیب سبد و ارزیابی عملکرد سرمایه‌گذاری.",
      icon: <FaBriefcase />,
      gradient: "bg-gradient-to-br from-amber-500 to-orange-600",
      ring: "ring-amber-500/30",
    },
    {
      to: "/assets",
      title: "دارایی خانواده",
      description:
        "سبد اشخاص، قیمت‌ها و اتصال کارگزاری برای مدیریت یکپارچهٔ دارایی‌ها.",
      icon: <FaUsers />,
      gradient: "bg-gradient-to-br from-fuchsia-500 to-purple-600",
      ring: "ring-fuchsia-500/30",
      adminOnly: true,
    },
  ];

  const visibleCards = cards.filter((c) => !c.adminOnly || isAdmin);

  const stats = [
    { label: "شرکت‌های پوشش‌داده‌شده", value: "۲۷۳", icon: <FaDatabase /> },
    { label: "امتیازدهی بنیادی", value: "PIT-safe", icon: <FaBullseye /> },
    { label: "فاکتورهای مدل", value: "+۵٬۰۰۰", icon: <FaLayerGroup /> },
    { label: "به‌روزرسانی داده", value: "خودکار", icon: <FaBolt /> },
  ];

  return (
    <div dir="rtl" className="relative min-h-screen overflow-hidden">
      {/* ── Decorative background ── */}
      <div className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -top-32 -right-24 h-96 w-96 rounded-full bg-emerald-400/20 dark:bg-emerald-500/10 blur-3xl animate-float" />
        <div
          className="absolute top-40 -left-24 h-96 w-96 rounded-full bg-teal-400/20 dark:bg-teal-500/10 blur-3xl animate-float"
          style={{ animationDelay: "1.2s" }}
        />
        <div
          className="absolute bottom-0 left-1/3 h-80 w-80 rounded-full bg-indigo-400/10 dark:bg-indigo-500/10 blur-3xl animate-float"
          style={{ animationDelay: "0.6s" }}
        />
      </div>

      {/* ── Top Navigation ── */}
      <header className="relative z-20 mx-auto flex max-w-7xl items-center justify-between px-6 py-5">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lg shadow-emerald-500/25 text-xl">
            <FaChartLine />
          </div>
          <div className="leading-tight">
            <p className="text-[11px] font-semibold uppercase tracking-widest text-emerald-600/80 dark:text-emerald-400/80">
              RFA
            </p>
            <h1 className="text-lg font-bold text-gray-800 dark:text-white">
              بینش شرکت‌ها
            </h1>
          </div>
        </div>

        <div className="flex items-center gap-2 sm:gap-3">
          <button
            onClick={toggleDarkMode}
            aria-label={darkMode ? "حالت روشن" : "حالت تاریک"}
            className="flex h-10 w-10 items-center justify-center rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 text-gray-600 dark:text-gray-200 transition hover:scale-105 hover:shadow-md"
          >
            {darkMode ? (
              <FaSun className="text-amber-400" />
            ) : (
              <FaMoon className="text-emerald-600" />
            )}
          </button>

          {isLoggedIn ? (
            <Link
              to="/dashboard"
              className="flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/20 transition hover:scale-[1.03] hover:shadow-lg"
            >
              <FaChartLine size={12} />
              {username || "داشبورد"}
            </Link>
          ) : (
            <>
              <Link
                to="/register"
                className="hidden h-10 items-center rounded-xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-700/50 px-4 text-sm font-semibold text-gray-700 dark:text-gray-200 transition hover:scale-[1.03] hover:shadow-md sm:flex"
              >
                ثبت‌نام
              </Link>
              <Link
                to="/login"
                className="flex h-10 items-center gap-2 rounded-xl bg-gradient-to-r from-emerald-500 to-teal-600 px-4 text-sm font-semibold text-white shadow-md shadow-emerald-500/20 transition hover:scale-[1.03] hover:shadow-lg"
              >
                <FaSignInAlt size={12} />
                ورود
              </Link>
            </>
          )}
        </div>
      </header>

      {/* ── Hero ── */}
      <section className="relative z-10 mx-auto max-w-7xl px-6 pt-10 pb-16 text-center sm:pt-16">
        <span className="animate-fade-in-up inline-flex items-center gap-2 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-4 py-1.5 text-xs font-semibold text-emerald-700 dark:text-emerald-300">
          <FaShieldAlt size={11} />
          سامانهٔ بنیادی و کوانت شرکت‌های بورسی
        </span>

        <h2
          className="animate-fade-in-up mx-auto mt-6 max-w-4xl text-4xl font-black leading-tight text-gray-800 dark:text-white sm:text-5xl md:text-6xl"
          style={{ animationDelay: "80ms" }}
        >
          تصمیم‌های سرمایه‌گذاری،
          <span className="text-gradient-emerald"> هوشمندتر و مستندتر</span>
        </h2>

        <p
          className="animate-fade-in-up mx-auto mt-6 max-w-2xl text-base leading-8 text-gray-500 dark:text-gray-400 sm:text-lg"
          style={{ animationDelay: "160ms" }}
        >
          داده‌های بنیادی، صورت‌های مالی و قیمت بازار را یکپارچه می‌کنیم و با
          مدل امتیازدهی نسخه‌دار و PIT-safe، تصویری شفاف از عملکرد هر شرکت به شما
          می‌دهیم.
        </p>

        <div
          className="animate-fade-in-up mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row"
          style={{ animationDelay: "240ms" }}
        >
          <Link
            to={isLoggedIn ? "/dashboard" : "/login"}
            className="group flex h-12 w-full items-center justify-center gap-2 rounded-2xl bg-gradient-to-r from-emerald-500 to-teal-600 px-8 text-base font-bold text-white shadow-lg shadow-emerald-500/25 transition hover:scale-[1.03] hover:shadow-xl hover:shadow-emerald-500/30 sm:w-auto"
          >
            {isLoggedIn ? "ورود به داشبورد" : "ورود به سیستم"}
            <FaArrowLeft className="transition-transform duration-300 group-hover:-translate-x-1" />
          </Link>
          <a
            href="#access"
            className="flex h-12 w-full items-center justify-center gap-2 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white/70 dark:bg-gray-800/40 px-8 text-base font-semibold text-gray-700 dark:text-gray-200 backdrop-blur transition hover:scale-[1.03] hover:shadow-md sm:w-auto"
          >
            مشاهدهٔ بخش‌ها
          </a>
        </div>

        {/* ── Stats bar ── */}
        <div
          className="animate-fade-in-up mx-auto mt-16 grid max-w-4xl grid-cols-2 gap-3 sm:grid-cols-4"
          style={{ animationDelay: "320ms" }}
        >
          {stats.map((s) => (
            <div
              key={s.label}
              className="flex flex-col items-center gap-2 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-800/40 px-4 py-5 backdrop-blur-xl shadow-sm"
            >
              <span className="text-xl text-emerald-600 dark:text-emerald-400">
                {s.icon}
              </span>
              <span className="text-xl font-black tabular-nums text-gray-800 dark:text-white">
                {s.value}
              </span>
              <span className="text-[11px] font-medium text-gray-500 dark:text-gray-400 text-center">
                {s.label}
              </span>
            </div>
          ))}
        </div>
      </section>

      {/* ── Access cards ── */}
      <section id="access" className="relative z-10 mx-auto max-w-7xl px-6 pb-20">
        <div className="mb-8 text-center">
          <h3 className="text-2xl font-bold text-gray-800 dark:text-white sm:text-3xl">
            به کجا می‌خواهید بروید؟
          </h3>
          <p className="mt-2 text-sm text-gray-500 dark:text-gray-400">
            یکی از بخش‌ها را انتخاب کنید و مستقیم وارد شوید.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4">
          {visibleCards.map((card, i) => (
            <AccessCard key={card.to} card={card} index={i} />
          ))}
        </div>
      </section>

      {/* ── Footer ── */}
      <footer className="relative z-10 border-t border-gray-200/70 dark:border-gray-700/50">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-3 px-6 py-8 text-center sm:flex-row sm:text-right">
          <p className="text-sm text-gray-500 dark:text-gray-400">
            RFA — سامانهٔ تحلیل بنیادی و کوانت شرکت‌های بورسی
          </p>
          <p className="text-xs text-gray-400 dark:text-gray-500">
            داده‌ها به‌صورت نسخه‌دار و قابل ردیابی محاسبه می‌شوند.
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Landing;
