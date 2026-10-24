import { lazy, Suspense } from "react";
import { Link, useLocation } from "react-router-dom";
import { FaArchive } from "react-icons/fa";

const CashRankingPage = lazy(() => import("./CashRankingPage"));
const ResearchHomePage = lazy(() => import("./ResearchHomePage"));
const QvtAnalysisPage = lazy(() => import("./QvtAnalysisPage"));
const HistoricalResearchPage = lazy(() => import("./HistoricalResearchPage"));

export default function RankingHubPage() {
  const { pathname } = useLocation();
  const archived = ["/ranking/legacy-cash", "/qvt", "/ranking/research"].includes(pathname);
  return <div dir="rtl" className="space-y-4">
    {archived && (
      <div className="animate-fade-in-up flex flex-wrap items-center gap-x-4 gap-y-2 rounded-2xl border border-amber-300/60 bg-gradient-to-l from-amber-50 to-orange-50/60 p-4 text-sm leading-7 text-amber-950 dark:border-amber-500/25 dark:from-amber-950/40 dark:to-orange-950/30 dark:text-amber-100">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-amber-500/15 text-amber-600 dark:text-amber-400 ring-1 ring-amber-500/25">
          <FaArchive size={14} />
        </span>
        <div className="min-w-0 flex-1">
          <Link to="/ranking?view=archive" className="font-bold underline decoration-amber-500/50 underline-offset-4 hover:decoration-amber-500">بازگشت به آرشیو رتبه‌بندی ←</Link>
          <p className="text-xs opacity-80">نمای آزمایشی / تاریخی · امتیازهای این صفحه رتبه‌بندی مدل منتخب P1 نیستند.</p>
        </div>
      </div>
    )}
    <Suspense fallback={<div role="status" className="flex items-center justify-center gap-3 p-10 text-sm text-gray-500 dark:text-gray-400">
      <span className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-500/20 border-t-emerald-500" />
      در حال بارگذاری…
    </div>}>
      {pathname === "/ranking/legacy-cash" ? <CashRankingPage /> : pathname === "/qvt" ? <QvtAnalysisPage /> : pathname === "/ranking/research" ? <HistoricalResearchPage /> : <ResearchHomePage />}
    </Suspense>
  </div>;
}
