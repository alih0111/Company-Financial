import { logoutSession } from "../hooks/useGetUser";
import { errorMessage } from "../utils/errorMessage";
import React, { useEffect, useRef, useState } from "react";
import Select from "react-select";
import { NavLink, useLocation } from "react-router-dom";
import {
  FaChartLine,
  FaChartPie,
  FaUsers,
  FaCoins,
  FaSyncAlt,
  FaBolt,
  FaDownload,
  FaBalanceScale,
  FaSignOutAlt,
  FaShieldAlt,
  FaArrowRight,
  FaTable,
  FaRobot,
} from "react-icons/fa";
import QuickSyncModal from "./QuickSyncModal";
import SymbolSyncModal from "./SymbolSyncModal";
import { useDarkMode } from "../utils/theme";
import {
  addViewedItem,
  collectBrsPrices,
} from "../utils/api";

interface SidebarProps {
  companyOptions: { value: string; label: string }[];
  selectedCompany: string;
  onCompanyChange: (val: string) => void;

  loadingCompanies: boolean;
  onCompanySearchOpen: () => void;
  profitReviewOpen: boolean;
  onProfitReviewToggle: () => void;
  codalWaitingCaptcha: boolean;
  isAdmin: boolean;
  username: string | null;
  open?: boolean;
  onClose?: () => void;
  onDataCollected?: () => void;
  companyProfits: {
    company_name: string;
    eps_growth: number;
    priceScore: number;
    sales_growth: number;
  }[];
}

// منوی ناوبری اصلی — «دارایی خانواده» فقط برای ادمین
const NAV_ITEMS: {
  to: string;
  label: string;
  icon: React.ReactNode;
  adminOnly?: boolean;
}[] = [
  { to:"/admin/data-access",label:"دسترسی دادهٔ کاربران",icon:<FaShieldAlt size={13}/>,adminOnly:true },
  { to: "/dashboard", label: "داشبورد شرکت", icon: <FaChartLine size={13} /> },
  // { to: "/market", label: "بازار و طلا", icon: <FaGlobe size={13} /> },
  // { to: "/compare", label: "مقایسه و نسبت", icon: <FaBalanceScale size={13} /> },
  // { to: "/watchlist", label: "دیده‌بان", icon: <FaEye size={13} /> },
  { to: "/Table", label: "غربال بازار", icon: <FaTable size={13} /> },
  // { to: "/ranking", label: "رتبه‌بندی", icon: <FaFlask size={13} /> },
  { to: "/strategy", label: "FactorMix · ماهانه ۱۵", icon: <FaChartPie size={13} /> },
  {
    to: "/strategy/performance",
    label: "عملکرد سبد استراتژی",
    icon: <FaChartLine size={13} />,
  },
  { to: "/chat", label: "دستیار سرمایه‌گذاری", icon: <FaRobot size={13} /> },
  // { to: "/portfolio", label: "پورتفولیو", icon: <FaBriefcase size={13} /> },
  {
    to: "/assets",
    label: "دارایی خانواده",
    icon: <FaUsers size={13} />,
    adminOnly: true,
  },
];

