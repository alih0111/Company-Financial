import { getAuthStatus, sessionHeaders } from "../hooks/useGetUser";
import { apiFetch } from "../utils/request";
import { useCallback, useEffect, useState } from "react";
import { FaSyncAlt } from "react-icons/fa";
import { API_BASE } from "../config";
import MonthlyFactorMixPlanner from "./MonthlyFactorMixPlanner";

type Row = {
  symbol: string; rank: number | null; score: number | null;
  previous_rank: number | null; previous_score: number | null;
  price_date: string; reason: string | null;
};
type Ranking = {
  date: string; market_date: string; computed_at_utc: string;
  previous_date: string | null; eligible_count: number; universe_count: number; rows: Row[];
};
const number = (value: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(value);
const date = (value: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(value.length === 10 ? `${value}T12:00:00Z` : value));
const headers = () => ({ ...sessionHeaders(), "Content-Type": "application/json" });

export default function CurrentFactorMixRanking() {
  const {isAdmin}=getAuthStatus();
  const [query,setQuery]=useState("");
  const [remoteTotal,setRemoteTotal]=useState(0);
  const [fetching,setFetching]=useState(false);
  const [ranking, setRanking] = useState<Ranking | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const readResponse = useCallback(async (response: Response) => {
    const body = await response.json();
    setRemoteTotal(Number(response.headers.get("X-Total-Count")||0));
    if (!response.ok) throw new Error(body.error || "دریافت رتبه‌بندی ناموفق بود.");
    if (body.ranking && (body.ranking.strategy_id !== "RFA-FactorMix-033-Q40-Buffer8-v1.0.0" || !Array.isArray(body.ranking.rows))) {
      throw new Error("نسخهٔ رتبه‌بندی FactorMix معتبر نیست.");
    }
    if ("ranking" in body) setRanking(body.ranking);
    setBusy(Boolean(body.running));
    if (body.refresh_error && !body.running) setError(body.refresh_error);
  }, []);

  const readUrl=`${API_BASE}/factormix/ranking${isAdmin?"":`?page=${page+1}&page_size=10&q=${encodeURIComponent(query)}`}`;
  useEffect(() => {
    const controller = new AbortController();
    setFetching(true);setError("");
    apiFetch(readUrl, { headers: headers(), cache: "no-store", signal: controller.signal })
      .then(readResponse).catch(e => { if (!controller.signal.aborted) setError(e.message); }).finally(()=>{if(!controller.signal.aborted)setFetching(false);});
    return () => controller.abort();
  }, [readResponse,readUrl]);

  useEffect(() => {
    if (!busy) return;
    const controller = new AbortController();
    const timer = window.setInterval(() => {
      apiFetch(readUrl, { headers: headers(), cache: "no-store", signal: controller.signal })
        .then(readResponse).catch(e => { if (!controller.signal.aborted) { setError(e.message); setBusy(false); } });
    }, isAdmin?2000:15000);
    return () => { window.clearInterval(timer); controller.abort(); };
  }, [busy, readResponse,readUrl,isAdmin]);

  async function refresh() {
    setBusy(true);
    setError("");
    try {
      const response = await apiFetch(`${API_BASE}/admin/factormix/ranking/refresh`, { method: "POST", headers: headers() });
      await readResponse(response);
      setPage(0);
    } catch (e) {
      setError(e instanceof Error ? e.message : "محاسبه ناموفق بود.");
      setBusy(false);
    }
  }

  const normalize = (value: string) => value.replace(/ي/g, "ی").replace(/ك/g, "ک").replace(/\s|\u200c/g, "");
  const rows = isAdmin ? ranking?.rows.filter(row => normalize(row.symbol).includes(normalize(search))) ?? [] : ranking?.rows ?? [];
  const pages = Math.max(1, Math.ceil((isAdmin?rows.length:remoteTotal) / 10));
  const currentPage = Math.min(page, pages - 1);
  const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 px-3 py-2 text-sm disabled:opacity-50 dark:border-slate-700";
  return <section className="rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700 dark:bg-slate-800/60">
    <div className="flex flex-wrap items-center justify-between gap-3">
      <h2 className="text-lg font-bold">امتیاز و رتبه‌بندی به‌روز FactorMix</h2>
      {isAdmin && <button className={button} onClick={refresh} disabled={busy}>
        <FaSyncAlt className={busy ? "animate-spin" : ""} size={12} />
        {busy ? "در حال محاسبه…" : "به‌روزرسانی امتیازها"}
      </button>}
    </div>
    <p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">{isAdmin?"بعد از پایان جمع‌آوری اطلاعات، امتیازها را به‌روز کنید.":"رتبه‌بندی ثبت‌شده به‌صورت صفحه‌ای ارائه می‌شود؛ به‌روزرسانی داده با مدیر است."}</p>
    {busy && <p role="status" className="mt-3 text-sm leading-7">در حال خواندن گزارش‌های مالی و فروش و محاسبهٔ عوامل مدل…</p>}
    {error && <p role="alert" className="mt-3 text-sm leading-7 text-rose-600 dark:text-rose-400">{error}</p>}
    {ranking ? <>
      <p className="mt-4 text-xs leading-7 text-slate-500">تاریخ ارزیابی {date(ranking.date)} · آخرین قیمت موجود {date(ranking.market_date)} · محاسبه‌شده در {new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran" }).format(new Date(ranking.computed_at_utc))}<br />{number(ranking.eligible_count)} نماد واجد شرایط از {number(ranking.universe_count)} نماد{ranking.previous_date ? ` · مقایسه با محاسبهٔ ${date(ranking.previous_date)}` : ""}</p>
      <form className="mt-4 flex items-end gap-2" onSubmit={event=>{event.preventDefault();setPage(0);setQuery(search);}}><label className="grid max-w-xs gap-2 text-xs">جست‌وجوی نماد<input maxLength={80} className="min-h-10 rounded-xl border border-slate-200 bg-transparent px-3 dark:border-slate-700" type="search" value={search} onChange={e => { setSearch(e.target.value); if(isAdmin)setPage(0); }} /></label><button className={button} disabled={fetching}>جست‌وجو</button></form>
      <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[650px] text-right text-sm">
        <thead><tr className="border-b text-xs text-slate-500">{["رتبه", "نماد", "امتیاز", "رتبهٔ قبلی", "تغییر امتیاز", "تاریخ قیمت / وضعیت"].map(label => <th key={label} className="p-3" scope="col">{label}</th>)}</tr></thead>
        <tbody>{(fetching?[]:isAdmin?rows.slice(currentPage * 10, (currentPage + 1) * 10):rows).map(row => <tr key={row.symbol} className="border-b border-slate-100 dark:border-slate-700">
          <td className="p-3">{row.rank === null ? "—" : number(row.rank)}</td><th scope="row" className="p-3">{row.symbol}</th>
          <td className="p-3 tabular-nums" dir="ltr">{row.score === null ? "—" : number(row.score, 4)}</td>
          <td className="p-3">{row.previous_rank === null ? "—" : number(row.previous_rank)}</td>
          <td className="p-3 tabular-nums" dir="ltr">{row.score === null || row.previous_score === null ? "—" : number(row.score - row.previous_score, 4)}</td>
          <td className="p-3 text-xs leading-7">{date(row.price_date)}{row.reason && <span className="block text-amber-700 dark:text-amber-400">{row.reason}</span>}</td>
        </tr>)}</tbody>
      </table></div>
      {fetching && <p role="status" className="mt-3 text-sm">در حال دریافت صفحه…</p>}
      {!fetching && !rows.length && <p className="mt-3 text-sm">نمادی پیدا نشد.</p>}
      <div className="mt-4 flex items-center gap-3 text-xs"><button className={button} disabled={fetching||currentPage === 0} onClick={() => setPage(currentPage - 1)}>قبلی</button><span>{number(currentPage + 1)} / {number(pages)}</span><button className={button} disabled={fetching||currentPage + 1 >= pages} onClick={() => setPage(currentPage + 1)}>بعدی</button></div>
    </> : !busy && !error && <p className="mt-4 text-sm text-slate-500">رتبه‌بندی هنوز آماده نشده است؛ مدیر باید اطلاعات را به‌روز کند.</p>}
    <MonthlyFactorMixPlanner ranking={ranking} busy={busy} />
  </section>;
}
