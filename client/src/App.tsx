import Sidebar from "./components/Sidebar";
import AppHeader from "./components/AppHeader";
import { ToastProvider } from "./components/Toast";
import { ConfirmProvider } from "./components/ConfirmDialog";
import ChartComponent from "./components/ChartComponent";
import PriceChart from "./components/PriceChart";
import ScoreBreakdown from "./components/ScoreBreakdown";
import useCompanyData from "./hooks/useCompanyData";
import ScriptModal from "./components/ScriptModal";
import { useDarkMode } from "./utils/theme";
import {
  FaChartBar,
  FaArrowUp,
  FaArrowDown,
  FaBullseye,
} from "react-icons/fa";
import DonutChartComponent from "./components/DonutChartComponent";
import { Routes, Route, useLocation, useNavigate, useSearchParams, Navigate } from "react-router-dom";
import ScriptFullModal from "./components/ScriptFullModal";
import ProtectedRoute from "./components/ProtectedRoute";
import NotFound from "./components/NotFound";
import { useCallback, useEffect, lazy, Suspense, useMemo, useState } from "react";
import {
  getAIStockSummary,
  collectBrsPrices,
  type AIStockMetric,
} from "./utils/api";
import { getAuthStatus } from "./hooks/useGetUser";

// صفحات سنگین lazy لود می‌شوند تا باندل اولیه سبک بماند
const Landing = lazy(() => import("./components/Landing"));
const Login = lazy(() => import("./components/Login"));
const Register = lazy(() => import("./components/Register"));
const BigDataTable = lazy(() => import("./components/BigDataTable"));
const Portfolio = lazy(() => import("./components/Portfolio"));
const FamilyAssets = lazy(() => import("./components/FamilyAssets"));
const ChatPage = lazy(() => import("./components/ChatPage"));

// لودر سطح صفحه برای Suspense
const PageLoader = () => (
  <div className="flex items-center justify-center min-h-[50vh]">
    <div className="flex items-center gap-3 text-gray-400 dark:text-gray-500">
      <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" fill="none" />
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
      </svg>
      <span className="text-sm font-medium">در حال بارگذاری…</span>
    </div>
  </div>
);

