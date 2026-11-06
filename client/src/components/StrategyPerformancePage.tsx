import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import StrategyPerformanceView from "./StrategyPerformanceView";
import { familyHistoryPrices, selectBenchmarkRows, validateBenchmarkSnapshot, validatePerformanceReport } from "./strategyPerformanceData.js";
import type { BenchmarkSnapshot } from "./strategyPerformanceData.js";
import { getFamilyHistory, getPriceHistory, type PriceHistoryRow } from "../utils/api";
import { getAuthStatus } from "../hooks/useGetUser";
import type { PerformanceReport } from "./factorMixTypes";

const reportUrl = `${import.meta.env.BASE_URL}strategies/factormix-033/performance/performance.json`;
const benchmarkUrl = `${import.meta.env.BASE_URL}strategies/factormix-033/performance/benchmarks.json`;

export default function StrategyPerformancePage() {
  const { isAdmin } = getAuthStatus();
  const [familyRows, setFamilyRows] = useState<{date:string;closing_price:number}[]>([]);
  const [familyStatus, setFamilyStatus] = useState("");
  const [report, setReport] = useState<PerformanceReport | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [loading, setLoading] = useState(true);
  const [indexRows, setIndexRows] = useState<PriceHistoryRow[]>([]);
  const [indexLoading, setIndexLoading] = useState(true);
  const [indexError, setIndexError] = useState("");
  const [goldRows, setGoldRows] = useState<PriceHistoryRow[]>([]);
  const [goldLoading, setGoldLoading] = useState(true);
  const [goldError, setGoldError] = useState("");
  const [snapshot, setSnapshot] = useState<BenchmarkSnapshot | null>(null);
  const [snapshotLoading, setSnapshotLoading] = useState(true);
  const historyStart = report?.cases.reduce((first,c)=>c.start<first ? c.start : first,report.cases[0].start) ?? "2022-03-26";
  const historyEnd = report?.cases[0].as_of ?? "2026-11-04";
  const definitions = useMemo(() => [
    { id: "index_toman", label: "شاخص کل · TSETMC / TEDPIX", color: "#0284c7", rows: selectBenchmarkRows(indexRows,snapshot?.series.index_toman.rows ?? [],historyStart,historyEnd) },
    { id: "mesghal_toman", label: "مثقال", color: "#d97706", rows: selectBenchmarkRows(goldRows,snapshot?.series.mesghal_toman.rows ?? [],historyStart,historyEnd) },
    ...(isAdmin ? [{ id: "family_toman", label: "دارایی خانواده · جمع کل", color: "#a855f7", maxAgeDays: 14, rows: familyRows }] : []),
  ], [indexRows, goldRows, snapshot, historyStart, historyEnd, familyRows, isAdmin]);

  useEffect(() => {
    if (!isAdmin) { setFamilyRows([]); setFamilyStatus(""); return; }
    let cancelled = false;
    setFamilyRows([]); setFamilyStatus("در حال دریافت جمع کل دارایی خانواده…");
    getFamilyHistory().then(history => {
      const rows = familyHistoryPrices(history);
      const anchor = rows.filter(r => r.date <= historyStart).slice(-1)[0];
      const age = anchor ? (Date.parse(historyStart) - Date.parse(anchor.date)) / 86400000 : Infinity;
      if (age > 14 || rows.filter(r => r.date >= historyStart && r.date <= historyEnd).length < 1) {
        throw new Error("تاریخچهٔ جمع کل دارایی خانواده برای مبنای ابتدای ۱۴۰۱ کافی نیست.");
      }
      if (!cancelled) { setFamilyRows(rows); setFamilyStatus(""); }
    }).catch((reason: unknown) => {
      if (!cancelled) setFamilyStatus(reason instanceof Error ? `خط دارایی خانواده: ${reason.message}` : "دریافت تاریخچهٔ دارایی خانواده ناموفق بود.");
    });
    return () => { cancelled = true; };
  }, [refresh, historyStart, historyEnd, isAdmin]);

  // A verified offline export keeps the full 1401 coverage available even when
  // an API response is short or an optional live service is unavailable.
  useEffect(() => {
    const controller=new AbortController();setSnapshotLoading(true);
    fetch(benchmarkUrl,{signal:controller.signal,cache:"no-store"}).then(async response=>{
      if (!response.ok) throw new Error("Benchmark snapshot unavailable");
      return validateBenchmarkSnapshot(await response.json());
    }).then(value=>{if(!controller.signal.aborted)setSnapshot(value);})
      .catch(()=>{if(!controller.signal.aborted)setSnapshot(null);})
      .finally(()=>{if(!controller.signal.aborted)setSnapshotLoading(false);});
    return ()=>controller.abort();
  },[refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError(""); setReport(null);
    fetch(reportUrl, { signal: controller.signal, cache: "no-store" })
      .then(async response => {
        if (!response.ok) throw new Error(`گزارش عملکرد در دسترس نیست (${response.status}).`);
        return validatePerformanceReport(await response.json());
      }).then(value => { if (!controller.signal.aborted) setReport(value); })
      .catch((reason: unknown) => { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : "گزارش عملکرد خوانده نشد."); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [refresh]);

  // Load the complete TEDPIX history from the same market-history API as gold.
  // The bundled chart snapshot starts in 1402 and cannot support a 1401 comparison.
  useEffect(() => {
    let cancelled = false;
    setIndexLoading(true); setIndexError(""); setIndexRows([]);
    getPriceHistory("شاخص کل", 5000).then(rows => {
      if (!Array.isArray(rows)) throw new Error("Invalid index history");
      if (!cancelled) setIndexRows(rows);
    }).catch(() => { if (!cancelled) setIndexError("دریافت تاریخچهٔ شاخص کل ناموفق بود."); })
      .finally(() => { if (!cancelled) setIndexLoading(false); });
    return () => { cancelled = true; };
  }, [refresh]);

  // Optional gold prices must never block the verified strategy report.
  useEffect(() => {
    let cancelled = false;
    setGoldLoading(true); setGoldError(""); setGoldRows([]);
    getPriceHistory("مثقال", 5000).then(rows => {
      if (!Array.isArray(rows)) throw new Error("Invalid gold history");
      if (!cancelled) setGoldRows(rows);
    }).catch(() => { if (!cancelled) setGoldError("دریافت تاریخچهٔ مثقال ناموفق بود؛ مقایسهٔ سبد و P1 و شاخص کل همچنان در دسترس است."); })
      .finally(() => { if (!cancelled) setGoldLoading(false); });
    return () => { cancelled = true; };
  }, [refresh]);

  if (error) return <main dir="rtl" className="space-y-4 rounded-2xl border border-rose-200 bg-rose-50 p-6 text-sm leading-8 text-rose-900 dark:bg-rose-950 dark:text-rose-100" role="alert"><h1 className="text-lg font-bold">گزارش عملکرد بارگذاری نشد</h1><p>{error}</p><div className="flex flex-wrap gap-4"><button className="underline" onClick={() => setRefresh(v => v+1)}>تلاش دوباره</button><Link className="underline" to="/strategy">بازگشت به سبد</Link></div></main>;
  if (!report) return <main dir="rtl" className="rounded-2xl border border-slate-200 bg-white py-20 text-center text-sm text-slate-500 dark:border-slate-700 dark:bg-slate-800" role="status">در حال خواندن گزارش عملکرد…</main>;
  return <StrategyPerformanceView report={report} familyStatus={familyStatus} loading={loading} onRefresh={() => setRefresh(v => v+1)} definitions={definitions} indexLoading={(indexLoading || snapshotLoading) && !definitions[0].rows.length} indexError={definitions[0].rows.length ? "" : indexError || (!snapshotLoading && !indexLoading ? "تاریخچهٔ کامل شاخص کل از ابتدای ۱۴۰۱ در دسترس نیست." : "")} goldLoading={(goldLoading || snapshotLoading) && !definitions[1].rows.length} goldError={definitions[1].rows.length ? "" : goldError || (!snapshotLoading && !goldLoading ? "تاریخچهٔ کامل مثقال از ابتدای ۱۴۰۱ در دسترس نیست." : "")} />;
}

