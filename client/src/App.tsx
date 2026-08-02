import Sidebar from "./components/Sidebar";
import ChartComponent from "./components/ChartComponent";
import PriceChart from "./components/PriceChart";
import ScoreBreakdown from "./components/ScoreBreakdown";
import useCompanyData from "./hooks/useCompanyData";
import ScriptModal from "./components/ScriptModal";
import { useDarkMode } from "./utils/theme";
import { FaSun, FaMoon } from "react-icons/fa";
import DonutChartComponent from "./components/DonutChartComponent";
import { Routes, Route, useLocation, useNavigate } from "react-router-dom";
import { useSearchParams } from "react-router-dom";
import ScriptFullModal from "./components/ScriptFullModal";
import Login from "./components/Login";
import ProtectedRoute from "./components/ProtectedRoute";
import BigDataTable from "./components/BigDataTable";
import Register from "./components/Register";
import { getAuthStatus } from "./hooks/useGetUser";
import { useEffect, useMemo, useState } from "react";
import AIStockTable from "./components/AIStockTable";
import Portfolio from "./components/Portfolio";
import { getAIStockSummary, type AIStockMetric } from "./utils/api";

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

  const navigate = useNavigate();
  const handleCompanyChange = (name: string) => {
    setSelectedCompany(name);
    setSearchParams({ companyname: name });
    navigate(`/?companyname=${encodeURIComponent(name || "")}`);
  };

  const location = useLocation();
  const hideSidebar =
    location.pathname === "/login" || location.pathname === "/register";

  const { isAdmin, username } = getAuthStatus();

  useEffect(() => {
    if (location.pathname === "/Table") {
      document.title = "RFA | Table";
    } else if (location.pathname === "/portfolio") {
      document.title = "RFA | Portfolio";
    } else {
      document.title = selectedCompany ? `RFA | ${selectedCompany}` : "RFA";
    }
  }, [selectedCompany, location.pathname]);

  const [aiRows, setAiRows] = useState<Record<string, AIStockMetric>>({});

  useEffect(() => {
    const loadAIData = async () => {
      try {
        const rows = await getAIStockSummary(1000);

        const rowMap: Record<string, AIStockMetric> = {};

        rows.forEach((row) => {
          if (row.company_id) {
            rowMap[String(row.company_id)] = row;
          }
        });

        setAiRows(rowMap);
      } catch (err) {
        console.error("Failed to load AI data:", err);
      }
    };

    loadAIData();
  }, []);

  const bigTableData = useMemo(() => {
    const baseData = Array.isArray(allDataScore) ? allDataScore : [];

    return baseData.map((row) => {
      const ai = aiRows[String(row.company_id)];
      return {
        ...row,
        ...ai,
      };
    });
  }, [allDataScore, aiRows]);

  return (
    <div
      className={`min-h-screen ${
        darkMode ? "dark" : ""
      } bg-gradient-to-br from-gray-100 via-white to-gray-200 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900 transition-colors duration-500`}
    >
      <div className="flex h-full">
        {!hideSidebar && (
          <Sidebar
            companyOptions={companyOptions}
            selectedCompany={selectedCompany}
            onCompanyChange={handleCompanyChange}
            openModalForScript={openModalForScript}
            runningScripts={runningScripts}
            companyProfits={
              allDataScore
                ? allDataScore
                : [{ company_name: "loading", eps_growth: 0 }]
            }
            {...scriptModalProps}
            isAdmin={isAdmin}
            username={username}
          />
        )}

        <main className="flex-1 mb-3 bg-white/50 dark:bg-gray-900/40 backdrop-blur-lg mb-0 shadow-2xl transition-all duration-300 my-4 mx-[15px] p-4 rounded-3xl border border-gray-200 dark:border-gray-700">
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
                      <div className="py-2">
                        {data1 ? (
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
                        ) : (
                          <p>Loading chart data...</p>
                        )}
                      </div>
                      <div className=" py-2">
                        {data2 ? (
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
                        ) : (
                          <p>Loading chart data...</p>
                        )}
                      </div>

                      {/* نمودار قیمت سهم */}
                      {selectedCompany && (
                        <div className="py-2 min-h-[440px]">
                          <PriceChart companyName={selectedCompany} />
                        </div>
                      )}

                      {/* تجزیه‌ی امتیاز */}
                      {selectedCompany && (
                        <div className="py-2">
                          <ScoreBreakdown
                            metric={Object.values(aiRows).find(
                              (r) => r.company_name === selectedCompany,
                            )}
                          />
                        </div>
                      )}
                    </div>
                  )}
                </ProtectedRoute>
              }
            />

            {/* <Route
              path="/Table"
              element={
                <div>
                  <BigDataTable
                    data={Array.isArray(allDataScore) ? allDataScore : []}
                    selectedCompany={selectedCompany}
                    onCompanyChange={handleCompanyChange}
                  />

                  <AIStockTable
                    data={Array.isArray(allDataScore) ? allDataScore : []}
                    selectedCompany={selectedCompany}
                    onCompanyChange={handleCompanyChange}
                  />
                </div>
              }
            /> */}
            <Route
              path="/Table"
              element={
                <div>
                  <BigDataTable
                    data={bigTableData}
                    selectedCompany={selectedCompany}
                    onCompanyChange={handleCompanyChange}
                  />
                </div>
              }
            />
            <Route
              path="/portfolio"
              element={
                <ProtectedRoute>
                  <Portfolio />
                </ProtectedRoute>
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
