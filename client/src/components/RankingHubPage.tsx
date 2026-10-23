import { lazy, Suspense } from "react";
import { Link, useLocation } from "react-router-dom";

const CashRankingPage = lazy(() => import("./CashRankingPage"));
const ResearchHomePage = lazy(() => import("./ResearchHomePage"));
const QvtAnalysisPage = lazy(() => import("./QvtAnalysisPage"));
const HistoricalResearchPage = lazy(() => import("./HistoricalResearchPage"));

export default function RankingHubPage() {
  const { pathname } = useLocation();
  const archived = ["/ranking/legacy-cash", "/qvt", "/ranking/research"].includes(pathname);
  return <div dir="rtl" className="space-y-4">
    {archived && <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm leading-7 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
      <Link to="/ranking?view=archive" className="font-bold underline">بازگشت به آرشیو رتبه‌بندی ←</Link>
      <p>نمای آزمایشی / تاریخی · امتیازهای این صفحه رتبه‌بندی مدل منتخب P1 نیستند.</p>
    </div>}
    <Suspense fallback={<div role="status" className="p-5 text-sm">در حال بارگذاری…</div>}>
      {pathname === "/ranking/legacy-cash" ? <CashRankingPage /> : pathname === "/qvt" ? <QvtAnalysisPage /> : pathname === "/ranking/research" ? <HistoricalResearchPage /> : <ResearchHomePage />}
    </Suspense>
  </div>;
}
