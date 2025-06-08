import React, { useState } from "react";
import Select from "react-select";
import NavigationButton from "./NavigationButton";
import { fetchFullPE } from "../utils/api";

interface SidebarProps {
  companyOptions: { value: string; label: string }[];
  selectedCompany: string;
  onCompanyChange: (val: string) => void;
  openModalForScript: (
    script: "script1" | "script2" | "full" | "stockPrices"
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
  const fullPE = async () => {
    setLoadingFullPE(true);
    const res = await fetchFullPE();
    setLoadingFullPE(false);
  };

  return (
    <aside className="max-h-[747px] m-4 mb-0 mr-0 w-72 p-6 bg-white/60 dark:bg-gray-800/60 backdrop-blur-lg shadow-2xl rounded-3xl border border-gray-200 dark:border-gray-700 flex flex-col gap-3 transition-all duration-300 ease-in-out">
      <div className="pb-2 flex justify-between items-center">
        <h2 className="text-xl font-bold text-gray-800 dark:text-white tracking-tight mb-2">
          Company Insights
        </h2>
        <NavigationButton />
      </div>
      <div>
        {/* <label
          htmlFor="company"
          className="block mb-2 text-sm font-semibold text-gray-700 dark:text-gray-300"
        >
          Select a Company
        </label> */}
        <Select
          inputId="company"
          options={companyOptions}
          value={
            companyOptions.find((opt) => opt.value === selectedCompany) || null
          }
          onChange={(option) => option && onCompanyChange(option.value)}
          isSearchable
          placeholder="Search or select..."
          isLoading={loadingCompanies}
          className="text-sm rtl:text-right"
          styles={{
            control: (base, state) => ({
              ...base,
              borderRadius: "0.75rem",
              borderColor: state.isFocused ? "#6366f1" : "#d1d5db", // focus: indigo-500, default: gray-300
              boxShadow: state.isFocused
                ? "0 0 0 2px rgba(99, 102, 241, 0.3)"
                : "none",
              transition: "all 0.2s",
              minHeight: "2rem",
              backgroundColor: "white",
              textAlign: "right",
            }),
            valueContainer: (base) => ({
              ...base,
              paddingRight: "0.75rem",
            }),
            placeholder: (base) => ({
              ...base,
              color: "#9ca3af", // text-gray-400
              fontWeight: 500,
            }),
            dropdownIndicator: (base) => ({
              ...base,
              paddingLeft: "0.5rem",
              paddingRight: "0.5rem",
              color: "#6b7280", // gray-500
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
              boxShadow: "0px 10px 15px -3px rgba(0,0,0,0.1)",
              textAlign: "right",
              zIndex: 50,
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
            }),
          }}
        />
      </div>

      <div className="flex flex-col justify-start h-full overflow-auto text-sm ">
        {isAdmin && (
          <>
            <div className="p-4 pb-2 flex justify-between items-center">
              <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                Profit Overview
              </h3>
            </div>
            <div className="flex flex-col gap-2">
              <button
                onClick={() => openModalForScript("script1")}
                disabled={runningScripts.script1}
                className=" w-full h-9 bg-gradient-to-r from-indigo-500 to-indigo-600 hover:from-indigo-600 hover:to-indigo-700 text-white rounded-xl font-sm tracking-wide shadow-lg hover:shadow-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {runningScripts.script1 ? "Running..." : "Gathering Profit"}
              </button>

              <button
                onClick={() => openModalForScript("script2")}
                disabled={runningScripts.script2}
                className="w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl font-sm tracking-wide shadow-lg hover:shadow-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {runningScripts.script2 ? "Running..." : "Gathering Sales"}
              </button>

              <button
                onClick={() => fullPE()}
                disabled={loadingFullPE}
                className={`w-full h-9 text-white rounded-xl font-sm tracking-wide shadow-lg transition-all duration-200
            ${
              loadingFullPE
                ? "bg-gray-400 cursor-not-allowed"
                : "bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700 hover:shadow-xl"
            }`}
              >
                {loadingFullPE ? "Running..." : "Full P/E"}
              </button>

              <button
                onClick={() => openModalForScript("stockPrices")}
                disabled={runningScripts.stockPrices}
                className="w-full h-9 bg-gradient-to-r from-fuchsia-500 to-purple-600 hover:from-fuchsia-600 hover:to-purple-700 text-white rounded-xl font-sm tracking-wide shadow-lg hover:shadow-xl transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {runningScripts.stockPrices ? "Running..." : "Gathering Prices"}
              </button>

              <button
                onClick={() => openModalForScript("full")}
                disabled={runningScripts.full}
                className={`w-full h-9 text-white rounded-xl font-sm tracking-wide shadow-lg transition-all duration-200
                  ${
                    runningScripts.full
                      ? "bg-gray-400 cursor-not-allowed"
                      : "bg-gradient-to-r from-violet-500 to-purple-600 hover:from-violet-600 hover:to-purple-700 hover:shadow-xl"
                  }`}
              >
                {runningScripts.full ? "Running..." : "Full Data Gathering"}
              </button>
            </div>
          </>
        )}
        {!isAdmin && (
          <div className="shadow-md mt-1 backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 h-4/6 flex flex-1 flex-col bg-white/30 dark:bg-gray-700/30 rounded-xl shadow-inner">
            {/* Fixed header */}
            <div className="p-4 pb-2 flex justify-between items-center">
              <h3 className="text-sm font-semibold text-gray-800 dark:text-gray-200">
                Profit Overview
              </h3>
            </div>

            {/* Scrollable content */}

            <div className="overflow-auto direction-rtl flex-1 p-2 pt-0">
              <div className="direction-ltr">
                <ul className="space-y-1 text-xs text-gray-700 dark:text-gray-300">
                  {companyProfits.map((company, index) => {
                    const eps = company.eps_growth;
                    let colorClass = "";

                    if (eps > 50) {
                      colorClass =
                        "text-green-600 dark:text-green-400 font-bold";
                    } else if (eps < -10) {
                      colorClass = "text-red-600 dark:text-red-400 font-bold";
                    }

                    const isSelected = company.company_name === selectedCompany;

                    return (
                      <li
                        key={index}
                        className={`flex justify-between cursor-pointer p-2 rounded-lg transition text-sm
                        hover:bg-gray-200 dark:hover:bg-gray-600
                        ${isSelected ? "bg-gray-100 dark:bg-gray-700" : ""}`}
                        onClick={() => onCompanyChange(company.company_name)}
                      >
                        <span className={`font-semibold ${colorClass}`}>
                          {/* {eps.toFixed(2)}% */}
                          {eps != null ? eps.toFixed(2) + "%" : "--"}
                        </span>

                        {/* <span className="text-sm">{company.priceScore}%</span> */}
                        <span>{company.company_name}</span>
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
            className="w-full h-9 bg-black dark:bg-gray-200 hover:bg-gray-800 dark:hover:bg-gray-200 text-white dark:text-black rounded-xl font-semibold tracking-wide shadow-md transition-all duration-200"
          >
            {username}
          </button>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
