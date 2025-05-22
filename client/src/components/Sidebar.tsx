import React from "react";
import Select from "react-select";

interface SidebarProps {
  companyOptions: { value: string; label: string }[];
  selectedCompany: string;
  onCompanyChange: (val: string) => void;
  openModalForScript: (script: "script1" | "script2") => void;
  runningScripts: Record<"script1" | "script2", boolean>;
  loadingCompanies: boolean;
}

const Sidebar: React.FC<SidebarProps> = ({
  companyOptions,
  selectedCompany,
  onCompanyChange,
  openModalForScript,
  runningScripts,
  loadingCompanies,
}) => {
  return (
    <aside className="m-4 w-72 p-6 bg-white/60 dark:bg-gray-800/60 backdrop-blur-lg shadow-2xl rounded-3xl border border-gray-200 dark:border-gray-700 flex flex-col gap-6 transition-all duration-300 ease-in-out">
      <h2 className="text-2xl font-bold text-gray-800 dark:text-white tracking-tight">
        Company Insights
      </h2>

      <div>
        <label
          htmlFor="company"
          className="block mb-2 text-sm font-semibold text-gray-600 dark:text-gray-300"
        >
          Select a Company
        </label>
        <Select
          inputId="company"
          options={companyOptions}
          value={
            companyOptions.find((opt) => opt.value === selectedCompany) || null
          }
          onChange={(option) => option && onCompanyChange(option.value)}
          isSearchable
          placeholder="Search or select..."
          className="text-sm rtl:text-right" // Add rtl:text-right for RTL text alignment
          isLoading={loadingCompanies}
          styles={{
            control: (base) => ({
              ...base,
              borderRadius: "0.75rem",
              borderColor: "#e5e7eb",
              boxShadow: "none",
              paddingRight: "8px", // Adjust padding for RTL
              textAlign: "right", // Force text alignment to right
            }),
            dropdownIndicator: (base) => ({
              ...base,
              left: "8px", // Move dropdown indicator to the left
              right: "auto", // Reset right positioning
            }),
            indicatorSeparator: (base) => ({
              ...base,
              marginRight: "8px", // Adjust separator position
              marginLeft: 0,
            }),
            input: (base) => ({
              ...base,
              textAlign: "right", // Align input text to right
            }),
            menu: (base) => ({
              ...base,
              textAlign: "right", // Align dropdown menu items to right
            }),
          }}
        />
      </div>

      <div className="flex flex-col justify-between h-full">
        <div className="flex flex-col gap-3">
          <button
            onClick={() => openModalForScript("script1")}
            disabled={runningScripts.script1}
            className="w-full h-11 bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl font-semibold tracking-wide shadow-md transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {runningScripts.script1 ? "Running..." : "Gathering Profit"}
          </button>

          <button
            onClick={() => openModalForScript("script2")}
            // disabled={runningScripts.script2}
            className="w-full h-11 bg-purple-600 hover:bg-purple-700 text-white rounded-xl font-semibold tracking-wide shadow-md transition-all duration-200 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {runningScripts.script2 ? "Running..." : "Gathering Sales"}
          </button>
        </div>

        <div className="profile">
          <button className="w-full h-11 bg-black dark:bg-gray-200 hover:bg-gray-800 dark:hover:bg-gray-200 text-white dark:text-black rounded-xl font-semibold tracking-wide shadow-md transition-all duration-200">
            Admin
          </button>
        </div>
      </div>
    </aside>
  );
};

export default Sidebar;
