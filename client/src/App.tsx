import React from "react";
import Sidebar from "./components/Sidebar";
import ChartComponent from "./components/ChartComponent";
import useCompanyData from "./hooks/useCompanyData";
import ScriptModal from "./components/ScriptModal";
import { useDarkMode } from "./utils/theme";
import { FaSun, FaMoon } from "react-icons/fa";
import DonutChartComponent from "./components/DonutChartComponent";

const App = () => {
  const { darkMode, toggleDarkMode } = useDarkMode();
  const {
    companyOptions,
    selectedCompany,
    setSelectedCompany,
    data1,
    data2,
    dataScore,
    loadingData,
    ...scriptModalProps
  } = useCompanyData();

  return (
    <div
      className={`min-h-screen ${
        darkMode ? "dark" : ""
      } bg-gradient-to-br from-gray-100 via-white to-gray-200 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900 transition-colors duration-500`}
    >
      <div className="flex h-screen">
        <Sidebar
          companyOptions={companyOptions}
          selectedCompany={selectedCompany}
          onCompanyChange={setSelectedCompany}
          {...scriptModalProps}
        />
        <main className="flex-1 p-6  bg-white/50 dark:bg-gray-900/40 backdrop-blur-md rounded-xl m-4 shadow-2xl transition-all duration-300 ">
          {loadingData ? (
            <p className="text-center text-gray-500 dark:text-gray-300">
              Loading company data...
            </p>
          ) : (
            <div className="flex flex-col justify-between h-full">
              <div className="flex gap-3">
                <div className="w-2/3 shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] pr-[25px]">
                  <ChartComponent data={data1} />
                </div>
                <div className="w-1/3 shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px]">
                  <DonutChartComponent data={dataScore} />
                </div>
              </div>

              <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] pr-[25px] pl-[15px]">
                <ChartComponent data={data2} />
              </div>
            </div>
          )}
        </main>
      </div>
      <ScriptModal {...scriptModalProps} />
      <button
        onClick={toggleDarkMode}
        className="fixed bottom-16 left-8 p-2 rounded-full bg-gray-200 dark:bg-gray-700 shadow-lg"
      >
        {darkMode ? <FaSun /> : <FaMoon />}
      </button>
    </div>
  );
};

export default App;