const Sidebar: React.FC<SidebarProps> = ({
  companyOptions,
  selectedCompany,
  onCompanyChange,
  loadingCompanies,
  onCompanySearchOpen,
  profitReviewOpen,
  onProfitReviewToggle,
  codalWaitingCaptcha,
  companyProfits,
  isAdmin,
  username,
  open = false,
  onClose,
  onDataCollected,
}) => {
  const location = useLocation();
  const [logoutError, setLogoutError] = useState("");
  const [loggingOut, setLoggingOut] = useState(false);
  const isRankingPath = [
    "/ranking",
    "/qvt",
    "/ranking/research",
    "/ranking/research/v12-1",
  ].includes(location.pathname);
  const [toolsOpen, setToolsOpen] = useState(false);
  const sidebarRef = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!open || window.matchMedia("(min-width: 1024px)").matches) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    const sidebar = sidebarRef.current;
    const focusable = () => Array.from(sidebar?.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), [tabindex="0"]',
    ) ?? []).filter((element) => element.getClientRects().length > 0);
    focusable()[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose?.();
      if (event.key !== "Tab") return;
      const elements = focusable();
      const first = elements[0];
      const last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previousFocus?.focus({ preventScroll: true });
    };
  }, [open, onClose]);
  const [loadingBrsDaily, setLoadingBrsDaily] = useState(false);
  const [loadingBrsBackfill, setLoadingBrsBackfill] = useState(false);
  const [loadingBrsSync, setLoadingBrsSync] = useState(false);
  const [brsMsg, setBrsMsg] = useState<string | null>(null);
  const [quickSyncOpen, setQuickSyncOpen] = useState(false);
  const [quickSyncing, setQuickSyncing] = useState(false);
  // جمع‌آوری سود/فروش per-symbol — مودال با تعداد گزارش دلخواه
  const [symbolSync, setSymbolSync] = useState<"financial" | "monthly" | null>(
    null,
  );
  const [loadingCompanyPrices, setLoadingCompanyPrices] = useState(false);
  const [toolsMsg, setToolsMsg] = useState<{
    kind: "ok" | "err";
    text: string;
  } | null>(null);
  const { darkMode } = useDarkMode();

  // جمع‌آوری تاریخچه‌ی قیمت نماد انتخاب‌شده از BRS
  const runCompanyPrices = async () => {
    if (!selectedCompany || loadingCompanyPrices) return;
    setLoadingCompanyPrices(true);
    setToolsMsg(null);
    try {
      await collectBrsPrices("backfill", {
        symbol: selectedCompany,
        force: true,
      });
      setToolsMsg({
        kind: "ok",
        text: `تاریخچه‌ی قیمت «${selectedCompany}» کامل شد ✓`,
      });
      onDataCollected?.();
    } catch (e: unknown) {
      setToolsMsg({
        kind: "err",
        text: errorMessage(e, "خطا در جمع‌آوری قیمت"),
      });
    } finally {
      setLoadingCompanyPrices(false);
    }
  };

  const runBrsDaily = async () => {
    setLoadingBrsDaily(true);
    setBrsMsg(null);
    try {
      await collectBrsPrices("daily");
      setBrsMsg("قیمت روزانه ذخیره شد ✓");
      onDataCollected?.();
    } catch (e: unknown) {
      setBrsMsg(errorMessage(e, "خطا در دریافت قیمت"));
    } finally {
      setLoadingBrsDaily(false);
    }
  };

  const runBrsBackfill = async () => {
    setLoadingBrsBackfill(true);
    setBrsMsg(null);
    try {
      await collectBrsPrices("backfill");
      setBrsMsg("تاریخچه قیمت به‌روزرسانی شد ✓");
      onDataCollected?.();
    } catch (e: unknown) {
      setBrsMsg(errorMessage(e, "خطا در backfill"));
    } finally {
      setLoadingBrsBackfill(false);
    }
  };

  const runBrsSync = async () => {
    setLoadingBrsSync(true);
    setBrsMsg(null);
    try {
      await collectBrsPrices("sync", { limit: 30, threshold: 20 });
      setBrsMsg("تعدیل قیمت‌ها انجام شد ✓");
      onDataCollected?.();
    } catch (e: unknown) {
      setBrsMsg(errorMessage(e, "خطا در sync"));
    } finally {
      setLoadingBrsSync(false);
    }
  };

  const handleCompanySelect = async (companyName: string) => {
    try {
      await addViewedItem(companyName);
    } catch (err) {
      console.error("Failed to save viewed item:", err);
    }

    onCompanyChange(companyName);
  };

  return (
    <>
    <aside
      ref={sidebarRef}
      id="app-sidebar"
      aria-label="منوی اصلی"
      className={`theme-transition fixed right-0 top-0 z-40 h-dvh w-72 max-w-[calc(100vw-32px)] shrink-0 p-5 overflow-hidden bg-white dark:bg-[#101a2f] shadow-xl shadow-gray-900/5 border-l border-gray-200/80 dark:border-white/[0.06] flex flex-col gap-3 transition-transform duration-300 ease-out-expo lg:static lg:h-full lg:w-64 xl:w-72 lg:rounded-[20px] lg:border lg:translate-x-0 ${
        open ? "translate-x-0 visible" : "translate-x-full invisible lg:visible"
      }`}
    >
      <div className="pb-2 shrink-0 flex justify-between items-center">
        <h2 className="flex items-center gap-2 text-lg font-bold text-emerald-600 dark:text-emerald-400 tracking-tight">
          <span className="flex items-center justify-center w-8 h-8 rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-500/25">
            <FaChartLine size={14} />
          </span>
          بینش شرکت‌ها
        </h2>
        <div className="flex items-center gap-1">
          <button
            onClick={onClose}
            aria-label="بستن منو"
            className="lg:hidden flex items-center justify-center w-8 h-8 rounded-lg text-gray-500 hover:bg-gray-100 dark:hover:bg-gray-700/50 transition"
          >
            ✕
          </button>
        </div>
      </div>

      {/* ── منوی ناوبری اصلی ── */}
      <nav aria-label="صفحه‌های برنامه" className="shrink-0 flex flex-col gap-1">
        {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            end
            onClick={onClose}
            className={({ isActive }) => {
              const active =
                isActive || (item.to === "/ranking" && isRankingPath);
              return `flex items-center gap-2.5 h-10 px-3 rounded-xl text-sm font-semibold transition-all duration-200 ${
                active
                  ? "bg-gradient-to-l from-emerald-500/15 to-teal-500/10 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/25 shadow-sm"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-100/80 dark:hover:bg-gray-700/40 hover:text-gray-800 dark:hover:text-white"
              }`;
            }}
          >
            {({ isActive }) => {
              const active =
                isActive || (item.to === "/ranking" && isRankingPath);
              return (
                <>
                  <span
                    className={`flex items-center justify-center w-7 h-7 rounded-lg text-sm transition ${
                      active
                        ? "bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm shadow-emerald-500/25"
                        : "bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400"
                    }`}
                  >
                    {item.icon}
                  </span>
                  {item.label}
                </>
              );
            }}
          </NavLink>
        ))}
      </nav>

      {/* ── جست‌وجوی شرکت ── */}
      <div className="shrink-0">
        <label
          htmlFor="company"
          className="mb-1.5 block px-1 text-[11px] font-bold text-gray-500 dark:text-gray-400 uppercase tracking-wide"
        >
          انتخاب شرکت
        </label>
        <Select
          inputId="company"
          options={companyOptions}
          value={
            companyOptions.find((opt) => opt.value === selectedCompany) || null
          }
          onChange={(option) => option && handleCompanySelect(option.value)}
          onMenuOpen={onCompanySearchOpen}
          isSearchable
          isRtl
          menuPortalTarget={document.body}
          menuPosition="fixed"
          placeholder="جست‌وجو یا انتخاب..."
          isLoading={loadingCompanies}
          className="text-sm rtl:text-right"
          styles={{
            menuPortal: (base) => ({ ...base, zIndex: 60 }),
            control: (base, state) => ({
              ...base,
              borderRadius: "0.75rem",
              borderColor: state.isFocused
                ? "#059669"
                : darkMode
                  ? "#374151"
                  : "#e5e7eb",
              boxShadow: state.isFocused
                ? "0 0 0 3px rgba(5, 150, 105, 0.15)"
                : "none",
              transition: "all 0.2s",
              minHeight: "2.25rem",
              backgroundColor: darkMode ? "#37415180" : "white",
              textAlign: "right",
              color: darkMode ? "#e5e7eb" : "#1f2937",
              ":hover": {
                borderColor: darkMode ? "#4b5563" : "#d1d5db",
              },
            }),
            valueContainer: (base) => ({
              ...base,
              paddingRight: "0.75rem",
            }),
            placeholder: (base) => ({
              ...base,
              color: "#9ca3af",
              fontWeight: 500,
            }),
            singleValue: (base) => ({
              ...base,
              color: darkMode ? "#e5e7eb" : "#1f2937",
            }),
            input: (base) => ({
              ...base,
              textAlign: "right",
              color: darkMode ? "#e5e7eb" : "#1f2937",
            }),
            dropdownIndicator: (base) => ({
              ...base,
              paddingLeft: "0.5rem",
              paddingRight: "0.5rem",
              color: darkMode ? "#9ca3af" : "#6b7280",
            }),
            indicatorSeparator: () => ({
              display: "none",
            }),
            menu: (base) => ({
              ...base,
              borderRadius: "0.75rem",
              boxShadow:
                "0 10px 40px -10px rgba(5,150,105,0.2), 0 4px 12px -2px rgba(0,0,0,0.15)",
              textAlign: "right",
              zIndex: 50,
              border: darkMode
                ? "1px solid rgba(16,185,129,0.15)"
                : "1px solid rgba(5,150,105,0.1)",
              backgroundColor: darkMode ? "#1f2937" : "white",
              overflow: "hidden",
            }),
            option: (base, state) => ({
              ...base,
              backgroundColor: state.isSelected
                ? "#059669"
                : state.isFocused
                  ? darkMode
                    ? "#064e3b"
                    : "#ecfdf5"
                  : "transparent",
              color: state.isSelected
                ? "white"
                : darkMode
                  ? "#e5e7eb"
                  : "#374151",
              padding: "0.5rem 0.75rem",
              cursor: "pointer",
              fontWeight: state.isSelected ? 600 : 400,
              transition: "background-color 0.15s",
            }),
          }}
        />
      </div>

      <div className="sidebar-scrollport flex-1 min-h-0 overflow-y-auto text-sm">
        {isAdmin && (
          <>
            <div className="pb-2 flex justify-between items-center mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
              <button
                onClick={() => setToolsOpen((v) => !v)}
                className="flex items-center justify-between w-full group"
                aria-expanded={toolsOpen}
                aria-controls="sidebar-data-tools"
              >
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                  ابزارهای داده
                </h3>
                <span className="text-gray-400 group-hover:text-emerald-500 transition text-lg leading-none">
                  {toolsOpen ? "−" : "+"}
                </span>
              </button>
            </div>
            <div id="sidebar-data-tools" className={`flex flex-col gap-2 ${toolsOpen ? "" : "hidden"}`}>
              <button
                onClick={() => setSymbolSync("financial")}
                disabled={!selectedCompany}
                title={
                  selectedCompany
                    ? `آخرین گزارش‌های سود «${selectedCompany}»`
                    : "ابتدا یک نماد انتخاب کنید"
                }
                className="sidebar-tool"
              >
                <FaCoins size={13} />
                جمع‌آوری سود
              </button>

              <button
                onClick={() => setSymbolSync("monthly")}
                disabled={!selectedCompany}
                title={
                  selectedCompany
                    ? `آخرین گزارش‌های فروش «${selectedCompany}»`
                    : "ابتدا یک نماد انتخاب کنید"
                }
                className="sidebar-tool"
              >
                <FaChartPie size={13} />
                جمع‌آوری فروش
              </button>

              <button
                onClick={runCompanyPrices}
                disabled={!selectedCompany || loadingCompanyPrices}
                title={
                  selectedCompany
                    ? `تاریخچه‌ی قیمت «${selectedCompany}»`
                    : "ابتدا یک نماد انتخاب کنید"
                }
                className="sidebar-tool"
              >
                <FaDownload size={13} />
                {loadingCompanyPrices ? "در حال اجرا..." : "جمع‌آوری قیمت‌ها"}
              </button>

              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
                <button
                  onClick={() => setQuickSyncOpen(true)}
                  aria-live="polite"
                  className={`flex items-center justify-center gap-2 w-full h-9 text-white rounded-xl p-2  text-sm tracking-wide shadow-sm transition-all duration-200 ${
                    quickSyncing && !codalWaitingCaptcha
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 hover:shadow-md hover:shadow-emerald-500/20  active:scale-[0.98]"
                  }`}
                >
                  <FaBolt size={13} />
                  {codalWaitingCaptcha
                    ? "کد امنیتی منتظر پاسخ است"
                    : quickSyncing
                      ? "در حال بررسی... · بازکردن وضعیت"
                      : "جمع‌آوری سریع"}
                </button>
              </div>

              {toolsMsg && (
                <p
                  className={`text-xs text-center font-medium ${
                    toolsMsg.kind === "ok"
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-red-500 dark:text-red-400"
                  }`}
                >
                  {toolsMsg.text}
                </p>
              )}

              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
                  قیمت‌های BRS
                </h3>
                <div className="flex flex-col gap-2 overflow-hidden">
                  <button
                    onClick={runBrsDaily}
                    disabled={loadingBrsDaily}
                    className="sidebar-tool"
                  >
                    <FaSyncAlt size={13} />
                    {loadingBrsDaily ? "در حال اجرا..." : "قیمت روزانه"}
                  </button>
                  <button
                    onClick={runBrsBackfill}
                    disabled={loadingBrsBackfill}
                    className="sidebar-tool"
                  >
                    <FaDownload size={13} />
                    {loadingBrsBackfill ? "در حال اجرا..." : "تاریخچه قیمت"}
                  </button>
                  <button
                    onClick={runBrsSync}
                    disabled={loadingBrsSync}
                    className="sidebar-tool"
                  >
                    <FaBalanceScale size={13} />
                    {loadingBrsSync ? "در حال اجرا..." : "تعدیل قیمت‌ها"}
                  </button>
                  {brsMsg && (
                    <p className="text-xs text-center text-emerald-600 dark:text-emerald-400 font-medium">
                      {brsMsg}
                    </p>
                  )}
                </div>
              </div>
            </div>
          </>
        )}
        {!isAdmin && (
          <div className="shadow-sm mt-1 rounded-2xl border border-gray-200/60 dark:border-white/[0.06] bg-white/40 dark:bg-white/[0.03]">
            <button type="button" onClick={onProfitReviewToggle} aria-expanded={profitReviewOpen} aria-controls="sidebar-profit-review" className="w-full p-4 pb-2 flex justify-between items-center">
              <span className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                مرور بازار
              </span>
              <span className="rounded-full bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/20 tabular-nums">
                {profitReviewOpen ? companyProfits.length.toLocaleString("fa-IR") : "+"}
              </span>
            </button>

            {profitReviewOpen && <div id="sidebar-profit-review" className="p-2 pt-0"><NavLink to="/Table" className="block px-3 py-2 text-xs underline">جست‌وجو و مقایسهٔ شرکت‌ها در غربال بازار</NavLink>
              <div className="direction-ltr">
                <ul className="space-y-0.5 text-xs text-gray-700 dark:text-gray-300">
                  {companyProfits.map((company, index) => {
                    const eps = company.eps_growth;
                    let colorClass = "";

                    if (eps > 30) {
                      colorClass =
                        "text-emerald-600 dark:text-emerald-400 font-bold";
                    } else if (eps < -10) {
                      colorClass = "text-red-600 dark:text-red-400 font-bold";
                    }

                    const isSelected = company.company_name === selectedCompany;

                    return (
                      <li
                        key={index}
                        className={`group flex items-center justify-between cursor-pointer p-2 rounded-xl transition-all duration-150 text-sm
                        hover:bg-emerald-50 dark:hover:bg-emerald-950/30
                        ${isSelected ? "bg-emerald-50/80 dark:bg-emerald-950/40 ring-1 ring-emerald-200/60 dark:ring-emerald-800/40" : ""}`}
                        onClick={() =>
                          handleCompanySelect(company.company_name)
                        }
                      >
                        <span
                          className={`font-semibold tabular-nums ${colorClass}`}
                        >
                          {eps != null ? eps.toFixed(2) + "%" : "--"}
                        </span>
                        <span className="flex items-center gap-1.5 font-medium">
                          {company.company_name}
                          <FaArrowRight
                            size={10}
                            className="opacity-0 -translate-x-1 group-hover:opacity-60 group-hover:translate-x-0 transition-all duration-200 text-emerald-500"
                          />
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>}
          </div>
        )}

      </div>
        <div className="profile shrink-0 border-t border-gray-100 dark:border-white/[0.06] pt-3">
 {logoutError && <p role="alert" className="mb-2 text-xs text-red-600">{logoutError}</p>}
          <button
            disabled={loggingOut}
            onClick={async () => {
              setLoggingOut(true); setLogoutError("");
              try { await logoutSession(); window.location.assign("/login"); }
              catch { setLogoutError("خروج کامل نشد؛ دوباره تلاش کنید."); setLoggingOut(false); }
            }}
            className="group flex items-center justify-between w-full h-10 px-3 rounded-2xl border border-gray-200/70 dark:border-white/[0.07] bg-white/60 dark:bg-white/[0.03] hover:border-red-400/50 dark:hover:border-red-500/40 hover:bg-red-50 dark:hover:bg-red-500/10 transition-all duration-300 shadow-sm"
          >
            <span className="flex items-center gap-2 min-w-0">
              <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white text-[10px] font-black shrink-0">
                {(username || "؟").trim().charAt(0).toUpperCase()}
              </span>
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-200 group-hover:text-red-700 dark:group-hover:text-red-300 truncate transition-colors">
                {username}
              </span>
              {isAdmin && (
                <FaShieldAlt
                  size={10}
                  className="text-emerald-500 shrink-0"
                  title="ادمین"
                />
              )}
            </span>
            <span className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-400 group-hover:text-red-500 dark:group-hover:text-red-400 transition-colors">
              خروج
              <FaSignOutAlt size={11} />
            </span>
          </button>
        </div>
    </aside>
      <QuickSyncModal
        visible={quickSyncOpen}
        onClose={() => setQuickSyncOpen(false)}
        onRunningChange={setQuickSyncing}
      />

      <SymbolSyncModal
        visible={symbolSync !== null}
        mode={symbolSync ?? "financial"}
        symbol={selectedCompany}
        onClose={() => setSymbolSync(null)}
        onDataCollected={onDataCollected}
      />
    </>
  );
};

export default Sidebar;
