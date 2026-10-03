import React, { useState } from "react";
import Select from "react-select";
import { NavLink } from "react-router-dom";
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
  FaBriefcase,
  FaTable,
  FaRobot,
  FaGlobe,
} from "react-icons/fa";
import QuickSyncModal from "./QuickSyncModal";
import SymbolSyncModal from "./SymbolSyncModal";
import { useDarkMode } from "../utils/theme";
import { addViewedItem, collectBrsPrices } from "../utils/api";

interface SidebarProps {
  companyOptions: { value: string; label: string }[];
  selectedCompany: string;
  onCompanyChange: (val: string) => void;

  loadingCompanies: boolean;
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
  { to: "/dashboard", label: "داشبورد شرکت", icon: <FaChartLine size={13} /> },
  // { to: "/market", label: "بازار و طلا", icon: <FaGlobe size={13} /> },
  { to: "/Table", label: "غربال بازار", icon: <FaTable size={13} /> },
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
  companyProfits,
  isAdmin,
  username,
  open = false,
  onClose,
  onDataCollected,
}) => {
  const [toolsOpen, setToolsOpen] = useState(true);
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
    } catch (e: any) {
      setToolsMsg({
        kind: "err",
        text: e?.message || "خطا در جمع‌آوری قیمت",
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
    } catch (e: any) {
      setBrsMsg(e?.message || "خطا در دریافت قیمت");
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
    } catch (e: any) {
      setBrsMsg(e?.message || "خطا در backfill");
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
    } catch (e: any) {
      setBrsMsg(e?.message || "خطا در sync");
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
    <aside
      className={`fixed left-0 top-0 z-40 h-full w-80 p-6 overflow-y-auto bg-white/95 dark:bg-gray-800/95 backdrop-blur-xl shadow-2xl shadow-emerald-500/5 dark:shadow-emerald-500/10 border-r border-gray-200/80 dark:border-gray-700/60 flex flex-col gap-3 transition-transform duration-300 ease-in-out lg:sticky lg:top-4 lg:h-auto lg:max-h-[97vh] lg:mb-0 lg:mr-0 lg:rounded-3xl lg:border lg:translate-x-0 ${
        open ? "translate-x-0" : "-translate-x-full"
      }`}
    >
      <div className="pb-2 flex justify-between items-center">
        <h2 className="flex items-center gap-2 text-xl font-bold text-gradient-emerald tracking-tight">
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
      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => (
          <NavLink
            key={item.to}
            to={item.to}
            onClick={onClose}
            className={({ isActive }) =>
              `flex items-center gap-2.5 h-10 px-3 rounded-xl text-sm font-semibold transition-all duration-200 ${
                isActive
                  ? "bg-gradient-to-l from-emerald-500/15 to-teal-500/10 text-emerald-700 dark:text-emerald-300 ring-1 ring-emerald-500/25 shadow-sm"
                  : "text-gray-600 dark:text-gray-300 hover:bg-gray-100/80 dark:hover:bg-gray-700/40 hover:text-gray-800 dark:hover:text-white"
              }`
            }
          >
            {({ isActive }) => (
              <>
                <span
                  className={`flex items-center justify-center w-7 h-7 rounded-lg text-sm transition ${
                    isActive
                      ? "bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-sm shadow-emerald-500/25"
                      : "bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400"
                  }`}
                >
                  {item.icon}
                </span>
                {item.label}
              </>
            )}
          </NavLink>
        ))}
      </nav>

      <div>
        <Select
          inputId="company"
          options={companyOptions}
          value={
            companyOptions.find((opt) => opt.value === selectedCompany) || null
          }
          onChange={(option) => option && handleCompanySelect(option.value)}
          isSearchable
          placeholder="جست‌وجو یا انتخاب..."
          isLoading={loadingCompanies}
          className="text-sm rtl:text-right"
          styles={{
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

      <div className="flex flex-col justify-start h-full overflow-auto text-sm ">
        {isAdmin && (
          <>
            <div className="pb-2 flex justify-between items-center mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
              <button
                onClick={() => setToolsOpen((v) => !v)}
                className="flex items-center justify-between w-full group"
                aria-expanded={toolsOpen}
              >
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                  ابزارهای داده
                </h3>
                <span className="text-gray-400 group-hover:text-emerald-500 transition text-lg leading-none">
                  {toolsOpen ? "−" : "+"}
                </span>
              </button>
            </div>
            <div className={`flex flex-col gap-2 ${toolsOpen ? "" : "hidden"}`}>
              <button
                onClick={() => setSymbolSync("financial")}
                disabled={!selectedCompany}
                title={
                  selectedCompany
                    ? `آخرین گزارش‌های سود «${selectedCompany}»`
                    : "ابتدا یک نماد انتخاب کنید"
                }
                className="flex items-center justify-center gap-2 w-full h-9 bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 text-white rounded-xl p-2 text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-emerald-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
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
                className="flex items-center justify-center gap-2 w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl p-2  text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-purple-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
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
                className="flex items-center justify-center gap-2 w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl p-2  text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-purple-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed active:scale-[0.98]"
              >
                <FaDownload size={13} />
                {loadingCompanyPrices ? "در حال اجرا..." : "جمع‌آوری قیمت‌ها"}
              </button>

              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
                <button
                  onClick={() => setQuickSyncOpen(true)}
                  disabled={quickSyncing}
                  className={`flex items-center justify-center gap-2 w-full h-9 text-white rounded-xl p-2  text-sm tracking-wide shadow-sm transition-all duration-200 ${
                    quickSyncing
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 hover:shadow-md hover:shadow-emerald-500/20  active:scale-[0.98]"
                  }`}
                >
                  <FaBolt size={13} />
                  {quickSyncing ? "در حال بررسی..." : "جمع‌آوری سریع"}
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
                    className={`flex items-center justify-center gap-2 w-full h-9 text-white rounded-xl p-2 text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsDaily
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 hover:shadow-md hover:shadow-emerald-500/20  active:scale-[0.98]"
                      }`}
                  >
                    <FaSyncAlt size={13} />
                    {loadingBrsDaily ? "در حال اجرا..." : "قیمت روزانه"}
                  </button>
                  <button
                    onClick={runBrsBackfill}
                    disabled={loadingBrsBackfill}
                    className={`flex items-center justify-center gap-2 w-full h-9 text-white rounded-xl p-2 text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsBackfill
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 hover:shadow-md hover:shadow-cyan-500/20  active:scale-[0.98]"
                      }`}
                  >
                    <FaDownload size={13} />
                    {loadingBrsBackfill ? "در حال اجرا..." : "تاریخچه قیمت"}
                  </button>
                  <button
                    onClick={runBrsSync}
                    disabled={loadingBrsSync}
                    className={`flex items-center justify-center gap-2 w-full h-9 text-white rounded-xl p-2 text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsSync
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 hover:shadow-md hover:shadow-amber-500/20  active:scale-[0.98]"
                      }`}
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
          <div className="shadow-sm mt-1 backdrop-blur-sm rounded-2xl border border-gray-200/60 dark:border-gray-700/40 h-4/6 flex flex-1 flex-col bg-white/40 dark:bg-gray-700/20">
            <div className="p-4 pb-2 flex justify-between items-center">
              <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                مرور سود
              </h3>
            </div>

            <div className="overflow-auto direction-rtl flex-1 p-2 pt-0">
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
            </div>
          </div>
        )}

        <div className="profile mt-4 overflow-hidden">
          <button
            onClick={() => {
              localStorage.removeItem("token");
              window.location.href = "/login";
            }}
            className="group flex items-center justify-between w-full h-10 px-3 rounded-2xl border border-gray-200/70 dark:border-gray-700/50 bg-white/60 dark:bg-gray-700/30 hover:bg-gray-900 dark:hover:bg-gray-100 transition-all duration-300 shadow-sm"
          >
            <span className="flex items-center gap-2 min-w-0">
              <span className="flex items-center justify-center w-6 h-6 rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white text-[10px] font-black shrink-0">
                {(username || "؟").trim().charAt(0).toUpperCase()}
              </span>
              <span className="text-sm font-semibold text-gray-700 dark:text-gray-200 group-hover:text-white dark:group-hover:text-gray-900 truncate transition-colors">
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
            <span className="flex items-center gap-1.5 text-[10px] font-semibold text-gray-400 group-hover:text-gray-300 dark:group-hover:text-gray-600 transition-colors">
              خروج
              <FaSignOutAlt size={11} />
            </span>
          </button>
        </div>
      </div>

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
    </aside>
  );
};

export default Sidebar;
