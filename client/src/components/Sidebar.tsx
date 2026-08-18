import React, { useState } from "react";
import Select from "react-select";
import { useNavigate } from "react-router-dom";
import NavigationButton from "./NavigationButton";
import { addViewedItem, collectBrsPrices, fetchFullPE } from "../utils/api";

interface SidebarProps {
  companyOptions: { value: string; label: string }[];
  selectedCompany: string;
  onCompanyChange: (val: string) => void;
  openModalForScript: (
    script: "script1" | "script2" | "full" | "stockPrices",
  ) => void;
  runningScripts: Record<
    "script1" | "script2" | "full" | "stockPrices",
    boolean
  >;

  loadingCompanies: boolean;
  isAdmin: boolean;
  username: string | null;
  companyProfits: {
    company_name: string;
    eps_growth: number;
    priceScore: number;
    sales_growth: number;
  }[];
}

const Sidebar: React.FC<SidebarProps> = ({
  companyOptions,
  selectedCompany,
  onCompanyChange,
  openModalForScript,
  runningScripts,
  loadingCompanies,
  companyProfits,
  isAdmin,
  username,
}) => {
  const [loadingFullPE, setLoadingFullPE] = useState(false);
  const [loadingBrsDaily, setLoadingBrsDaily] = useState(false);
  const [loadingBrsBackfill, setLoadingBrsBackfill] = useState(false);
  const [loadingBrsSync, setLoadingBrsSync] = useState(false);
  const [brsMsg, setBrsMsg] = useState<string | null>(null);
  const navigate = useNavigate();

  const fullPE = async () => {
    setLoadingFullPE(true);
    const res = await fetchFullPE();
    setLoadingFullPE(false);
  };

  const runBrsDaily = async () => {
    setLoadingBrsDaily(true);
    setBrsMsg(null);
    try {
      await collectBrsPrices("daily");
      setBrsMsg("قیمت روزانه ذخیره شد ✓");
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
      const res = await collectBrsPrices("sync", { limit: 30, threshold: 20 });
      setBrsMsg("تعدیل قیمت‌ها انجام شد ✓");
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
    <aside className="sticky top-4 max-h-[97vh] m-4 mb-0 mr-0 w-72 p-6 bg-white/70 dark:bg-gray-800/50 backdrop-blur-xl shadow-2xl shadow-indigo-500/5 dark:shadow-indigo-500/10 rounded-3xl border border-gray-200/80 dark:border-gray-700/60 flex flex-col gap-3 transition-all duration-300 ease-in-out glass-border glass-border-active">
      <div className="pb-2 flex justify-between items-center">
        <h2 className="text-xl font-bold text-gradient-indigo tracking-tight">
          Company Insights
        </h2>
        <NavigationButton />
      </div>
      <div>
        <Select
          inputId="company"
          options={companyOptions}
          value={
            companyOptions.find((opt) => opt.value === selectedCompany) || null
          }
          onChange={(option) => option && handleCompanySelect(option.value)}
          isSearchable
          placeholder="Search or select..."
          isLoading={loadingCompanies}
          className="text-sm rtl:text-right"
          styles={{
            control: (base, state) => ({
              ...base,
              borderRadius: "0.75rem",
              borderColor: state.isFocused ? "#6366f1" : "#e5e7eb",
              boxShadow: state.isFocused
                ? "0 0 0 3px rgba(99, 102, 241, 0.15)"
                : "0 1px 2px rgba(0,0,0,0.05)",
              transition: "all 0.2s",
              minHeight: "2.25rem",
              backgroundColor: "white",
              textAlign: "right",
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
            dropdownIndicator: (base) => ({
              ...base,
              paddingLeft: "0.5rem",
              paddingRight: "0.5rem",
              color: "#6b7280",
            }),
            indicatorSeparator: () => ({
              display: "none",
            }),
            input: (base) => ({
              ...base,
              textAlign: "right",
            }),
            menu: (base) => ({
              ...base,
              borderRadius: "0.75rem",
              boxShadow:
                "0 10px 40px -10px rgba(99,102,241,0.15), 0 4px 12px -2px rgba(0,0,0,0.08)",
              textAlign: "right",
              zIndex: 50,
              border: "1px solid rgba(99,102,241,0.1)",
            }),
            option: (base, state) => ({
              ...base,
              backgroundColor: state.isSelected
                ? "#6366f1"
                : state.isFocused
                  ? "#eef2ff"
                  : "white",
              color: state.isSelected ? "white" : "#374151",
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
            <div className=" pb-2 flex justify-between items-center mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
              <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
                Profit Overview
              </h3>
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => navigate("/assets")}
                className="w-full h-9 bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 text-white rounded-xl text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-amber-500/20 transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
              >
                دارایی خانواده
              </button>
              <button
                onClick={() => openModalForScript("script1")}
                disabled={runningScripts.script1}
                className=" w-full h-9 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white rounded-xl text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-indigo-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
              >
                {runningScripts.script1 ? "Running..." : "Gathering Profit"}
              </button>

              <button
                onClick={() => openModalForScript("script2")}
                disabled={runningScripts.script2}
                className="w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-purple-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
              >
                {runningScripts.script2 ? "Running..." : "Gathering Sales"}
              </button>

              <button
                onClick={() => fullPE()}
                disabled={loadingFullPE}
                className={`w-full h-9 text-white rounded-xl text-sm tracking-wide shadow-sm transition-all duration-200
            ${
              loadingFullPE
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700 hover:shadow-md hover:shadow-purple-500/20 hover:scale-[1.02] active:scale-[0.98]"
            }`}
              >
                {loadingFullPE ? "Running..." : "Full P/E"}
              </button>

              <button
                onClick={() => openModalForScript("stockPrices")}
                disabled={runningScripts.stockPrices}
                className="w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl text-sm tracking-wide shadow-sm hover:shadow-md hover:shadow-purple-500/20 transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed hover:scale-[1.02] active:scale-[0.98]"
              >
                {runningScripts.stockPrices ? "Running..." : "Gathering Prices"}
              </button>

              <button
                onClick={() => openModalForScript("full")}
                disabled={runningScripts.full}
                className={`w-full h-9 text-white rounded-xl text-sm tracking-wide shadow-sm transition-all duration-200
                  ${
                    runningScripts.full
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700 hover:shadow-md hover:shadow-purple-500/20 hover:scale-[1.02] active:scale-[0.98]"
                  }`}
              >
                {runningScripts.full ? "Running..." : "Full Data Gathering"}
              </button>

              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-gray-700/60">
                <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200 mb-2">
                  BRS Prices
                </h3>
                <div className="flex flex-col gap-2">
                  <button
                    onClick={runBrsDaily}
                    disabled={loadingBrsDaily}
                    className={`w-full h-9 text-white rounded-xl text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsDaily
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-emerald-500 to-teal-600 hover:from-emerald-600 hover:to-teal-700 hover:shadow-md hover:shadow-emerald-500/20 hover:scale-[1.02] active:scale-[0.98]"
                      }`}
                  >
                    {loadingBrsDaily ? "Running..." : "Daily Prices"}
                  </button>
                  <button
                    onClick={runBrsBackfill}
                    disabled={loadingBrsBackfill}
                    className={`w-full h-9 text-white rounded-xl text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsBackfill
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 hover:shadow-md hover:shadow-cyan-500/20 hover:scale-[1.02] active:scale-[0.98]"
                      }`}
                  >
                    {loadingBrsBackfill ? "Running..." : "Backfill History"}
                  </button>
                  <button
                    onClick={runBrsSync}
                    disabled={loadingBrsSync}
                    className={`w-full h-9 text-white rounded-xl text-sm tracking-wide shadow-sm transition-all duration-200
                      ${
                        loadingBrsSync
                          ? "bg-gray-400 cursor-not-allowed"
                          : "bg-gradient-to-r from-amber-500 to-orange-600 hover:from-amber-600 hover:to-orange-700 hover:shadow-md hover:shadow-amber-500/20 hover:scale-[1.02] active:scale-[0.98]"
                      }`}
                  >
                    {loadingBrsSync ? "Running..." : "Sync Adjustments"}
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
                Profit Overview
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
                        className={`flex justify-between cursor-pointer p-2 rounded-lg transition-all duration-150 text-sm
                        hover:bg-indigo-50 dark:hover:bg-indigo-950/30
                        ${isSelected ? "bg-indigo-50/80 dark:bg-indigo-950/40 ring-1 ring-indigo-200/60 dark:ring-indigo-800/40" : ""}`}
                        onClick={() =>
                          handleCompanySelect(company.company_name)
                        }
                      >
                        <span
                          className={`font-semibold tabular-nums ${colorClass}`}
                        >
                          {eps != null ? eps.toFixed(2) + "%" : "--"}
                        </span>
                        <span className="font-medium">
                          {company.company_name}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </div>
            </div>
          </div>
        )}

        <div className="profile mt-4">
          <button
            onClick={() => {
              localStorage.removeItem("token");
              window.location.href = "/login";
            }}
            className="w-full h-9 bg-gray-900 dark:bg-gray-100 hover:bg-gray-800 dark:hover:bg-gray-200 text-white dark:text-gray-900 rounded-xl font-semibold tracking-wide shadow-sm transition-all duration-200 hover:scale-[1.02] active:scale-[0.98]"
          >
            {username}
          </button>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
