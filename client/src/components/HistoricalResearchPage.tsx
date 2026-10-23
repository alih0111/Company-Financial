import { lazy, Suspense } from "react";

const ResearchRankingPage = lazy(() => import("./ResearchRankingPage"));
const ResearchV11Results = lazy(() => import("./ResearchV11Results"));

export default function HistoricalResearchPage() {
  return <div className="space-y-4">
    <p className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-sm leading-6 text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">این بخش پژوهش تاریخی است؛ مدل منتخب برای ارزیابی آینده در تب جداگانهٔ «مدل منتخب و آینده» مشخص شده است.</p>
    <Suspense fallback={<div role="status" className="p-4 text-sm">در حال بارگذاری پژوهش تاریخی…</div>}>
      <ResearchRankingPage />
      <ResearchV11Results />
    </Suspense>
  </div>;
}