// روت مهمان: کاربر لاگین‌شده نباید login/register را ببیند
const GuestRoute = ({ children }: { children: React.ReactNode }) => {
  const { username } = getAuthStatus();
  return username ? <Navigate to="/dashboard" replace /> : <>{children}</>;
};

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
    refreshData,
    ...scriptModalProps
  } = useCompanyData();

  const [, setSearchParams] = useSearchParams();

  const navigate = useNavigate();
  const handleCompanyChange = (name: string) => {
    setSelectedCompany(name);
    setSearchParams({ companyname: name });
    navigate(`/dashboard?companyname=${encodeURIComponent(name || "")}`);
  };

  const location = useLocation();
  const isLanding = location.pathname === "/";
  const hideSidebar =
    location.pathname === "/login" || location.pathname === "/register";

  const { isAdmin, username } = getAuthStatus();

  const [sidebarOpen, setSidebarOpen] = useState(false);

  const pageTitle =
    location.pathname === "/Table"
      ? "غربال بازار"
      : location.pathname === "/chat"
        ? "دستیار سرمایه‌گذاری"
        : location.pathname === "/portfolio"
          ? "پورتفولیو"
          : location.pathname === "/assets"
            ? "دارایی خانواده"
            : selectedCompany
              ? selectedCompany
              : "داشبورد";

  const pageSubtitle =
    location.pathname === "/Table"
      ? "غربال و مقایسه‌ی همه‌ی شرکت‌های بازار"
      : location.pathname === "/chat"
        ? "گفت‌وگو و پیشنهاد سرمایه‌گذاری بر پایه‌ی داده‌های کمی"
        : location.pathname === "/assets"
          ? "سبد اشخاص، قیمت‌ها و اتصال کارگزاری"
          : location.pathname === "/portfolio"
            ? "دارایی‌های سهام"
            : undefined;

  const [collectingPrice, setCollectingPrice] = useState(false);
  const [priceCollectMsg, setPriceCollectMsg] = useState<string | null>(null);

  const collectCompanyPrices = async () => {
    if (!selectedCompany) return;
    setCollectingPrice(true);
    setPriceCollectMsg(null);
    try {
      await collectBrsPrices("backfill", {
        symbol: selectedCompany,
        force: true,
      });
      setPriceCollectMsg("تاریخچه‌ی قیمت کامل شد ✓");
      handleDataCollected();
    } catch (e: any) {
      setPriceCollectMsg(e?.message || "خطا در جمع‌آوری قیمت");
    } finally {
      setCollectingPrice(false);
    }
  };

  useEffect(() => {
    if (location.pathname === "/") {
      document.title = "RFA | بینش شرکت‌ها";
    } else if (location.pathname === "/Table") {
      document.title = "RFA | غربال بازار";
    } else if (location.pathname === "/portfolio") {
      document.title = "RFA | پورتفولیو";
    } else if (location.pathname === "/assets") {
      document.title = "RFA | دارایی خانواده";
    } else if (location.pathname === "/login") {
      document.title = "RFA | ورود";
    } else if (location.pathname === "/register") {
      document.title = "RFA | ثبت‌نام";
    } else {
      document.title = selectedCompany ? `RFA | ${selectedCompany}` : "RFA | داشبورد";
    }
  }, [selectedCompany, location.pathname]);

  const [aiRows, setAiRows] = useState<Record<string, AIStockMetric>>({});
  const [priceRefreshTick, setPriceRefreshTick] = useState(0);

  const loadAIData = useCallback(async () => {
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
  }, []);

  const handleDataCollected = useCallback(() => {
    refreshData();
    loadAIData();
    setPriceRefreshTick((t) => t + 1);
  }, [refreshData, loadAIData]);

  useEffect(() => {
    loadAIData();
  }, [loadAIData]);

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

  const currentMetric = useMemo(() => {
    return Object.values(aiRows).find(
      (r) => r.company_name === selectedCompany,
    );
  }, [aiRows, selectedCompany]);

  const mainContent = loadingData ? (
    <div className="flex items-center justify-center h-full">
      <div className="flex items-center gap-3 text-gray-400 dark:text-gray-500">
        <svg className="animate-spin h-5 w-5" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
            fill="none"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
        <span className="text-sm font-medium">Loading company data...</span>
      </div>
    </div>
  ) : (
    <div className="flex flex-col gap-3">
      {/* ── Stats Summary Cards ── */}
      {currentMetric && (
        <div className="animate-fade-in-up grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            icon={<FaBullseye className="text-lg" />}
            label="Score"
            value={currentMetric.quant_score?.toFixed(1) ?? "--"}
            colorClass="text-indigo-600 dark:text-indigo-400"
            bgClass="bg-indigo-500/10 ring-indigo-500/20"
            glowClass="shadow-indigo-500/10"
          />
          <StatCard
            icon={<FaArrowUp className="text-lg" />}
            label="EPS Growth"
            value={
              currentMetric.net_profit_growth_4_reports != null
                ? `${currentMetric.net_profit_growth_4_reports.toFixed(1)}%`
                : "--"
            }
            colorClass={
              currentMetric.net_profit_growth_4_reports != null &&
              currentMetric.net_profit_growth_4_reports > 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-500 dark:text-red-400"
            }
            bgClass="bg-emerald-500/10 ring-emerald-500/20"
            glowClass="shadow-emerald-500/10"
          />
          <StatCard
            icon={<FaChartBar className="text-lg" />}
            label="Sales Growth"
            value={
              currentMetric.sales_growth_12m != null
                ? `${currentMetric.sales_growth_12m.toFixed(1)}%`
                : "--"
            }
            colorClass={
              currentMetric.sales_growth_12m != null &&
              currentMetric.sales_growth_12m > 0
                ? "text-emerald-600 dark:text-emerald-400"
                : "text-red-500 dark:text-red-400"
            }
            bgClass="bg-purple-500/10 ring-purple-500/20"
            glowClass="shadow-purple-500/10"
          />
          <StatCard
            icon={<FaArrowDown className="text-lg" />}
            label="P/E"
            value={
              currentMetric.pe_approx != null && currentMetric.pe_approx > 0
                ? currentMetric.pe_approx.toFixed(1)
                : "--"
            }
            colorClass="text-amber-600 dark:text-amber-400"
            bgClass="bg-amber-500/10 ring-amber-500/20"
            glowClass="shadow-amber-500/10"
          />
        </div>
      )}

      {/* ── EPS Chart + Donut ── */}
      <div className="animate-fade-in-up" style={{ animationDelay: "80ms" }}>
        {data1 ? (
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="sm:w-3/4">
              <ChartComponent data={data1} />
            </div>
            <div className="sm:w-1/4">
              {dataScore && (
                <DonutChartComponent score={dataScore[0].epsGrowth} />
              )}
            </div>
          </div>
        ) : (
          <p className="text-gray-400 dark:text-gray-500 text-sm">
            Loading chart data...
          </p>
        )}
      </div>

      {/* ── Sales Chart + Donut ── */}
      <div className="animate-fade-in-up" style={{ animationDelay: "160ms" }}>
        {data2 ? (
          <div className="flex flex-col sm:flex-row gap-3">
            <div className="sm:w-3/4">
              <ChartComponent data={data2} />
            </div>
            <div className="sm:w-1/4">
              {dataScore && (
                <DonutChartComponent score={dataScore[0].salesGrowth} />
              )}
            </div>
          </div>
        ) : (
          <p className="text-gray-400 dark:text-gray-500 text-sm">
            Loading chart data...
          </p>
        )}
      </div>

      {/* ── Price Chart ── */}
      {selectedCompany && (
        <div
          className="animate-fade-in-up min-h-[440px]"
          style={{ animationDelay: "240ms" }}
        >
          {isAdmin && (
            <div className="flex items-center gap-3 mb-2">
              <button
                onClick={collectCompanyPrices}
                disabled={collectingPrice}
                className={`text-xs font-medium px-3 py-1.5 rounded-xl transition-all duration-200 ${
                  collectingPrice
                    ? "bg-gray-300 dark:bg-gray-700 text-gray-500 dark:text-gray-400 cursor-not-allowed"
                    : "bg-gradient-to-r from-cyan-500 to-blue-600 hover:from-cyan-600 hover:to-blue-700 text-white shadow-sm hover:shadow-md hover:shadow-cyan-500/20"
                }`}
              >
                {collectingPrice
                  ? "در حال جمع‌آوری... (۱۵-۳۰ ثانیه)"
                  : "📥 جمع‌آوری کامل قیمت این نماد"}
              </button>
              {priceCollectMsg && (
                <span
                  className={`text-xs ${
                    priceCollectMsg.includes("✓")
                      ? "text-emerald-600 dark:text-emerald-400"
                      : "text-red-500"
                  }`}
                >
                  {priceCollectMsg}
                </span>
              )}
            </div>
          )}
          <PriceChart
            companyName={selectedCompany}
            refreshTick={priceRefreshTick}
          />
        </div>
      )}

      {/* ── Score Breakdown ── */}
      {selectedCompany && (
        <div className="animate-fade-in-up" style={{ animationDelay: "320ms" }}>
          <ScoreBreakdown metric={currentMetric} />
        </div>
      )}
    </div>
  );

  if (isLanding) {
    return (
      <div
        className={`min-h-screen ${
          darkMode ? "dark" : ""
        } bg-gradient-to-br from-gray-100 via-white to-gray-200 dark:from-gray-900 dark:via-gray-800 dark:to-gray-900 transition-colors duration-500`}
      >
        <Suspense fallback={<PageLoader />}>
          <Landing darkMode={darkMode} toggleDarkMode={toggleDarkMode} />
        </Suspense>
      </div>
    );
  }

  return (
    <ToastProvider>
      <ConfirmProvider>
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
                companyProfits={allDataScore ?? []}
                {...scriptModalProps}
                isAdmin={isAdmin}
                username={username}
                open={sidebarOpen}
                onClose={() => setSidebarOpen(false)}
                onDataCollected={handleDataCollected}
              />
            )}

            {!hideSidebar && sidebarOpen && (
              <div
                className="fixed inset-0 z-30 bg-black/40 backdrop-blur-sm lg:hidden"
                onClick={() => setSidebarOpen(false)}
              />
            )}

            <main className="flex-1 min-w-0 bg-white/50 dark:bg-gray-900/40 backdrop-blur-lg shadow-2xl shadow-emerald-500/5 transition-all duration-300 my-4 mx-[15px] p-4 rounded-3xl border border-gray-200/80 dark:border-gray-700/60">
              {!hideSidebar && (
                <AppHeader
                  title={pageTitle}
                  subtitle={pageSubtitle}
                  darkMode={darkMode}
                  toggleDarkMode={toggleDarkMode}
                  username={username}
                  isAdmin={isAdmin}
                  onMenuClick={() => setSidebarOpen(true)}
                />
              )}
              <Suspense fallback={<PageLoader />}>
                <Routes>
                  <Route
                    path="/login"
                    element={
                      <GuestRoute>
                        <Login />
                      </GuestRoute>
                    }
                  />
                  <Route
                    path="/register"
                    element={
                      <GuestRoute>
                        <Register />
                      </GuestRoute>
                    }
                  />
                  <Route
                    path="/dashboard"
                    element={<ProtectedRoute>{mainContent}</ProtectedRoute>}
                  />
                  <Route
                    path="/Table"
                    element={
                      <ProtectedRoute>
                        <BigDataTable data={bigTableData} />
                      </ProtectedRoute>
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
                  <Route
                    path="/chat"
                    element={
                      <ProtectedRoute>
                        <ChatPage />
                      </ProtectedRoute>
                    }
                  />
                  <Route
                    path="/assets"
                    element={
                      isAdmin ? (
                        <ProtectedRoute>
                          <FamilyAssets />
                        </ProtectedRoute>
                      ) : (
                        <Navigate to="/dashboard" replace />
                      )
                    }
                  />
                  <Route path="*" element={<NotFound />} />
                </Routes>
              </Suspense>
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
        </div>
      </ConfirmProvider>
    </ToastProvider>
  );
};

// ── Stat Card Component ──
const StatCard: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  colorClass: string;
  bgClass: string;
  glowClass: string;
}> = ({ icon, label, value, colorClass, bgClass, glowClass }) => (
  <div
    className={`rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/40 backdrop-blur-sm p-4 shadow-md ${glowClass} hover:-translate-y-0.5 transition-all duration-200`}
  >
    <div className="flex items-center gap-3">
      <div
        className={`flex items-center justify-center w-10 h-10 rounded-xl ring-1 ${bgClass} ${colorClass}`}
      >
        {icon}
      </div>
      <div>
        <p className="text-[11px] font-medium text-gray-400 dark:text-gray-500 uppercase tracking-wide">
          {label}
        </p>
        <p className={`text-lg font-bold tabular-nums ${colorClass}`}>
          {value}
        </p>
      </div>
    </div>
  </div>
);

export default App;
