import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { FaArrowDown, FaArrowUp, FaArrowLeft, FaCheckCircle, FaDownload, FaHistory, FaSyncAlt } from "react-icons/fa";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { FactorMixDashboard, FactorMixTrade } from "./factorMixTypes";

const base = `${import.meta.env.BASE_URL}strategies/factormix-033/`;
const n = (v: number, digits = 0) => new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(v);
const pct = (v: number) => new Intl.NumberFormat("fa-IR", { style: "percent", maximumFractionDigits: 1 }).format(v);
const day = (v: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeZone: "Asia/Tehran" }).format(new Date(`${v}T12:00:00Z`));
const instant = (v: string) => new Intl.DateTimeFormat("fa-IR", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tehran" }).format(new Date(v));
const tone = (v: number) => v < -0.5 ? "text-rose-600 dark:text-rose-400" : v > 0.5 ? "text-emerald-700 dark:text-emerald-400" : "text-slate-600 dark:text-slate-300";
const panel = "rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700/70 dark:bg-slate-800/60";
const button = "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium transition hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700";
const field = "min-h-10 min-w-0 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-900";
const blockNames: Record<string, string> = { growth: "رشد", profitability: "سودآوری", valuation: "ارزش‌گذاری", balance: "ترازنامه", momentum: "روند قیمت", risk: "ریسک و برگشت قیمت", acceleration: "شتاب تغییرات مالی", p1: "امتیاز P1" };

export function validFactorMixData(x: FactorMixDashboard) {
  if (x.schema_version !== 1 || x.strategy_id !== "RFA-FactorMix-033-Q40-Buffer8-v1.0.0" || x.mode !== "historical_replay" ||
      !x.integrity?.daily_nav_reproduced || !x.integrity.ledger_reconciled ||
      !Array.isArray(x.holdings) || !Array.isArray(x.trades) || !Array.isArray(x.path) || !x.path.length ||
      !Array.isArray(x.decisions) || !x.decisions.length || !x.policy_sha256?.match(/^[a-f0-9]{64}$/) ||
      !x.rankings?.decision?.rows?.length || !x.rankings.latest?.rows?.length ||
      x.rankings.decision.date !== x.decisions[x.decisions.length-1].date || x.rankings.latest.date !== x.as_of ||
      !Number.isFinite(x.nav_toman) || !Number.isFinite(x.cash_toman) || x.initial_toman !== 100_000_000 ||
      x.holdings.some(h => !Number.isFinite(h.market_value_toman) || !Number.isFinite(h.cost_basis_toman)) ||
      Math.abs(x.cash_toman + x.holdings.reduce((a, h) => a + h.market_value_toman, 0) - x.nav_toman) > 1 ||
      Math.abs(x.realized_pnl_toman + x.unrealized_pnl_toman - (x.nav_toman - x.initial_toman)) > 1 ||
      x.path[x.path.length-1]?.date !== x.as_of || Math.abs(x.path[x.path.length-1]!.nav_toman - x.nav_toman) > 1 ||
      !x.forward || x.forward.execution_enabled !== false || x.forward.holdings.length !== 0 || x.forward.trades.length !== 0) {
    throw new Error("گزارش سبد با نسخهٔ ثبت‌شده یا جمع حساب سازگار نیست. نمایش اعداد متوقف شد.");
  }
  return x;
}

function Metric({ label, value, note, positive }: { label: string; value: string; note?: string; positive?: boolean }) {
  return <article className="min-w-0 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-700/70 dark:bg-slate-800/60">
    <p className="text-xs text-slate-500 dark:text-slate-400">{label}</p>
    <p className={`mt-3 break-words text-xl font-black tabular-nums sm:text-2xl ${positive ? "text-emerald-700 dark:text-emerald-400" : ""}`}>{value}</p>
    {note && <p className="mt-2 text-xs leading-6 text-slate-500 dark:text-slate-400">{note}</p>}
  </article>;
}

function Downloads() {
  return <div className="flex flex-wrap gap-2">
    {[["دفتر معاملات", "trades.csv"], ["مسیر سرمایه", "nav.csv"], ["تصمیم‌ها", "decisions.csv"], ["قواعد و وزن‌ها", "strategy.locked.json"]].map(([label, file]) =>
      <a className={button} key={file} href={base + file} download><FaDownload size={11} />{label}</a>)}
  </div>;
}

function Portfolio({ data }: { data: FactorMixDashboard }) {
  const latest = data.decisions[data.decisions.length-1]!;
  return <div className="space-y-5">
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
      <Metric label="ارزش کل سبد تاریخی · تومان" value={n(data.nav_toman)} note={`شروع با ${n(data.initial_toman)} تومان در ${day(data.start)}`} />
      <Metric label="سود خالص تاریخی · تومان" value={n(data.nav_toman - data.initial_toman)} note={`بازده کل ${pct(data.metrics.total_return)} · پس از هزینه‌های مدل`} positive />
      <Metric label="وجه نقد مدل · تومان" value={n(data.cash_toman)} note={`${n(data.holdings.length)} نماد موجود · هدف ${n(data.policy.rules.target_names)} نماد`} />
      <Metric label="بیشترین افت سرمایه" value={pct(Math.abs(data.metrics.max_drawdown))} note="بیشترین فاصله از سقف قبلی در کل بازه" />
    </div>
    <section className={panel} aria-labelledby="holdings-title">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 id="holdings-title" className="text-lg font-bold">چه چیزهایی در سبد مانده؟</h2><p className="mt-1 text-xs leading-6 text-slate-500 dark:text-slate-400">ترکیب پایان {day(data.as_of)} · مبالغ به تومان</p></div>
        <span className="rounded-lg bg-slate-100 px-3 py-2 text-xs dark:bg-slate-900">آخرین تصمیم: {day(latest.date)}</span>
      </div>
      <p className="mt-4 rounded-xl bg-slate-50 px-3 py-2 text-xs leading-7 text-slate-600 dark:bg-slate-900/70 dark:text-slate-300">تعدادها «واحد شاخصی تعدیل‌شده» هستند. تعداد سهم واقعی کارگزاری از این بک‌تست به دست نمی‌آید. میانگین بهای تمام‌شده شامل هزینهٔ خرید است.</p>
      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[1050px] text-right text-sm">
          <caption className="sr-only">دارایی‌های تاریخی FactorMix-033 تا {day(data.as_of)}</caption>
          <thead><tr className="border-b border-slate-200 text-xs text-slate-500 dark:border-slate-700 dark:text-slate-400">{["نماد / وضعیت", "واحد شاخصی", "میانگین بها", "بهای مانده", "قیمت / تاریخ", "ارزش روز / وزن", "سود و زیان باز"].map(s => <th className="px-3 py-3 font-medium" key={s} scope="col">{s}</th>)}</tr></thead>
          <tbody>{data.holdings.map(h => <tr className="border-b border-slate-100 last:border-0 dark:border-slate-700/50" key={h.symbol}>
            <th className="px-3 py-4" scope="row"><span className="font-bold">{h.symbol}</span><span className={`mt-1 block text-xs font-normal ${h.action === "HOLD" ? "text-emerald-700 dark:text-emerald-400" : "text-amber-700 dark:text-amber-300"}`}>{h.action === "HOLD" ? "نگهداری در سبد هدف" : "خروج کامل نشده"}</span><small className="mt-1 block font-normal text-slate-500">رتبهٔ تصمیم: {h.decision_rank == null ? "فاقد شرایط" : n(h.decision_rank)}</small></th>
            <td className="px-3 tabular-nums">{n(h.index_units, 3)}</td><td className="px-3 tabular-nums">{n(h.average_cost_toman, 2)}</td><td className="px-3 tabular-nums">{n(h.cost_basis_toman)}</td>
            <td className="px-3 tabular-nums">{n(h.last_index_price_toman, 2)}<span className={`mt-1 block text-xs ${h.price_age_days > 0 ? "text-amber-700 dark:text-amber-300" : "text-slate-500"}`}>{day(h.price_date)}{h.price_age_days > 0 ? ` · ${n(h.price_age_days)} روز قدیمی‌تر` : ""}</span></td>
            <td className="px-3 font-semibold tabular-nums">{n(h.market_value_toman)}<span className="mt-1 block text-xs font-normal text-slate-500">{pct(h.weight)} سبد</span></td>
            <td className={`px-3 font-semibold tabular-nums ${tone(h.unrealized_pnl_toman)}`}>{n(h.unrealized_pnl_toman)}<span className="mt-1 block text-xs font-normal">{pct(h.unrealized_pnl_toman / h.cost_basis_toman)}</span></td>
          </tr>)}</tbody>
        </table>
      </div>
      <div className="mt-4 flex flex-wrap justify-between gap-2 border-t border-slate-100 pt-4 text-xs leading-7 dark:border-slate-700"><p>نقد {n(data.cash_toman)} + دارایی {n(data.nav_toman - data.cash_toman)} = کل سبد {n(data.nav_toman)} تومان</p><span className="inline-flex items-center gap-1 text-emerald-700 dark:text-emerald-400"><FaCheckCircle />جمع حساب تطبیق داده شده</span></div>
      {data.holdings.some(h => h.action === "EXIT_UNFILLED") && <p className="mt-3 rounded-xl bg-amber-50 p-3 text-xs leading-7 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200">تعداد واقعی موقعیت‌های مدل از هدف پنج سهم بیشتر شده، چون فروش سهم خارج‌شده از سبد هدف اجرا نشده است. ارزش ثبت‌شدهٔ سبد، وجه نقد قابل برداشت فوری نیست.</p>}
    </section>
    <div className="grid gap-4 xl:grid-cols-2">
      <section className={panel}><h2 className="font-bold">آخرین تصمیم و سفارش‌های باقی‌مانده</h2>
        <p className="mt-2 text-xs leading-7 text-slate-500">تصمیم بعد از پایان {day(latest.date)} · اولین امکان اجرا جلسهٔ بعد</p>
        <div className="mt-3 flex flex-wrap gap-2">{latest.targets.map(t => <span key={t.symbol} className="rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-200">{t.symbol}<small className="ms-2 opacity-70">رتبهٔ {n(t.rank)} · {pct(t.weight)}</small></span>)}</div>
        <Link to="/strategy?tab=ranking" className="mt-3 inline-block text-xs font-semibold text-emerald-700 underline underline-offset-4 dark:text-emerald-400">مشاهدهٔ جدول رتبه‌بندی مبنای انتخاب ←</Link>
        {data.orders.length ? <ul className="mt-4 space-y-3">{data.orders.map(o => <li key={`${o.symbol}-${o.side}`} className="rounded-xl border border-amber-200 p-3 text-sm leading-7 dark:border-amber-900"><b>{o.side === "SELL" ? "فروش" : "خرید"} {o.symbol}</b><span className="ms-2 text-xs text-amber-700 dark:text-amber-300">{o.status === "EXPIRED" ? "مهلت گذشته؛ اجرا نشده" : "در انتظار اجرای مدل"}</span><p className="text-xs text-slate-500">{n(o.eligible_sessions_observed)} جلسه از مهلت {n(o.lifetime_sessions)} جلسه در دادهٔ موجود گذشته است. {o.reason === "NO_TRADABLE_OPEN" ? "قیمت بازگشایی قابل معامله موجود نبوده است." : o.reason === "ONE_PRICE_BAR" ? "روز تک‌قیمت طبق قاعدهٔ مدل کنار گذاشته شده است." : "محدودیت نقد یا ظرفیت اجرا باقی مانده است."}</p></li>)}</ul> : <p className="mt-4 text-sm text-slate-500">سفارش بازی در پایان داده ثبت نشده است.</p>}
        <p className="mt-4 text-xs leading-7 text-slate-500">موعد تقویمی بعدی پس از این داده: {day(data.next_nominal_review)}؛ اجرا وابسته به جلسهٔ قابل معامله و دادهٔ معتبر است.</p>
      </section>
      <section className={panel}><h2 className="font-bold">سود و هزینه‌ها از کجا آمده؟</h2>
        <dl className="mt-4 space-y-3 text-sm">{[["سود / زیان بسته‌شده", data.realized_pnl_toman], ["سود / زیان باز", data.unrealized_pnl_toman], ["جمع کارمزدهای مدل", data.fees_toman], ["جمع اثر لغزش قیمت", data.slippage_toman]].map(([label, value]) => <div className="flex flex-wrap justify-between gap-2" key={String(label)}><dt className="text-slate-500 dark:text-slate-400">{label}</dt><dd className="font-semibold tabular-nums">{n(Number(value))} تومان</dd></div>)}</dl>
        <p className="mt-5 text-xs leading-7 text-slate-500">کارمزد و لغزش قبلاً در معاملات و بازده منظور شده‌اند. سود بسته‌شده بر اساس میانگین موزون بهای تمام‌شده محاسبه می‌شود.</p>
      </section>
    </div>
  </div>;
}

function Forward({ data }: { data: FactorMixDashboard }) {
  const f = data.forward;
  return <div className="space-y-5">
    <section className={`${panel} border-emerald-200 dark:border-emerald-900`}>
      <span className="rounded-full bg-amber-100 px-3 py-1 text-xs font-bold text-amber-900 dark:bg-amber-950 dark:text-amber-200">{f.status === "NOT_STARTED" ? "حساب شروع نشده" : "حساب ثبت شده · منتظر دادهٔ تازهٔ مدل"}</span>
      <h2 className="mt-4 text-xl font-black">پیگیری مستقل از زمان ثبت حساب</h2>
      <p className="mt-3 max-w-3xl text-sm leading-8 text-slate-600 dark:text-slate-300">این حساب با سرمایهٔ مستقل شروع می‌شود. هنوز خرید یا فروشی برای آن ثبت نشده است. خریدهای سال‌های گذشته و سود بک‌تست وارد این حساب نمی‌شوند.</p>
      {f.started_at_utc && <p className="mt-2 text-xs text-slate-500">زمان ثبت: {instant(f.started_at_utc)}</p>}
    </section>
    <div className="grid grid-cols-2 gap-3 xl:grid-cols-4"><Metric label="سرمایهٔ اولیه · تومان" value={f.initial_toman == null ? "—" : n(f.initial_toman)} /><Metric label="نقد ثبت‌شده · تومان" value={f.cash_toman == null ? "—" : n(f.cash_toman)} /><Metric label="تعداد دارایی" value={n(f.holdings.length)} /><Metric label="معاملهٔ ثبت‌شده" value={n(f.trades.length)} /></div>
    <section className={panel}><h2 className="font-bold">چرا هنوز سهمی نخریده؟</h2><p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">آخرین دادهٔ آمادهٔ همین مدل مربوط به {day(data.as_of)} و پیش از شروع حساب است. برای ثبت خرید فرضی، اتصال ورودی تازهٔ FactorMix، ثبت تصمیم پس از شروع و شواهد جلسهٔ بعد لازم است. اجرای سفارش و به‌روزرسانی خودکار این حساب هنوز فعال نشده‌اند.</p><p className="mt-3 text-xs leading-7 text-slate-500">«بازخوانی گزارش» آخرین گزارش ذخیره‌شده را می‌خواند و خریدوفروش ایجاد نمی‌کند. دریافت اطلاعات مدل‌های دیگر نیز این حساب را تغییر نمی‌دهد.</p></section>
    <section className={panel}><h2 className="font-bold">دفتر ثبت حساب</h2>{f.events.length ? <ol className="mt-4 space-y-3">{f.events.map(e => <li className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-50 p-4 text-sm dark:bg-slate-900/60" key={e.id}><span className="inline-flex items-center gap-2"><FaCheckCircle className="text-emerald-600" />ثبت حساب مستقل با {n(f.initial_toman!)} تومان نقد</span><time dateTime={e.at_utc} className="text-xs text-slate-500">{instant(e.at_utc)}</time></li>)}</ol> : <p className="mt-3 text-sm text-slate-500">رویدادی ثبت نشده است.</p>}<a className={`${button} mt-4`} href={base + "forward.json"} download><FaDownload size={11} />دریافت وضعیت و دفتر حساب</a></section>
  </div>;
}

function Ranking({ data }: { data: FactorMixDashboard }) {
  const [snapshot, setSnapshot] = useState<"decision" | "latest">("decision");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const ranking = data.rankings[snapshot];
  const normalize = (s: string) => s.replace(/ي/g,"ی").replace(/ك/g,"ک").replace(/\s|\u200c/g,"");
  const rows = ranking.rows.filter(r => normalize(r.symbol).includes(normalize(search)));
  const pageCount = Math.max(1, Math.ceil(rows.length / 20));
  const current = Math.min(page,pageCount-1);
  const last = data.decisions[data.decisions.length-1];
  return <div className="space-y-5">
    <section className={panel}>
      <h2 className="text-lg font-bold">سبد از کدام رتبه‌بندی انتخاب شده؟</h2>
      <p className="mt-3 text-sm leading-8 text-slate-600 dark:text-slate-300">آخرین انتخاب در پایان {day(last.date)} با امتیاز خودِ FactorMix-033 انجام شده است. پنج نماد هدف در آن تصمیم عبارت‌اند از:</p>
      <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-5">{last.targets.map(t => <div key={t.symbol} className="rounded-xl bg-emerald-50 p-3 dark:bg-emerald-950/50"><p className="text-xs text-emerald-700 dark:text-emerald-300">رتبهٔ {n(t.rank)}</p><p className="mt-1 font-bold">{t.symbol}</p><p className="mt-1 text-xs text-slate-500">وزن هدف {pct(t.weight)}</p></div>)}</div>
      <p className="mt-4 text-xs leading-7 text-slate-500">این رتبه‌بندی با جدول P1 در صفحهٔ «رتبه‌بندی» فرق دارد. سهم‌های موجود تا رتبهٔ ۸ اولویت نگهداری دارند؛ در این تصمیم، پنج سهم هدف همان رتبه‌های ۱ تا ۵ بوده‌اند. اجراهای خرید آن‌ها در {day(data.trades.find(t=>t.decision===last.date && t.side==="BUY")!.session)} ثبت شده‌اند.</p>
    </section>
    <section className={panel}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div><h2 className="text-lg font-bold">رتبه‌بندی FactorMix-033</h2><p className="mt-2 text-xs leading-7 text-slate-500">بازمحاسبهٔ تاریخی با همان وزن‌های نسخهٔ ۱٫۰٫۰ · رتبه فقط میان نمادهای واجد شرایط</p></div>
        <a className={button} href={base+`ranking-${snapshot}.csv`} download><FaDownload size={11} />دریافت همین رتبه‌بندی</a>
      </div>
      <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="تاریخ رتبه‌بندی">
        {(["decision","latest"] as const).map(key => <button key={key} aria-pressed={snapshot===key} className={`${button} ${snapshot===key ? "!border-emerald-500 !bg-emerald-50 !text-emerald-800 dark:!bg-emerald-950 dark:!text-emerald-200" : ""}`} onClick={()=>{setSnapshot(key);setPage(0);}}>{key==="decision" ? "مبنای آخرین انتخاب سبد" : "آخرین دادهٔ موجود"} · {day(data.rankings[key].date)}</button>)}
      </div>
      <div className="mt-4 rounded-xl bg-slate-50 p-3 text-xs leading-7 text-slate-600 dark:bg-slate-900/60 dark:text-slate-300"><p>تاریخ محاسبهٔ امتیاز: <b>{day(ranking.date)}</b> · تاریخ آخرین snapshot مالی: {day(ranking.financial_snapshot_date)}</p><p>{n(ranking.eligible_count)} نماد واجد شرایط از جهان {n(ranking.universe_count)} نماد؛ {n(ranking.excluded_count)} نماد به‌دلیل شرایط امتیاز، قیمت یا عمر داده در رتبه‌بندی اجرا وارد نشده‌اند.</p><p>{snapshot==="decision" ? "این جدول مستقیماً مبنای آخرین تصمیم سبد بوده است." : "این جدول وضعیت آخرین داده را نشان می‌دهد؛ تصمیم و خرید تازه‌ای برای سبد ایجاد نمی‌کند و رتبه‌بندی امروز نیست."}</p></div>
      <label className="mt-4 grid max-w-xs gap-2 text-xs">جست‌وجوی نماد<input className={field} type="search" placeholder="مثلاً شمواد" value={search} onChange={e=>{setSearch(e.target.value);setPage(0);}} /></label>
      <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[650px] text-right text-sm"><caption className="sr-only">رتبه‌بندی FactorMix-033 در {day(ranking.date)}</caption><thead><tr className="border-b text-xs text-slate-500 dark:border-slate-700">{["رتبه", "نماد", "امتیاز مدل", "انتخاب در آخرین تصمیم", "موجودی در پایان داده"].map(h=><th key={h} className="p-3 font-medium" scope="col">{h}</th>)}</tr></thead><tbody>{rows.slice(current*20,current*20+20).map(r=><tr key={r.symbol} className={`border-b border-slate-100 last:border-0 dark:border-slate-700/50 ${r.selected_in_last_decision ? "bg-emerald-50/50 dark:bg-emerald-950/20" : ""}`}><td className="p-3 tabular-nums">{n(r.rank)}</td><th scope="row" className="p-3">{r.symbol}</th><td className="p-3 tabular-nums" dir="ltr">{n(r.score,4)}</td><td className="p-3 text-xs">{r.selected_in_last_decision ? <span className="text-emerald-700 dark:text-emerald-400">در سبد هدف {day(last.date)}</span> : "خارج از سبد هدف"}</td><td className="p-3 text-xs">{r.held_at_portfolio_end ? (r.selected_in_last_decision ? "خرید ثبت‌شده / موجود" : <span className="text-amber-700 dark:text-amber-300">موجود؛ خروج اجرا نشده</span>) : "در سبد نیست"}</td></tr>)}</tbody></table></div>
      {!rows.length && <p className="py-10 text-center text-sm text-slate-500">نمادی با این جست‌وجو در فهرست واجد شرایط نیست.</p>}
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">{n(rows.length)} نتیجه · صفحهٔ {n(current+1)} از {n(pageCount)}</p><div className="flex gap-2"><button className={button} disabled={!current} onClick={()=>setPage(current-1)}>قبلی</button><button className={button} disabled={current+1>=pageCount} onClick={()=>setPage(current+1)}>بعدی</button></div></div>
      <p className="mt-4 text-xs leading-7 text-slate-500">امتیاز، جمع وزن‌دار بلوک‌های همین مدل است و درصد سود پیش‌بینی‌شده نیست. تغییر رتبه بین دو تاریخ، سفارش قبلی را خودکار لغو یا سبد را بازچینی نمی‌کند؛ بازبینی در موعد استراتژی انجام می‌شود.</p>
    </section>
  </div>;
}

function Transactions({ data }: { data: FactorMixDashboard }) {
  const [symbol, setSymbol] = useState(""); const [side, setSide] = useState("");
  const [from, setFrom] = useState(""); const [to, setTo] = useState(""); const [page, setPage] = useState(0);
  const symbols = useMemo(() => [...new Set(data.trades.map(t => t.symbol))].sort((a,b) => a.localeCompare(b,"fa")), [data.trades]);
  const rows = useMemo(() => data.trades.filter(t => (!symbol || t.symbol === symbol) && (!side || t.side === side) && (!from || t.session >= from) && (!to || t.session <= to)).slice().reverse(), [data.trades, symbol, side, from, to]);
  const pages = Math.max(1, Math.ceil(rows.length / 15)); const current = Math.min(page, pages-1);
  const change = (setter: (v: string) => void, value: string) => { setter(value); setPage(0); };
  return <section className={panel}>
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-bold">دفتر خرید و فروش تاریخی</h2><p className="mt-2 text-xs text-slate-500">{n(data.trades.length)} اجرای ثبت‌شده · جدیدترین اجرا در ابتدا · تمام مبالغ به تومان</p></div><a href={base+"trades.csv"} download className={button}><FaDownload size={11} />تمام معاملات CSV</a></div>
    <div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <label className="grid gap-2 text-xs">نماد<select className={field} value={symbol} onChange={e => change(setSymbol,e.target.value)}><option value="">همهٔ نمادها</option>{symbols.map(s => <option key={s}>{s}</option>)}</select></label>
      <label className="grid gap-2 text-xs">عملیات<select className={field} value={side} onChange={e => change(setSide,e.target.value)}><option value="">خرید و فروش</option><option value="BUY">خرید</option><option value="SELL">فروش</option></select></label>
      <label className="grid gap-2 text-xs">از تاریخ میلادی<input type="date" className={field} value={from} onChange={e => change(setFrom,e.target.value)} /></label>
      <label className="grid gap-2 text-xs">تا تاریخ میلادی<input type="date" className={field} value={to} onChange={e => change(setTo,e.target.value)} /></label>
    </div>
    {from && to && from > to && <p role="alert" className="mt-3 text-sm text-amber-700">تاریخ شروع باید پیش از پایان باشد.</p>}
    <div className="mt-5 overflow-x-auto"><table className="w-full min-w-[1000px] text-right text-sm"><caption className="sr-only">معاملات تاریخی؛ تعدادها واحد شاخصی‌اند</caption><thead><tr className="border-b text-xs text-slate-500 dark:border-slate-700">{["اجرا / تصمیم", "نماد", "عملیات", "واحد شاخصی", "قیمت مبنا", "مبلغ ناخالص", "کارمزد", "اثر بر نقد", "نقد پس از اجرا"].map(s => <th className="p-3 font-medium" scope="col" key={s}>{s}</th>)}</tr></thead><tbody>{rows.slice(current*15, current*15+15).map((t: FactorMixTrade) => <tr key={t.id} className="border-b border-slate-100 last:border-0 dark:border-slate-700/50"><td className="p-3 text-xs">{day(t.session)}<span className="mt-1 block text-slate-500">تصمیم {day(t.decision)}</span></td><th scope="row" className="p-3">{t.symbol}</th><td className="p-3"><span className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs ${t.side === "BUY" ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300" : "bg-rose-50 text-rose-800 dark:bg-rose-950 dark:text-rose-300"}`}>{t.side === "BUY" ? <FaArrowDown size={9} /> : <FaArrowUp size={9} />}{t.side === "BUY" ? "خرید" : "فروش"}</span></td><td className="p-3 tabular-nums">{n(t.units,3)}</td><td className="p-3 tabular-nums">{n(t.index_price,2)}</td><td className="p-3 tabular-nums">{n(t.gross_toman)}</td><td className="p-3 tabular-nums">{n(t.fee_toman)}</td><td className="p-3 tabular-nums">{n(t.cash_delta_toman)}</td><td className="p-3 tabular-nums">{n(t.cash_after_toman)}</td></tr>)}</tbody></table></div>
    {!rows.length && <p className="py-10 text-center text-sm text-slate-500">معامله‌ای با این فیلترها ثبت نشده است.</p>}
    <div className="mt-4 flex flex-wrap items-center justify-between gap-3"><p className="text-xs text-slate-500">{n(rows.length)} نتیجه · صفحهٔ {n(current+1)} از {n(pages)}</p><div className="flex gap-2"><button className={button} disabled={!current} onClick={() => setPage(current-1)}>قبلی</button><button className={button} disabled={current+1>=pages} onClick={() => setPage(current+1)}>بعدی</button></div></div>
    <p className="mt-4 text-xs leading-7 text-slate-500">قیمت مبنا، قیمت واحد شاخصی پیش از لغزش است. مبلغ ناخالص لغزش را دارد؛ اثر بر نقد شامل کارمزد است. این دفتر مربوط به بک‌تست است.</p>
  </section>;
}

export function Performance({ data }: { data: FactorMixDashboard }) {
  return <div className="space-y-5">
    <section className={panel}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-lg font-bold">مسیر همان ۱۰۰ میلیون تومان</h2><p className="mt-2 text-xs text-slate-500">{day(data.start)} تا {day(data.as_of)} · هر دو مدل با بازه، سرمایه و فرض‌های اجرای یکسان</p></div><div className="flex gap-4 text-xs"><span className="text-emerald-600">● FactorMix-033</span><span className="text-slate-500">● مدل قبلی P1</span></div></div>
      <div className="mt-6 h-72 w-full sm:h-80" dir="ltr" aria-label="نمودار ارزش سبد تاریخی و مدل قبلی"><ResponsiveContainer width="100%" height="100%"><LineChart data={data.path} margin={{top:10,right:12,left:0,bottom:10}}><CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#94a3b8" opacity={0.15} /><XAxis dataKey="date" minTickGap={65} tick={{fontSize:10,fill:"#64748b"}} tickFormatter={d => new Intl.DateTimeFormat("fa-IR",{year:"numeric",month:"short"}).format(new Date(`${d}T12:00:00Z`))} /><YAxis width={70} tick={{fontSize:10,fill:"#64748b"}} tickFormatter={v => n(v/1e6)} /><Tooltip contentStyle={{borderRadius:12,direction:"rtl",fontFamily:"inherit",background:"#fff",color:"#0f172a"}} labelFormatter={v => day(String(v))} formatter={(v: number, name: string) => [`${n(v)} تومان`, name === "nav_toman" ? "FactorMix-033" : "مدل قبلی P1"]} /><Line dataKey="baseline_toman" stroke="#94a3b8" dot={false} strokeWidth={1.7} isAnimationActive={false} /><Line dataKey="nav_toman" stroke="#059669" dot={false} strokeWidth={2.5} isAnimationActive={false} /></LineChart></ResponsiveContainer></div><p className="text-xs text-slate-500">محور عمودی: میلیون تومان</p>
    </section>
    <div className="grid gap-3 sm:grid-cols-3"><Metric label="FactorMix در پایان · تومان" value={n(data.nav_toman)} note={`بازده کل ${pct(data.metrics.total_return)}`} /><Metric label="مدل قبلی در همان تاریخ · تومان" value={n(data.baseline.final_toman)} note={`بازده کل ${pct(data.baseline.total_return)}`} /><Metric label="اختلاف ارزش پایان · تومان" value={n(data.nav_toman-data.baseline.final_toman)} note="این تفاوت تاریخی، تضمین برتری آینده نیست" positive /></div>
    <section className={panel}><h2 className="font-bold">عملکرد سال‌های شمسی</h2><div className="mt-3 overflow-x-auto"><table className="w-full min-w-[650px] text-right text-sm"><thead><tr className="border-b text-xs text-slate-500 dark:border-slate-700">{["سال", "آخرین داده", "سرمایهٔ آغاز · تومان", "سرمایهٔ پایان · تومان", "بازده"].map(s => <th key={s} className="p-3" scope="col">{s}</th>)}</tr></thead><tbody>{data.annual.map(y => <tr key={y.year} className="border-b border-slate-100 last:border-0 dark:border-slate-700/50"><th scope="row" className="p-3">{n(y.year)}{y.year === 1405 && <small className="ms-2 font-normal text-slate-500">تا آخرین داده</small>}</th><td className="p-3">{day(y.end)}</td><td className="p-3">{n(y.initial_toman)}</td><td className="p-3">{n(y.final_toman)}</td><td className={`p-3 ${tone(y.return_fraction)}`}>{pct(y.return_fraction)}</td></tr>)}</tbody></table></div></section>
    <p className="text-xs leading-7 text-slate-500">بخشی از این تاریخ در پژوهش و انتخاب مدل استفاده شده است. این بازپخش، نتیجهٔ آینده یا عملکرد حساب واقعی نیست. زمان دریافت تاریخی همهٔ گزارش‌ها و حسابداری تعداد سهم واقعی اثبات نشده‌اند.</p>
  </div>;
}

function Rules({ data }: { data: FactorMixDashboard }) {
  return <div className="space-y-5">
    <section className={panel}><h2 className="text-lg font-bold">قواعد نسخهٔ ثبت‌شده</h2><div className="mt-5 grid gap-3 sm:grid-cols-2 xl:grid-cols-3">{[["ترکیب هدف", "۵ نماد، هر کدام ۲۰٪"], ["قاعدهٔ نگهداری", "نگهداری سهم موجود تا رتبهٔ ۸"], ["بازبینی", "پایان فصل شمسی +۴۰ روز تقویمی"], ["اصلاح وزن", "در بازبینی، انحراف بیش از ۵ واحد درصد"], ["زمان اجرا", "تصمیم پس از بسته‌شدن؛ اجرای زودتر از جلسهٔ بعد ندارد"], ["مهلت سفارش", "۵ جلسهٔ قابل معامله"]].map(([a,b]) => <div className="rounded-xl bg-slate-50 p-4 dark:bg-slate-900/60" key={a}><p className="text-xs text-slate-500">{a}</p><p className="mt-2 text-sm font-semibold leading-7">{b}</p></div>)}</div><p className="mt-4 text-xs leading-7 text-slate-500">سهم‌های باقی‌مانده تا رتبهٔ ۸ اولویت نگهداری دارند؛ بنابراین سبد الزاماً همان پنج رتبهٔ اول هر روز نیست. جای خالی بدون سهم واجد شرایط، نقد می‌ماند.</p></section>
    <div className="grid gap-5 xl:grid-cols-2"><section className={panel}><h2 className="font-bold">وزن بلوک‌های امتیاز</h2><div className="mt-5 space-y-3">{Object.entries(data.policy.block_weights).sort((a,b)=>b[1]-a[1]).map(([key, weight]) => <div key={key}><div className="mb-1 flex justify-between text-xs"><span>{blockNames[key] ?? key}</span><span>{pct(weight)}</span></div><div className="h-1.5 rounded-full bg-slate-100 dark:bg-slate-700"><div className="h-1.5 rounded-full bg-emerald-500" style={{width:`${weight*100}%`}} /></div></div>)}</div></section>
    <section className={panel}><h2 className="font-bold">فرض‌های اجرا و منبع</h2><ul className="mt-4 list-inside list-disc space-y-3 text-sm leading-7 text-slate-600 dark:text-slate-300"><li>کارمزد هر سمت {pct(data.policy.execution.fee)}؛ لغزش هر سمت {pct(data.policy.execution.slippage)}.</li><li>ظرفیت روزانه حداکثر {pct(data.policy.execution.capacity)} میانهٔ ارزش معاملات ۲۰ رکورد قبلی است.</li><li>روزهای تک‌قیمت برای اجرای مدل کنار گذاشته شده‌اند.</li><li>قیمت و گزارش مالی باید محدودیت عمر داده را رعایت کنند.</li><li>پس از بخش تاریخی منجمد، روزهای بدون فعالیت قابل معامله در کل جهان ۲۵۴ نماد، جلسهٔ سهام شمرده نشده‌اند.</li></ul><p className="mt-4 text-xs leading-7 text-slate-500">داده‌ها از نسخهٔ بایگانی‌شده بررسی شده‌اند؛ مسیر روزانه و جمع حساب معاملات بازتولید و تطبیق داده شده‌اند. این مدل هنوز به اجرای سفارش واقعی متصل نیست.</p></section></div>
    <section className={panel}><h2 className="font-bold">تاریخچهٔ تصمیم‌ها</h2><div className="mt-4 space-y-3">{data.decisions.slice().reverse().map(d => <details className="rounded-xl border border-slate-200 p-3 dark:border-slate-700" key={d.date}><summary className="cursor-pointer text-sm font-semibold leading-7">{day(d.date)}<span className="ms-3 text-xs font-normal text-slate-500">{d.targets.map(t=>t.symbol).join("، ")} · {n(d.fill_count)} اجرا</span></summary><div className="mt-3 space-y-2 text-xs leading-7 text-slate-600 dark:text-slate-300"><p>تاریخ دادهٔ مالی امتیاز: {day(d.signal_date)}</p><p>ورودی‌های هدف: {d.entrants.join("، ") || "ندارد"}</p><p>خروج‌های هدف: {d.exits.join("، ") || "ندارد"}</p><p>تصمیم هدف با خریدوفروش انجام‌شده فرق دارد؛ اجرای واقعی مدل را در دفتر معاملات ببینید.</p></div></details>)}</div></section>
    <section className={panel}><div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="font-bold">ثبت و بازیابی نسخه</h2><p className="mt-2 text-xs leading-7 text-slate-500">نسخهٔ ۱٫۰٫۰ در Git و دو بستهٔ پشتیبان محلی ثبت شده است. {n(data.integrity.verified_files)} فایل منبع هنگام ساخت گزارش تطبیق داده شده‌اند. نسخهٔ بایگانی‌شده بازنویسی نمی‌شود.</p></div><span className="rounded-lg bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">تطبیق مسیر روزانه و دفتر: موفق</span></div><div className="mt-5"><Downloads /></div><details className="mt-5 text-xs text-slate-500"><summary className="cursor-pointer">شناسه و اثر انگشت نسخه</summary><p className="mt-3 break-all font-mono" dir="ltr">{data.strategy_id}<br />SHA-256: {data.policy_sha256}</p></details></section>
  </div>;
}

const tabs = [["portfolio", "سبد تاریخی"], ["ranking", "رتبه‌بندی همین مدل"], ["forward", "پیگیری جدید"], ["trades", "خرید و فروش"], ["performance", "عملکرد"], ["rules", "قواعد و نسخه"]];

export default function FactorMixPage() {
  const [params, setParams] = useSearchParams(); const selected = params.get("tab") ?? "portfolio";
  const tab = tabs.some(t => t[0] === selected) ? selected : "portfolio";
  const [data, setData] = useState<FactorMixDashboard | null>(null); const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0); const [loading, setLoading] = useState(true);
  useEffect(() => {
    const ctl = new AbortController(); setLoading(true); setError("");
    fetch(base + "dashboard.json", { signal: ctl.signal, cache: "no-store" }).then(async r => {
      if (!r.ok) throw new Error(`گزارش استراتژی در دسترس نیست (${r.status}).`);
      return validFactorMixData(await r.json());
    }).then(setData).catch(e => { if (!ctl.signal.aborted) { setData(null); setError(e instanceof Error ? e.message : "گزارش خوانده نشد."); } }).finally(() => { if (!ctl.signal.aborted) setLoading(false); });
    return () => ctl.abort();
  }, [refresh]);
  return <main dir="rtl" className="mx-auto max-w-[1500px] space-y-5 text-slate-800 dark:text-slate-100">
    <header className="flex flex-wrap items-start justify-between gap-4"><div><div className="flex flex-wrap items-center gap-2"><span className="text-xs font-bold tracking-wide text-emerald-700 dark:text-emerald-400" dir="ltr">FactorMix-033</span><span className="rounded-full border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 dark:border-slate-700 dark:text-slate-400">نسخهٔ ۱٫۰٫۰</span></div><h1 className="mt-2 text-2xl font-black sm:text-3xl">سبد استراتژی</h1><p className="mt-2 text-sm leading-7 text-slate-500 dark:text-slate-400">دارایی‌ها، تصمیم‌ها و مسیر سرمایه در یک جا</p></div><div className="flex flex-wrap gap-2"><button className={button} disabled={loading} onClick={() => setRefresh(x=>x+1)}><FaSyncAlt size={12} className={loading ? "animate-spin" : ""} />بازخوانی گزارش</button><Link className={button} to="/ranking">رتبه‌بندی<FaArrowLeft size={11} /></Link></div></header>
    {error ? <div role="alert" className="rounded-2xl border border-rose-200 bg-rose-50 p-5 text-sm leading-8 text-rose-900 dark:bg-rose-950 dark:text-rose-100"><p>{error}</p><button className={`${button} mt-3`} onClick={() => setRefresh(x=>x+1)}>تلاش دوباره</button></div> : !data ? <div role="status" className={`${panel} py-16 text-center text-sm text-slate-500`}>در حال خواندن دفتر استراتژی…</div> : <>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl bg-slate-100 px-4 py-3 text-xs leading-7 text-slate-600 dark:bg-slate-800 dark:text-slate-300"><p className="inline-flex items-center gap-2"><FaHistory className="shrink-0" /><span><b>دادهٔ تاریخی تا {day(data.as_of)}</b> · سبد کارگزاری یا قیمت لحظه‌ای نیست</span></p><span>آخرین ساخت گزارش: {instant(data.generated_at_utc)}</span></div>
      <nav aria-label="بخش‌های سبد استراتژی" className="flex flex-wrap gap-1 rounded-2xl border border-slate-200 bg-white p-1.5 dark:border-slate-700 dark:bg-slate-800/60">{tabs.map(([id,label]) => <button key={id} aria-current={tab===id ? "page" : undefined} onClick={() => setParams(p=>{const q=new URLSearchParams(p);q.set("tab",id);return q;})} className={`min-h-10 flex-1 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-semibold transition sm:flex-none sm:px-5 ${tab===id ? "bg-emerald-600 text-white shadow-sm" : "text-slate-500 hover:bg-slate-50 dark:text-slate-300 dark:hover:bg-slate-700"}`}>{label}</button>)}</nav>
      {tab==="portfolio" ? <Portfolio data={data} /> : tab==="ranking" ? <Ranking data={data} /> : tab==="forward" ? <Forward data={data} /> : tab==="trades" ? <Transactions data={data} /> : tab==="performance" ? <div className="space-y-4"><div className="flex flex-wrap items-center justify-between gap-3 rounded-xl bg-slate-100 p-4 text-xs leading-7 dark:bg-slate-800"><p>نمای زیر حساب شروع ۱۴۰۲ است. نتیجهٔ جدیدِ شروع ۱۴۰۱ و نمودارهای کامل هر دو بازه در صفحهٔ عملکرد قرار دارند.</p><Link className={button} to="/strategy/performance">عملکرد کامل · شروع ۱۴۰۱ یا ۱۴۰۲<FaArrowLeft size={11} /></Link></div><Performance data={data} /></div> : <Rules data={data} />}
      <footer className="flex flex-wrap justify-between gap-2 border-t border-slate-200 pt-4 text-[11px] leading-7 text-slate-500 dark:border-slate-700"><span>FactorMix-033 · نسخهٔ ثبت‌شدهٔ ۱٫۰٫۰ · ارقام پولی به تومان</span><span>بازخوانی صفحه فقط گزارش ذخیره‌شده را می‌خواند.</span></footer>
    </>}
  </main>;
}
