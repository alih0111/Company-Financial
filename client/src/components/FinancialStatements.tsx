import { Fragment, useEffect, useMemo, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { FaExclamationTriangle, FaFileInvoice, FaInfoCircle } from "react-icons/fa";
import { SkeletonTable } from "./Skeleton";
import { faDigits } from "../utils/chartHelpers";
import {
  fetchFinancialStatements,
  type FSAmount,
  type FSPeriod,
  type FinancialStatementsResponse,
} from "../utils/api";

// صورت‌های مالی کامل یک نماد (سود و زیان / ترازنامه / جریان نقد عملیاتی).
//
// واحد: مبالغ کدال «هم‌واحد گزارش» ذخیره شده‌اند و واحد اعلامی بین گزارش‌ها
// متغیر است؛ بنابراین مقادیر مطلقِ قابل اتکا در «هر سهم (ریال)» نمایش داده
// می‌شوند — باز-مقیاس‌شده با لنگر EPS×سرمایه (بازنمایی همان قرارداد
// NPUnitRatio در vw_AIStockMetrics). EPS سطر ریالیِ قطعی کدال است و
// درصدها/نسبت‌ها ذاتاً بی‌واحد و درست‌اند. ردیف‌هایی که لنگرشان با سود خالص
// سازگار نیست با علامت هشدار مشخص می‌شوند.

type TabKey = "income" | "balance" | "cashflow";

const TABS: { key: TabKey; label: string }[] = [
  { key: "income", label: "سود و زیان" },
  { key: "balance", label: "ترازنامه" },
  { key: "cashflow", label: "جریان نقد" },
];

const PERIOD_LABEL: Record<number, string> = {
  3: "۳ ماهه",
  6: "۶ ماهه",
  9: "۹ ماهه",
  12: "۱۲ ماهه",
};

const fmtInt = (v: number) =>
  faDigits(
    v.toLocaleString("fa-IR", {
      maximumFractionDigits: Math.abs(v) >= 100 ? 0 : 1,
    })
  );

const fmtPct = (v: number) =>
  `${faDigits(Math.abs(v) >= 100 ? Math.round(v).toLocaleString("fa-IR") : v.toLocaleString("fa-IR", { maximumFractionDigits: 1 }))}٪`;

const fmtRatio = (v: number) =>
  faDigits(v.toLocaleString("fa-IR", { maximumFractionDigits: 2 }));

// مقدارِ مطلق «هر سهم (ریال)»: مقدار خام هم‌واحد گزارش × ۱۰۰۰ ÷ سرمایه.
// برای سود خالص این دقیقاً EPS را بازتولید می‌کند (لنگر سمت سرور چک شده است).
const perShare = (amount: FSAmount | undefined, capital: number | null | undefined): number | null => {
  const cur = amount?.current;
  if (cur == null || capital == null || capital === 0) return null;
  return (cur * 1000) / capital;
};

type CellKind = "rial" | "raw" | "pct" | "ratio";

interface Row {
  key: string;
  label: string;
  hint?: string;
  kind: CellKind;
  // مقدار هر دوره را از ردیف گزارش می‌گیرد (به ترتیب periods از سرور)
  values: (number | null)[];
  warnIfUnitInconsistent?: boolean;
  section?: string; // اگر ست شود، قبل از این ردیف سرتیتر بخش چاپ می‌شود
  goodWhenPositive?: boolean; // برای رنگ درصدها
}

const num = (v: number | null | undefined): number | null =>
  v == null || Number.isNaN(v) ? null : v;

function buildIncomeRows(periods: FSPeriod[]): Row[] {
  return [
    {
      key: "eps",
      label: "سود خالص هر سهم",
      hint: "از سطر «سود (زیان) خالص هر سهم» کدال — ریال",
      kind: "rial",
      values: periods.map((p) => num(p.income_statement.eps_rial)),
      goodWhenPositive: true,
      section: "هر سهم (ریال)",
    },
    {
      key: "op_eps",
      label: "سود عملیاتی هر سهم",
      hint: "از سطر «سود (زیان) عملیاتی هر سهم» کدال — ریال",
      kind: "rial",
      values: periods.map((p) => num(p.income_statement.operating_eps_rial)),
      goodWhenPositive: true,
    },
    {
      key: "rev_ps",
      label: "درآمد هر سهم",
      hint: "درآمد هم‌واحد گزارش باز-مقیاس‌شده به هر سهم (ریال)",
      kind: "rial",
      values: periods.map((p) =>
        perShare(p.income_statement.revenue, p.income_statement.capital)
      ),
    },
    {
      key: "np_ps",
      label: "سود خالص هر سهم (از مبالغ)",
      hint: "سود خالص هم‌واحد گزارش باز-مقیاس‌شده — باید با سطر EPS هم‌خوان باشد",
      kind: "rial",
      values: periods.map((p) =>
        perShare(p.income_statement.net_profit, p.income_statement.capital)
      ),
    },
    {
      key: "eps_yoy",
      label: "رشد EPS سالانه",
      kind: "pct",
      values: periods.map((p) => num(p.derived.eps_yoy_pct)),
      goodWhenPositive: true,
      section: "درصدها و نسبت‌ها",
    },
    {
      key: "net_margin",
      label: "حاشیه سود خالص",
      hint: "سود خالص ÷ درآمد همان دوره",
      kind: "pct",
      values: periods.map((p) => num(p.derived.net_margin_pct)),
    },
    {
      key: "rev_yoy",
      label: "رشد درآمد (سالانه)",
      kind: "pct",
      values: periods.map((p) => num(p.derived.revenue_yoy_pct)),
      goodWhenPositive: true,
    },
    {
      key: "np_yoy",
      label: "رشد سود خالص (سالانه)",
      kind: "pct",
      values: periods.map((p) => num(p.derived.net_profit_yoy_pct)),
      goodWhenPositive: true,
    },
    {
      key: "capital",
      label: "سرمایه",
      hint: "هم‌واحد گزارش کدال",
      kind: "raw",
      values: periods.map((p) => num(p.income_statement.capital)),
      warnIfUnitInconsistent: true,
      section: "مبالغ هم‌واحد گزارش",
    },
    {
      key: "revenue",
      label: "درآمد",
      kind: "raw",
      values: periods.map((p) => num(p.income_statement.revenue.current)),
      warnIfUnitInconsistent: true,
    },
    {
      key: "finance_costs",
      label: "هزینه مالی",
      kind: "raw",
      values: periods.map((p) => num(p.income_statement.finance_costs.current)),
      warnIfUnitInconsistent: true,
    },
    {
      key: "other_non_op",
      label: "سایر درآمد و هزینه‌های غیرعملیاتی",
      kind: "raw",
      values: periods.map((p) =>
        num(p.income_statement.other_non_operating.current)
      ),
      warnIfUnitInconsistent: true,
    },
    {
      key: "net_profit",
      label: "سود خالص",
      kind: "raw",
      values: periods.map((p) => num(p.income_statement.net_profit.current)),
      warnIfUnitInconsistent: true,
    },
  ];
}

function buildBalanceRows(periods: FSPeriod[]): Row[] {
  return [
    {
      key: "book_value_ps",
      label: "ارزش دفتری هر سهم",
      hint: "حقوق صاحبان سهام باز-مقیاس‌شده به هر سهم (ریال)",
      kind: "rial",
      values: periods.map((p) =>
        perShare(p.balance_sheet.total_equity, p.income_statement.capital)
      ),
      section: "هر سهم (ریال)",
    },
    {
      key: "current_ratio",
      label: "نسبت جاری",
      hint: "دارایی جاری ÷ بدهی جاری",
      kind: "ratio",
      values: periods.map((p) => num(p.derived.current_ratio)),
      goodWhenPositive: true,
      section: "درصدها و نسبت‌ها",
    },
    {
      key: "debt_assets",
      label: "بدهی به دارایی",
      kind: "pct",
      values: periods.map((p) => num(p.derived.debt_to_assets_pct)),
    },
    {
      key: "ca_share",
      label: "سهم دارایی جاری از کل",
      kind: "pct",
      values: periods.map((p) => num(p.derived.current_assets_pct)),
    },
    {
      key: "total_assets",
      label: "جمع دارایی‌ها",
      kind: "raw",
      values: periods.map((p) => num(p.balance_sheet.total_assets.current)),
      warnIfUnitInconsistent: true,
      section: "مبالغ هم‌واحد گزارش",
    },
    {
      key: "current_assets",
      label: "دارایی‌های جاری",
      kind: "raw",
      values: periods.map((p) => num(p.balance_sheet.current_assets.current)),
      warnIfUnitInconsistent: true,
    },
    {
      key: "non_current_assets",
      label: "دارایی‌های غیرجاری",
      hint: "محاسبه‌شده: جمع دارایی‌ها − دارایی جاری",
      kind: "raw",
      values: periods.map((p) =>
        num(p.derived.non_current_assets.current)
      ),
      warnIfUnitInconsistent: true,
    },
    {
      key: "total_liabilities",
      label: "جمع بدهی‌ها",
      kind: "raw",
      values: periods.map((p) => num(p.balance_sheet.total_liabilities.current)),
      warnIfUnitInconsistent: true,
    },
    {
      key: "current_liabilities",
      label: "بدهی‌های جاری",
      kind: "raw",
      values: periods.map((p) =>
        num(p.balance_sheet.current_liabilities.current)
      ),
      warnIfUnitInconsistent: true,
    },
    {
      key: "non_current_liabilities",
      label: "بدهی‌های غیرجاری",
      hint: "محاسبه‌شده: جمع بدهی‌ها − بدهی جاری",
      kind: "raw",
      values: periods.map((p) =>
        num(p.derived.non_current_liabilities.current)
      ),
      warnIfUnitInconsistent: true,
    },
    {
      key: "total_equity",
      label: "حقوق صاحبان سهام",
      kind: "raw",
      values: periods.map((p) => num(p.balance_sheet.total_equity.current)),
      warnIfUnitInconsistent: true,
    },
  ];
}

function buildCashflowRows(periods: FSPeriod[]): Row[] {
  return [
    {
      key: "ocf_ps",
      label: "جریان نقد عملیاتی هر سهم",
      hint: "خالص جریان‌های نقدی عملیاتی (تجمعی) باز-مقیاس‌شده به هر سهم (ریال)",
      kind: "rial",
      values: periods.map((p) =>
        perShare(p.cash_flow.operating, p.income_statement.capital)
      ),
      goodWhenPositive: true,
      section: "هر سهم (ریال)",
    },
    {
      key: "cash_conversion",
      label: "تبدیل سود به نقد",
      hint: "جریان نقد عملیاتی ÷ سود خالص همان دوره",
      kind: "pct",
      values: periods.map((p) => num(p.derived.cash_conversion_pct)),
      section: "درصدها و نسبت‌ها",
    },
    {
      key: "ocf",
      label: "جریان نقد عملیاتی (تجمعی)",
      kind: "raw",
      values: periods.map((p) => num(p.cash_flow.operating.current)),
      warnIfUnitInconsistent: true,
      section: "مبالغ هم‌واحد گزارش",
    },
    {
      key: "ocf_ly",
      label: "جریان نقد عملیاتی دوره مشابه سال قبل",
      kind: "raw",
      values: periods.map((p) => num(p.cash_flow.operating.ly)),
      warnIfUnitInconsistent: true,
    },
  ];
}

function cellColor(value: number | null, kind: CellKind, goodWhenPositive?: boolean): string {
  if (value == null) return "text-gray-400 dark:text-gray-500";
  if ((kind === "pct" || kind === "rial") && goodWhenPositive) {
    return value >= 0
      ? "text-emerald-600 dark:text-emerald-400"
      : "text-red-500 dark:text-red-400";
  }
  if (value < 0) return "text-red-500 dark:text-red-400";
  return "text-gray-700 dark:text-gray-200";
}

function formatCell(value: number | null, kind: CellKind): string {
  if (value == null) return "—";
  switch (kind) {
    case "pct":
      return fmtPct(value);
    case "ratio":
      return fmtRatio(value);
    case "rial":
      return fmtInt(value);
    default:
      return faDigits(value.toLocaleString("fa-IR", { maximumFractionDigits: 0 }));
  }
}

interface FinancialStatementsProps {
  companyName: string;
}

export default function FinancialStatements({ companyName }: FinancialStatementsProps) {
  const [data, setData] = useState<FinancialStatementsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<TabKey>("income");

  useEffect(() => {
    if (!companyName) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    setData(null);
    fetchFinancialStatements(companyName)
      .then((res) => {
        if (!cancelled) setData(res);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "خطای ناشناخته");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [companyName]);

  const periods = useMemo(() => data?.periods ?? [], [data]);

  const rows = useMemo(() => {
    if (!periods.length) return [];
    if (tab === "income") return buildIncomeRows(periods);
    if (tab === "balance") return buildBalanceRows(periods);
    return buildCashflowRows(periods);
  }, [periods, tab]);

  // نمودارها ترتیب زمانی قدیم→جدید می‌خواهند (recharts چپ→راست)
  const chronological = useMemo(() => [...periods].reverse(), [periods]);

  const epsSeries = useMemo(
    () =>
      chronological.map((p) => ({
        name: faDigits(p.report_date),
        value: p.income_statement.eps_rial ?? 0,
      })),
    [chronological]
  );

  const balanceSeries = useMemo(
    () =>
      chronological.map((p) => ({
        name: faDigits(p.report_date),
        جاری: p.derived.current_assets_pct ?? 0,
        بدهی: p.derived.debt_to_assets_pct ?? 0,
      })),
    [chronological]
  );

  const ocfSeries = useMemo(
    () =>
      chronological.map((p) => ({
        name: faDigits(p.report_date),
        value: perShare(p.cash_flow.operating, p.income_statement.capital) ?? 0,
      })),
    [chronological]
  );

  const hasInconsistentUnits = periods.some((p) => p.unit_consistent === false);

  return (
    <div className="rounded-2xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/40 backdrop-blur-sm p-4 shadow-md">
      {/* سرصفحه + تب‌ها */}
      <div className="flex flex-col sm:flex-row sm:items-center gap-3 justify-between mb-3">
        <h3 className="flex items-center gap-2 text-sm font-bold text-gray-800 dark:text-gray-100">
          <FaFileInvoice className="text-emerald-500" />
          صورت‌های مالی
          <span className="text-xs font-normal text-gray-400 dark:text-gray-500">
            ({faDigits(companyName)})
          </span>
        </h3>
        <div className="flex gap-1 rounded-xl bg-gray-100/80 dark:bg-gray-900/60 p-1">
          {TABS.map((t) => (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg transition-all duration-200 ${
                tab === t.key
                  ? "bg-white dark:bg-gray-700 text-emerald-600 dark:text-emerald-400 shadow-sm"
                  : "text-gray-500 dark:text-gray-400 hover:text-gray-700 dark:hover:text-gray-200"
              }`}
            >
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {loading && <SkeletonTable rows={10} cols={5} />}

      {!loading && error && (
        <div className="rounded-xl border border-red-200/70 dark:border-red-900/40 bg-red-50/60 dark:bg-red-900/10 p-4 text-sm text-red-600 dark:text-red-400">
          {error}
        </div>
      )}

      {!loading && !error && periods.length === 0 && (
        <div className="rounded-xl border border-gray-200/70 dark:border-gray-700/40 bg-gray-50/60 dark:bg-gray-900/30 p-4 text-sm text-gray-500 dark:text-gray-400">
          صورت مالی ثبت‌شده‌ای برای «{faDigits(companyName)}» در پایگاه داده پیدا
          نشد. پس از همگام‌سازی کدال این بخش پر می‌شود.
        </div>
      )}

      {!loading && !error && periods.length > 0 && (
        <>
          {hasInconsistentUnits && (
            <div className="mb-3 flex items-start gap-2 rounded-xl border border-amber-200/70 dark:border-amber-900/40 bg-amber-50/60 dark:bg-amber-900/10 p-3 text-xs text-amber-700 dark:text-amber-300">
              <FaExclamationTriangle className="mt-0.5 shrink-0" />
              <span>
                در برخی دوره‌ها لنگر «EPS × سرمایه» با سود خالص اعلامی سازگار
                نیست (نشان ⁇)؛ مقیاس مبالغ آن دوره‌ها ممکن است با بقیه
                یکسان نباشد. درصدها و سطرهای «هر سهم» مستقل از این مشکل‌اند.
              </span>
            </div>
          )}

          {/* جدول: سطر = خطوط صورت، ستون = دوره‌ها (جدیدترین سمت راست) */}
          <div className="overflow-x-auto">
            <table className="w-full text-xs border-separate border-spacing-y-1">
              <thead>
                <tr>
                  <th className="sticky right-0 bg-white/95 dark:bg-gray-800/95 text-right font-medium text-gray-500 dark:text-gray-400 px-3 py-2 min-w-[170px] z-10">
                    شرح
                  </th>
                  {periods.map((p) => (
                    <th
                      key={p.report_date}
                      className="px-3 py-2 text-center font-medium text-gray-600 dark:text-gray-300 whitespace-nowrap"
                    >
                      <div>{faDigits(p.report_date)}</div>
                      <div className="text-[10px] font-normal text-gray-400 dark:text-gray-500 mt-0.5">
                        {PERIOD_LABEL[p.duration_months] ?? `${faDigits(String(p.duration_months))} ماهه`}
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <Fragment key={row.key}>
                    {row.section && (
                      <tr>
                        <td
                          colSpan={periods.length + 1}
                          className="px-3 pt-3 pb-1 text-[11px] font-bold text-emerald-600 dark:text-emerald-400/90"
                        >
                          {row.section}
                        </td>
                      </tr>
                    )}
                    <tr className="bg-white/80 dark:bg-gray-800/60 hover:bg-emerald-50/40 dark:hover:bg-gray-700/40 transition-colors">
                      <td className="sticky right-0 bg-white/95 dark:bg-gray-800/95 px-3 py-2 text-right text-gray-600 dark:text-gray-300 whitespace-nowrap z-10">
                        {row.label}
                        {row.hint && (
                          <span
                            title={row.hint}
                            className="inline-flex align-middle mr-1 text-gray-400 dark:text-gray-500 cursor-help"
                          >
                            <FaInfoCircle size={10} />
                          </span>
                        )}
                      </td>
                      {row.values.map((v, i) => {
                        const period = periods[i];
                        const flagged =
                          !!row.warnIfUnitInconsistent &&
                          period?.unit_consistent === false;
                        return (
                          <td
                            key={`${row.key}-${period?.report_date ?? i}`}
                            className={`px-3 py-2 text-center tabular-nums whitespace-nowrap ${cellColor(
                              v,
                              row.kind,
                              row.goodWhenPositive
                            )}`}
                          >
                            {formatCell(v, row.kind)}
                            {flagged && (
                              <span
                                title="سازگاری واحد این دوره تأیید نشده است"
                                className="text-amber-500 dark:text-amber-400 mr-1"
                              >
                                ⁇
                              </span>
                            )}
                          </td>
                        );
                      })}
                    </tr>
                  </Fragment>
                ))}
              </tbody>
            </table>
          </div>

          {/* نمودار روند هر تب */}
          <div className="mt-4 text-gray-500 dark:text-gray-400">
            {tab === "income" && (
              <MiniChart
                title="روند EPS (ریال — قطعی)"
                data={epsSeries}
                type="bar"
              />
            )}
            {tab === "balance" && (
              <MiniChart
                title="ساختار ترازنامه (٪ — بی‌واحد)"
                data={balanceSeries}
                type="line"
                series={[
                  { key: "جاری", color: "#10b981" },
                  { key: "بدهی", color: "#f59e0b" },
                ]}
              />
            )}
            {tab === "cashflow" && (
              <MiniChart
                title="جریان نقد عملیاتی هر سهم (ریال)"
                data={ocfSeries}
                type="bar"
              />
            )}
          </div>

          <p className="mt-3 text-[11px] leading-5 text-gray-400 dark:text-gray-500">
            {data?.unit_note} مقادیر «هر سهم» با لنگر EPS×سرمایه از مبالغ
            هم‌واحد گزارش باز-مقیاس شده‌اند.
          </p>
        </>
      )}
    </div>
  );
}

// ── نمودار کوچک روند ─────────────────────────────────────────────────────

interface MiniSeries {
  key: string;
  color: string;
}

function MiniChart({
  title,
  data,
  type,
  series,
}: {
  title: string;
  data: Record<string, number | string>[];
  type: "bar" | "line";
  series?: MiniSeries[];
}) {
  const keys = series?.map((s) => s.key) ?? ["value"];
  const colors = series?.map((s) => s.color) ?? ["#10b981"];
  return (
    <div className="rounded-xl border border-gray-200/60 dark:border-gray-700/40 bg-white/60 dark:bg-gray-800/40 p-3">
      <p className="text-xs font-medium text-gray-600 dark:text-gray-300 mb-2">
        {title}
      </p>
      <div className="h-44">
        <ResponsiveContainer width="100%" height="100%">
          {type === "bar" ? (
            <BarChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.6} />
              <YAxis
                tick={{ fontSize: 10 }}
                stroke="currentColor"
                opacity={0.6}
                width={56}
                tickFormatter={(v: number) =>
                  faDigits(
                    v.toLocaleString("fa-IR", {
                      notation: "compact",
                      maximumFractionDigits: 1,
                    })
                  )
                }
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  fontSize: 12,
                  backgroundColor: "rgba(255,255,255,0.95)",
                }}
                labelStyle={{ color: "#374151" }}
                formatter={(value: number | string) =>
                  faDigits(Number(value).toLocaleString("fa-IR", { maximumFractionDigits: 1 }))
                }
              />
              {keys.map((k, i) => (
                <Bar key={k} dataKey={k} fill={colors[i]} radius={[4, 4, 0, 0]} />
              ))}
            </BarChart>
          ) : (
            <LineChart data={data} margin={{ top: 4, right: 8, left: 8, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="currentColor" opacity={0.15} />
              <XAxis dataKey="name" tick={{ fontSize: 10 }} stroke="currentColor" opacity={0.6} />
              <YAxis
                tick={{ fontSize: 10 }}
                stroke="currentColor"
                opacity={0.6}
                width={40}
                tickFormatter={(v: number) =>
                  faDigits(
                    v.toLocaleString("fa-IR", {
                      maximumFractionDigits: 0,
                    })
                  )
                }
              />
              <Tooltip
                contentStyle={{
                  borderRadius: 12,
                  fontSize: 12,
                  backgroundColor: "rgba(255,255,255,0.95)",
                }}
                labelStyle={{ color: "#374151" }}
                formatter={(value: number | string) =>
                  faDigits(Number(value).toLocaleString("fa-IR", { maximumFractionDigits: 1 }))
                }
              />
              {keys.map((k, i) => (
                <Line
                  key={k}
                  type="monotone"
                  dataKey={k}
                  stroke={colors[i]}
                  strokeWidth={2}
                  dot={{ r: 2 }}
                />
              ))}
            </LineChart>
          )}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
