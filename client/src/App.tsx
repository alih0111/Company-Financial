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

const App = () => {
  const { darkMode, toggleDarkMode } = useDarkMode();
  // const {
  //   companyOptions,
  //   selectedCompany,
  //   setSelectedCompany,
  //   data1,
  //   data2,
  //   dataScore,
  //   allDataScore,
  //   loadingData,
  //   runningScripts,
  //   scriptModalStates,
  //   setScriptModalStates,
  //   fullModalData,
  //   setFullModalData,
  //   ...scriptModalProps
  // } = useCompanyData();
  const {
    companyOptions,
    selectedCompany,
    setSelectedCompany,
    data1,
    data2,
    dataScore,
    allDataScore,
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
      <div className="flex h-screen">
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
        <main className="flex-1 p-6 bg-white/50 dark:bg-gray-900/40 backdrop-blur-md rounded-xl m-4 shadow-2xl transition-all duration-300 ">
          <Routes>
            <Route
              path="/"
              element={
                loadingData ? (
                  <p className="text-center text-gray-500 dark:text-gray-300">
                    Loading company data...
                  </p>
                ) : (
                  <div className="flex flex-col justify-between h-full">
                    <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px]">
                      <div className="flex gap-3">
                        <div className="w-3/4 ">
                          <ChartComponent data={data1} />
                        </div>
                        <div className="w-1/4 ">
                          {dataScore && (
                            <DonutChartComponent
                              score={dataScore[0].epsGrowth}
                            />
                          )}
                        </div>
                      </div>
                    </div>
                    <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px]">
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
                        </div>{" "}
                      </div>
                    </div>
                  </div>
                )
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
        className="fixed bottom-16 left-8 p-2 rounded-full bg-gray-200 dark:bg-gray-700 shadow-lg"
      >
        {darkMode ? <FaSun /> : <FaMoon />}
      </button>
    </div>
  );
};

export default App;
