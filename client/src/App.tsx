import React from "react";
import Sidebar from "./components/Sidebar";
import ChartComponent from "./components/ChartComponent";
import useCompanyData from "./hooks/useCompanyData";
import ScriptModal from "./components/ScriptModal";
import { useDarkMode } from "./utils/theme";
import { FaSun, FaMoon } from "react-icons/fa";
import DonutChartComponent from "./components/DonutChartComponent";
import { Routes, Route } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import ScriptFullModal from "./components/ScriptFullModal";
// import StockChartComponent from "./components/StockChartComponent";
// import StockCandleChart from "./components/StockChartComponent";
import GaugeChartComponent from "./components/GaugeChartComponent";
import Login from "./components/Login";
import ProtectedRoute from "./components/ProtectedRoute";
import BigDataTable from "./components/BigDataTable";
import Register from "./components/Register";

const App = () => {
  const { darkMode, toggleDarkMode } = useDarkMode();
  const {
    companyOptions,
    selectedCompany,
    setSelectedCompany,
    data1,
    data2,
    dataScore,
    allDataScore,
    stockPrice,
    stockPriceScore,
    loadingData,
    runningScripts,
    metadata,
    setMetadata,
    scriptModalStates,
    setScriptModalStates,
    fullModalData,
    setFullModalData,
    openModalForScript,
    submitMetadata,
    ...scriptModalProps
  } = useCompanyData();

  const [searchParams, setSearchParams] = useSearchParams();

  const handleCompanyChange = (name: string) => {
    setSelectedCompany(name);
    setSearchParams({ companyname: name });
  };

  return (
    <div
      className={`min-h-screen ${
        darkMode ? "dark" : ""
      } bg-gradient-to-br from-gray-100 via-white to-gray-200 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900 transition-colors duration-500`}
    >
      <div className="flex h-full">
        <Sidebar
          companyOptions={companyOptions}
          selectedCompany={selectedCompany}
          onCompanyChange={handleCompanyChange}
          openModalForScript={openModalForScript}
          runningScripts={runningScripts}
          companyProfits={
            allDataScore
              ? allDataScore
              : [{ companyName: "loading", epsGrowth: 0 }]
          }
          {...scriptModalProps}
        />
        <main className="flex-1 bg-white/50 dark:bg-gray-900/40 backdrop-blur-lg mb-0 shadow-2xl transition-all duration-300 my-5 mr-[15px] p-4 rounded-3xl border border-gray-200 dark:border-gray-700">
          <Routes>
            <Route path="/login" element={<Login />} />
            <Route path="/register" element={<Register />} />
            <Route
              path="/"
              element={
                <ProtectedRoute>
                  {loadingData ? (
                    <p className="text-center text-gray-500 dark:text-gray-300">
                      Loading company data...
                    </p>
                  ) : (
                    <div className="flex flex-col justify-center h-full ">
                      <div className="shadow-md backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px]">
                        <div className="flex gap-3">
                          <div className="w-3/4">
                            <ChartComponent data={data1} />
                          </div>
                          <div className="w-1/4">
                            {dataScore && (
                              <DonutChartComponent
                                score={dataScore[0].epsGrowth}
                              />
                            )}
                          </div>
                        </div>
                      </div>
                      <div className="shadow-md mt-2 backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px]">
                        <div className="flex gap-3">
                          <div className="w-3/4">
                            <ChartComponent data={data2} />
                          </div>
                          <div className="w-1/4">
                            {dataScore && (
                              <DonutChartComponent
                                score={dataScore[0].salesGrowth}
                              />
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </ProtectedRoute>
              }
            />

            <Route
              path="/Table"
              element={
                <div>
                  <BigDataTable
                    data={Array.isArray(allDataScore) ? allDataScore : []}
                    selectedCompany={selectedCompany}
                    onCompanyChange={handleCompanyChange}
                  />
                </div>
              }
            />
          </Routes>
        </main>
      </div>
      <ScriptModal
        modal={{ visible: scriptModalStates.script1, script: "profit" }}
        setModal={(val) =>
          setScriptModalStates((prev) => ({ ...prev, script1: val.visible }))
        }
        metadata={metadata}
        setMetadata={setMetadata}
        runningScripts={runningScripts}
        submitMetadata={() => submitMetadata("script1")}
      />

      <ScriptModal
        modal={{ visible: scriptModalStates.script2, script: "sales" }}
        setModal={(val) =>
          setScriptModalStates((prev) => ({ ...prev, script2: val.visible }))
        }
        metadata={metadata}
        setMetadata={setMetadata}
        runningScripts={runningScripts}
        submitMetadata={() => submitMetadata("script2")}
      />

      <ScriptModal
        modal={{
          visible: scriptModalStates.stockPrices,
          script: "stockPrices",
        }}
        setModal={(val) =>
          setScriptModalStates((prev) => ({
            ...prev,
            stockPrices: val.visible,
          }))
        }
        metadata={metadata}
        setMetadata={setMetadata}
        runningScripts={runningScripts}
        submitMetadata={() => submitMetadata("stockPrices")}
      />

      <ScriptFullModal
        modal={{ visible: scriptModalStates.full, ...fullModalData }}
        setModal={(val) => {
          setScriptModalStates((prev) => ({ ...prev, full: val.visible }));
          setFullModalData(val);
        }}
        submitMetadata={() => submitMetadata("full")}
      />

      <button
        onClick={toggleDarkMode}
        className="fixed bottom-14 left-8 p-2 rounded-full bg-gray-200 dark:bg-gray-700 shadow-lg"
      >
        {darkMode ? <FaSun /> : <FaMoon />}
      </button>
    </div>
  );
};

export default App;
