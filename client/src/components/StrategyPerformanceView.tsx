import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { FaArrowRight, FaDownload, FaSyncAlt } from "react-icons/fa";
import {
  Area,
  AreaChart,
  Brush,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  alignBenchmarks,
  drawdownComparison,
} from "./strategyPerformanceData.js";
import type { BenchmarkDefinition } from "./strategyPerformanceData.js";
import type { PerformanceCase, PerformanceReport } from "./factorMixTypes";

const base = `${import.meta.env.BASE_URL}strategies/factormix-033/performance/`;
const n = (value: number, digits = 0) =>
  new Intl.NumberFormat("fa-IR", { maximumFractionDigits: digits }).format(
    value,
  );
const yearLabel = (value: number) =>
  new Intl.NumberFormat("fa-IR", { useGrouping: false }).format(value);
const pct = (value: number) =>
  new Intl.NumberFormat("fa-IR", {
    style: "percent",
    maximumFractionDigits: 1,
  }).format(value);
const day = (value: string) =>
  new Intl.DateTimeFormat("fa-IR", {
    dateStyle: "medium",
    timeZone: "Asia/Tehran",
  }).format(new Date(`${value}T12:00:00Z`));
const month = (value: string) =>
  new Intl.DateTimeFormat("fa-IR", { year: "numeric", month: "short" }).format(
    new Date(`${value}T12:00:00Z`),
  );
const panel =
  "min-w-0 rounded-2xl border border-slate-200 bg-white p-4 sm:p-6 dark:border-slate-700/70 dark:bg-slate-800/60";
const button =
  "inline-flex min-h-10 items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm font-medium transition hover:bg-slate-50 disabled:opacity-40 dark:border-slate-700 dark:bg-slate-800 dark:hover:bg-slate-700";
const tooltipStyle = {
  borderRadius: 12,
  direction: "rtl" as const,
  fontFamily: "inherit",
  background: "#fff",
  color: "#0f172a",
};
function SeriesToggle({
  label,
  color,
  active,
  onClick,
}: {
  label: string;
  color: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={`${button} ${active ? "" : "opacity-50"}`}
    >
      <span aria-hidden="true" style={{ color }}>
        {active ? "●" : "○"}
      </span>
      <span className={active ? "" : "line-through"}>{label}</span>
      <span className="sr-only">{active ? "روشن" : "خاموش"}</span>
    </button>
  );
}

function HistoricalCharts({
  replay,
  definitions,
  indexLoading,
  indexError,
  goldLoading,
  goldError,
}: {
  replay: PerformanceCase;
  definitions: BenchmarkDefinition[];
  indexLoading: boolean;
  indexError: string;
  goldLoading: boolean;
  goldError: string;
}) {
  const [mode, setMode] = useState<"value" | "return">("value");
  const [log, setLog] = useState(true);
  const [hiddenCapital, setHiddenCapital] = useState<string[]>([]);
  const [hiddenDrawdown, setHiddenDrawdown] = useState<string[]>([]);
  const toggleCapital = (id: string) =>
    setHiddenCapital((ids) =>
      ids.includes(id) ? ids.filter((v) => v !== id) : [...ids, id],
    );
  const toggleDrawdown = (id: string) =>
    setHiddenDrawdown((ids) =>
      ids.includes(id) ? ids.filter((v) => v !== id) : [...ids, id],
    );
  // Every benchmark is anchored at the account start; a shorter family history
  // must never shorten or rebase the other lines.
  const aligned = useMemo(
    () => alignBenchmarks(replay, definitions, 7, true),
    [replay, definitions],
  );
  const drawdowns = useMemo(
    () => drawdownComparison(replay, definitions, 7, true),
    [replay, definitions],
  );
  const capitalSeries = [
    { id: "nav_toman", label: "FactorMix-033", color: "#059669" },
    { id: "baseline_toman", label: "مدل قبلی P1", color: "#94a3b8" },
    ...aligned.series,
  ];
  const names = Object.fromEntries(
    capitalSeries.flatMap((s) => [
      [s.id, s.label],
      [`${s.id}_pct`, s.label],
    ]),
  );
  const drawdownNames = Object.fromEntries(
    drawdowns.series.map((s) => [s.id, s.label]),
  );
  const isValue = mode === "value";
  const points = useMemo(() => {
    const source = aligned.points.length >= 2 ? aligned.points : replay.path;
    return source.map((p) => {
      const point: Record<string, string | number | null> = { ...p };
      for (const id of [
        "nav_toman",
        "baseline_toman",
        ...aligned.series.map((s) => s.id),
      ]) {
        const value = (p as Record<string, string | number | null>)[id];
        point[`${id}_pct`] =
          typeof value === "number"
            ? (value / replay.initial_toman - 1) * 100
            : null;
      }
      return point;
    });
  }, [replay, aligned]);
  const hasFamily = aligned.series.some((s) => s.id === "family_toman");
  return (
    <div className="space-y-5">
      <section className={panel} aria-labelledby="capital-chart-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 id="capital-chart-title" className="text-lg font-bold">
              مسیر همان ۱۰۰ میلیون تومان
            </h2>
            <p className="mt-2 text-xs leading-7 text-slate-500">
              {day(replay.start)} تا {day(replay.as_of)} · مبنای هر خط: ۱۰۰
              میلیون تومان در ابتدای بازه
            </p>
          </div>
          <div
            className="flex flex-wrap gap-2"
            role="group"
            aria-label="نوع نمودار"
          >
            <button
              className={button}
              aria-pressed={isValue}
              onClick={() => setMode("value")}
            >
              ارزش سبد
            </button>
            <button
              className={button}
              aria-pressed={!isValue}
              onClick={() => setMode("return")}
            >
              بازده تجمعی
            </button>
            {isValue && (
              <button
                className={button}
                aria-pressed={log}
                onClick={() => setLog((v) => !v)}
              >
                {log ? "مقیاس لگاریتمی" : "مقیاس خطی"}
              </button>
            )}
          </div>
        </div>
        {(indexLoading || goldLoading) && (
          <p role="status" className="mt-3 text-xs text-slate-500">
            در حال دریافت خطوط شاخص کل و مثقال…
          </p>
        )}
        {(indexError || goldError) && (
          <p
            role="status"
            className="mt-3 text-xs leading-7 text-amber-700 dark:text-amber-300"
          >
            {[indexError, goldError].filter(Boolean).join(" ")}
          </p>
        )}
        <div
          className="mt-4 flex flex-wrap gap-2"
          role="group"
          aria-label="خطوط مسیر سرمایه"
        >
          {capitalSeries.map((s) => (
            <SeriesToggle
              key={s.id}
              label={s.label}
              color={s.color}
              active={!hiddenCapital.includes(s.id)}
              onClick={() => toggleCapital(s.id)}
            />
          ))}
        </div>
        <p className="mt-2 text-xs text-slate-500">
          برای خاموش یا روشن کردن هر خط، روی نام آن بزنید.
        </p>
        {capitalSeries.every((s) => hiddenCapital.includes(s.id)) ? (
          <p role="status" className="py-20 text-center text-sm text-slate-500">
            همهٔ خطوط خاموش‌اند؛ یک خط را روشن کنید.
          </p>
        ) : (
          <div
            className="mt-4 h-80 w-full sm:h-96"
            dir="ltr"
            aria-label="نمودار مقایسهٔ مسیر سرمایه"
          >
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                key={`${mode}-${log}`}
                data={points}
                margin={{ top: 12, right: 10, left: 0, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="4 4"
                  vertical={false}
                  stroke="#94a3b8"
                  opacity={0.18}
                />
                <XAxis
                  dataKey="date"
                  minTickGap={60}
                  tick={{ fontSize: 10, fill: "#64748b" }}
                  tickFormatter={month}
                />
                <YAxis
                  scale={isValue && log ? "log" : "linear"}
                  domain={["auto", "auto"]}
                  width={76}
                  tick={{ fontSize: 10, fill: "#64748b" }}
                  tickFormatter={(v) => (isValue ? n(v / 1e6) : `${n(v)}٪`)}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(v) => day(String(v))}
                  formatter={(v: number, name: string) => [
                    isValue ? `${n(v)} تومان` : `${n(v, 1)}٪`,
                    names[name],
                  ]}
                />
                {capitalSeries.map((s) => (
                  <Line
                    key={s.id}
                    dataKey={isValue ? s.id : `${s.id}_pct`}
                    hide={hiddenCapital.includes(s.id)}
                    stroke={s.color}
                    dot={false}
                    connectNulls={false}
                    strokeWidth={s.id === "nav_toman" ? 2.5 : 2}
                    isAnimationActive={false}
                  />
                ))}
                <Brush
                  dataKey="date"
                  height={25}
                  stroke="#059669"
                  tickFormatter={(v) => month(String(v))}
                  travellerWidth={10}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        )}
        {hasFamily && (
          <p className="mt-3 text-xs leading-7 text-slate-500">
            دارایی خانواده · جمع کل: ۱۰۰ میلیون × جمع کل هر روز ÷ جمع کل ابتدای
            بازه. این خط تغییر دارایی ثبت‌شده را نشان می‌دهد و اثر واریز و
            برداشت از آن حذف نشده است.
          </p>
        )}
      </section>
      <section className={panel} aria-labelledby="drawdown-title">
        <h2 id="drawdown-title" className="text-lg font-bold">
          افت از بالاترین ارزش قبلی
        </h2>
        <p className="mt-2 text-xs leading-7 text-slate-500">
          {day(drawdowns.start)} تا {day(drawdowns.end)} · افت هر مسیر نسبت به
          بالاترین ارزش قبلیِ خودش
        </p>
        <div
          className="mt-4 flex flex-wrap gap-2"
          role="group"
          aria-label="خطوط افت سرمایه"
        >
          {drawdowns.series.map((s) => (
            <SeriesToggle
              key={s.id}
              label={s.label}
              color={s.color}
              active={!hiddenDrawdown.includes(s.id)}
              onClick={() => toggleDrawdown(s.id)}
            />
          ))}
        </div>
        {/* <div className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {drawdowns.series
            .filter((s) => !hiddenDrawdown.includes(s.id))
            .map((s) => (
              <div
                key={s.id}
                className="rounded-xl bg-slate-50 px-3 py-2 text-xs leading-7 dark:bg-slate-900/60"
              >
                <p style={{ color: s.color }}>● {s.label}</p>
                <p>
                  بیشترین افت مشاهده‌شده:{" "}
                  <b className="tabular-nums">
                    {pct(Math.abs(s.max_drawdown))}
                  </b>
                </p>
              </div>
            ))}
        </div> */}
        {drawdowns.series.every((s) => hiddenDrawdown.includes(s.id)) ? (
          <p role="status" className="py-20 text-center text-sm text-slate-500">
            همهٔ خطوط خاموش‌اند؛ یک خط را روشن کنید.
          </p>
        ) : (
          <div
            className="mt-5 h-56 w-full sm:h-64"
            dir="ltr"
            aria-label="نمودار مقایسهٔ افت سرمایه"
          >
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart
                data={drawdowns.points}
                margin={{ top: 8, right: 10, left: 0, bottom: 5 }}
              >
                <CartesianGrid
                  strokeDasharray="4 4"
                  vertical={false}
                  stroke="#94a3b8"
                  opacity={0.18}
                />
                <XAxis
                  dataKey="date"
                  minTickGap={60}
                  tick={{ fontSize: 10, fill: "#64748b" }}
                  tickFormatter={month}
                />
                <YAxis
                  width={76}
                  domain={["auto", 0]}
                  tick={{ fontSize: 10, fill: "#64748b" }}
                  tickFormatter={(v) => `${n(v * 100)}٪`}
                />
                <Tooltip
                  contentStyle={tooltipStyle}
                  labelFormatter={(v) => day(String(v))}
                  formatter={(v: number, name: string) => [
                    pct(v),
                    drawdownNames[name],
                  ]}
                />
                {drawdowns.series.map((s) => (
                  <Area
                    key={s.id}
                    dataKey={s.id}
                    hide={hiddenDrawdown.includes(s.id)}
                    stroke={s.color}
                    fill={s.color}
                    fillOpacity={0.035}
                    connectNulls={false}
                    strokeWidth={1.8}
                    isAnimationActive={false}
                  />
                ))}
              </AreaChart>
            </ResponsiveContainer>
          </div>
        )}
        <p className="mt-2 text-xs leading-7 text-slate-500">
          صفر یعنی آن مسیر در سقف قبلی یا بالاتر از آن است. خاموش‌کردن خطوط و
          بزرگ‌نمایی، مبنای محاسبهٔ بازده و افت را تغییر نمی‌دهد.
        </p>
      </section>
    </div>
  );
}

export function PerformanceContent({
  replay,
  definitions,
  indexLoading = false,
  indexError = "",
  goldLoading = false,
  goldError = "",
}: {
  replay: PerformanceCase;
  definitions: BenchmarkDefinition[];
  indexLoading?: boolean;
  indexError?: string;
  goldLoading?: boolean;
  goldError?: string;
}) {
  const a = replay.accounts.candidate,
    b = replay.accounts.baseline;
  const stale = a.positions.filter((p) => (p.price_age_days ?? 0) > 0);
  return (
    <div className="space-y-5">
      <HistoricalCharts
        replay={replay}
        definitions={definitions}
        indexLoading={indexLoading}
        indexError={indexError}
        goldLoading={goldLoading}
        goldError={goldError}
      />
      <section className={panel} aria-labelledby="annual-performance-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h2 id="annual-performance-title" className="text-lg font-bold">
              عملکرد سال‌های شمسی
            </h2>
            <p className="mt-2 text-xs leading-7 text-slate-500">
              یک حساب پیوسته؛ سرمایه در ابتدای سال‌ها دوباره ۱۰۰ میلیون نمی‌شود.
              همهٔ مبالغ جدول میلیون تومان‌اند.
            </p>
          </div>
          <a className={button} href={base + replay.downloads.annual} download>
            <FaDownload size={11} />
            دریافت جدول سالانه
          </a>
        </div>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[950px] text-right text-sm">
            <caption className="sr-only">
              بازده سالانهٔ حساب شروع {yearLabel(replay.start_year)}
            </caption>
            <thead>
              <tr className="border-b text-xs text-slate-500 dark:border-slate-700">
                {[
                  "سال / پایان داده",
                  "آغاز مدل جدید",
                  "پایان مدل جدید",
                  "بازده مدل جدید",
                  "آغاز P1",
                  "پایان P1",
                  "بازده P1",
                ].map((h) => (
                  <th className="p-3 font-medium" scope="col" key={h}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {replay.annual.map((y) => (
                <tr
                  key={y.year}
                  className="border-b border-slate-100 last:border-0 dark:border-slate-700/50"
                >
                  <th scope="row" className="p-3">
                    {yearLabel(y.year)}
                    <small className="mt-1 block text-xs font-normal text-slate-500">
                      {day(y.end)}
                    </small>
                  </th>
                  <td className="p-3 tabular-nums">
                    {n(y.initial_toman / 1e6, 1)}
                  </td>
                  <td className="p-3 font-bold tabular-nums text-emerald-700 dark:text-emerald-400">
                    {n(y.final_toman / 1e6, 1)}
                  </td>
                  <td className="p-3 tabular-nums">{pct(y.return_fraction)}</td>
                  <td className="p-3 tabular-nums">
                    {n(y.baseline_initial_toman / 1e6, 1)}
                  </td>
                  <td className="p-3 tabular-nums">
                    {n(y.baseline_final_toman / 1e6, 1)}
                  </td>
                  <td className="p-3 tabular-nums">
                    {pct(y.baseline_return_fraction)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className={panel}>
        <h2 className="text-lg font-bold">هزینه و اجرای مدل</h2>
        <div className="mt-4 overflow-x-auto">
          <table className="w-full min-w-[580px] text-right text-sm">
            <thead>
              <tr className="border-b text-xs text-slate-500 dark:border-slate-700">
                <th className="p-3" scope="col">
                  شاخص کل بازه
                </th>
                <th className="p-3" scope="col">
                  FactorMix-033
                </th>
                <th className="p-3" scope="col">
                  P1
                </th>
              </tr>
            </thead>
            <tbody>
              {[
                ["کارمزد کسرشده · تومان", n(a.fees_toman), n(b.fees_toman)],
                [
                  "اثر لغزش قیمت · تومان",
                  n(a.slippage_toman),
                  n(b.slippage_toman),
                ],
                [
                  "اجرای خرید / فروش",
                  `${n(a.buy_count)} / ${n(a.sell_count)}`,
                  `${n(b.buy_count)} / ${n(b.sell_count)}`,
                ],
                ["تعداد تصمیم", n(a.decision_count), n(b.decision_count)],
                ["اولین اجرای خرید", day(a.first_fill), day(b.first_fill)],
                ["نقد پایان · تومان", n(a.cash_toman), n(b.cash_toman)],
                ["بازده مرکب سالانهٔ تاریخی", pct(a.cagr), pct(b.cagr)],
              ].map(([label, left, right]) => (
                <tr
                  className="border-b border-slate-100 last:border-0 dark:border-slate-700/50"
                  key={label}
                >
                  <th
                    className="p-3 text-xs font-normal text-slate-500"
                    scope="row"
                  >
                    {label}
                  </th>
                  <td className="p-3 tabular-nums">{left}</td>
                  <td className="p-3 tabular-nums">{right}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-4 text-xs leading-7 text-slate-500">
          کارمزد ۰٫۵٪ و لغزش ۰٫۱٪ هر طرف قبلاً در نتیجه منظور شده‌اند؛ دوباره از
          سود کم نشوند. P1 با قواعد ثابت سبد خودش مقایسه می‌شود؛ این جدول
          به‌تنهایی اثر امتیاز را از اثر قواعد سبد جدا نمی‌کند.
        </p>
      </section>
      <section className={panel}>
        <h2 className="text-lg font-bold">دریافت خروجی همین بازه</h2>
        <div className="mt-4 flex flex-wrap gap-2">
          {[
            ["گزارش", "report"],
            ["نمودار PNG", "chart"],
            ["مسیر سرمایهٔ مدل", "candidate_nav"],
            ["مسیر سرمایهٔ P1", "baseline_nav"],
            ["معاملات مدل", "candidate_trades"],
            ["معاملات P1", "baseline_trades"],
          ].map(([label, key]) => (
            <a
              className={button}
              key={key}
              href={base + replay.downloads[key]}
              download
            >
              <FaDownload size={11} />
              {label}
            </a>
          ))}
        </div>
        <p className="mt-3 text-xs text-slate-500">
          تمام فایل‌های این بخش مربوط به حساب با شروع{" "}
          {yearLabel(replay.start_year)} هستند.
        </p>
      </section>
      <aside className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-xs leading-8 text-amber-950 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
        <p>
          <b>مبنای این اعداد بازپخش تاریخی است.</b> بخشی از همین تاریخچه در
          انتخاب مدل استفاده شده و زمان دریافت تاریخی همهٔ گزارش‌ها اثبات نشده
          است. ارقام اسمی‌اند؛ تورم تعدیل نشده و واحدها شاخصی تعدیل‌شده‌اند.
          ارزش پایان، وجه نقد قابل برداشت فوری نیست.
        </p>
        {stale.map((p) => (
          <p key={p.symbol}>
            {p.symbol}: {n(p.market_value_toman)} تومان با قیمت{" "}
            {day(p.price_date!)}، {n(p.price_age_days!)} روز قدیمی‌تر از پایان
            داده{p.action === "EXIT_UNFILLED" ? "؛ خروج اجرا نشده است" : ""}.
          </p>
        ))}
        <p>
          روزهای بدون فعالیت سهام در تقویم مشاهده‌شدهٔ همین نسخه رسیدگی شده‌اند.
          انتخاب بازه یا بازخوانی گزارش، حساب جدید و معاملهٔ واقعی ایجاد
          نمی‌کند.
        </p>
      </aside>
    </div>
  );
}

export default function StrategyPerformanceView({
  report,
  loading,
  onRefresh,
  definitions,
  indexLoading,
  indexError,
  goldLoading,
  goldError,
  familyStatus = "",
}: {
  familyStatus?: string;
  report: PerformanceReport;
  loading: boolean;
  onRefresh: () => void;
  definitions: BenchmarkDefinition[];
  indexLoading: boolean;
  indexError: string;
  goldLoading: boolean;
  goldError: string;
}) {
  const replay = report.cases.find((c) => c.id === report.default_case)!;
  return (
    <main
      dir="rtl"
      className="mx-auto min-w-0 max-w-[1500px] space-y-5 text-slate-800 dark:text-slate-100"
    >
      <header
        className={`${panel} flex flex-wrap items-start justify-between gap-4`}
      >
        <div>
          <p
            className="text-xs font-bold tracking-wide text-emerald-700 dark:text-emerald-400"
            dir="ltr"
          >
            FactorMix-033 · v1.0.0
          </p>
          <h1 className="mt-2 text-2xl font-black sm:text-3xl">
            عملکرد سبد استراتژی
          </h1>
          <p className="mt-2 text-sm leading-7 text-slate-500 dark:text-slate-400">
            مسیر سرمایه، افت و بازده سالانه با همان وزن‌ها و قواعد ثبت‌شده
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button className={button} disabled={loading} onClick={onRefresh}>
            <FaSyncAlt size={12} className={loading ? "animate-spin" : ""} />
            بازخوانی گزارش
          </button>
          <Link className={button} to="/strategy">
            <FaArrowRight size={11} />
            سبد استراتژی
          </Link>
        </div>
      </header>
      {familyStatus && (
        <p role="status" className="text-xs leading-7 text-slate-500">
          {familyStatus}
        </p>
      )}
      <PerformanceContent
        key={replay.id}
        replay={replay}
        definitions={definitions}
        indexLoading={indexLoading}
        indexError={indexError}
        goldLoading={goldLoading}
        goldError={goldError}
      />
      <footer className="border-t border-slate-200 pt-4 text-[11px] leading-7 text-slate-500 dark:border-slate-700">
        دو بازه با سرمایه و فرض‌های اجرای مشترک بررسی شده‌اند. بازخوانی فقط
        گزارش ذخیره‌شده را می‌خواند؛ دریافت داده و خریدوفروش خودکار فعال
        نمی‌شود.
      </footer>
    </main>
  );
}
