import { useMemo, useState } from "react";
import { useTable, useSortBy, useGlobalFilter, type Column } from "react-table";
import { FaSort, FaSortUp, FaSortDown, FaSearch, FaCheck, FaTimes } from "react-icons/fa";
import { addViewedItem } from "../utils/api";

const getStableValue = (row: DataRow): boolean | null => {
  return row.stable ?? row.Stable ?? null;
};

// مرتب‌سازی عددی با مدیریت null
// nullها همیشه آخر (چه صعودی چه نزولی)
const numericSort = (
  rowA: { values: Record<string, unknown> },
  rowB: { values: Record<string, unknown> },
  columnId: string,
  desc?: boolean,
) => {
  const parseValue = (value: unknown): number | null => {
    if (value === null || value === undefined || value === "") {
      return null;
    }

    const parsed = Number(value);

    return Number.isFinite(parsed) ? parsed : null;
  };

  const a = parseValue(rowA.values[columnId]);
  const b = parseValue(rowB.values[columnId]);

  if (a === null && b === null) return 0;

  if (a === null) return desc ? -1 : 1;
  if (b === null) return desc ? 1 : -1;

  return a - b;
};

interface DataRow {
  company_id: string;
  company_name: string;
  eps_growth: number;
  sales_growth: number;
  pe: number;
  stable: boolean;
  Stable?: boolean;
  operation: number;
  quant_score?: number | null;

  revenue_growth_yoy?: number | null;
  operating_margin_latest?: number | null;
  net_margin_latest?: number | null;
  operating_margin_trend?: number | null;
  interest_coverage?: number | null;
  non_operating_pct?: number | null;
  ps_ratio?: number | null;
  latest_price?: number | null;
  pe_approx?: number | null;
  symbol?: string | null;
  price_return_30d?: number | null;
  avg_trade_value_30d?: number | null;

  bad_pe_flag?: boolean;
  weak_sales_flag?: boolean;
  weak_operating_profit_flag?: boolean;
  weak_liquidity_flag?: boolean;
  loss_maker_flag?: boolean;
  weak_coverage_flag?: boolean;
  margin_contraction_flag?: boolean;
}

interface Props {
  data: DataRow[];
  _selectedCompany: string;
  _onCompanyChange: (name: string) => void;
}

// Score badge styling
const scoreBadge = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) {
    return "bg-gray-100 dark:bg-gray-700/50 text-gray-500 dark:text-gray-400";
  }
  if (value >= 70) return "bg-emerald-500/15 text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/20";
  if (value >= 55) return "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 ring-1 ring-emerald-500/15";
  if (value >= 40) return "bg-indigo-500/15 text-indigo-600 dark:text-indigo-400 ring-1 ring-indigo-500/20";
  if (value >= 25) return "bg-amber-500/15 text-amber-600 dark:text-amber-400 ring-1 ring-amber-500/20";
  return "bg-red-500/15 text-red-600 dark:text-red-400 ring-1 ring-red-500/20";
};

// Non-operating badge styling
const nonOpBadge = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return "text-gray-400";
  if (value < 5) return "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10";
  if (value < 15) return "text-amber-600 dark:text-amber-400 bg-amber-500/10";
  if (value < 30) return "text-orange-600 dark:text-orange-400 bg-orange-500/10";
  return "text-red-600 dark:text-red-400 bg-red-500/10 font-semibold";
};

// Growth badge
const growthBadge = (value: number | null | undefined) => {
  if (value == null || !Number.isFinite(value)) return "text-gray-400";
  if (value > 30) return "text-emerald-600 dark:text-emerald-400 bg-emerald-500/10 font-semibold";
  if (value < -10) return "text-red-600 dark:text-red-400 bg-red-500/10 font-semibold";
  return "text-gray-600 dark:text-gray-300";
};

// Row left border color based on score
const rowBorderColor = (score: number | null | undefined) => {
  if (score == null || !Number.isFinite(score)) return "border-l-gray-300 dark:border-l-gray-700";
  if (score >= 70) return "border-l-emerald-500/60";
  if (score >= 55) return "border-l-emerald-400/40";
  if (score >= 40) return "border-l-indigo-500/50";
  if (score >= 25) return "border-l-amber-400/50";
  return "border-l-red-400/50";
};

const BigDataTable: React.FC<Props> = ({
  data,
  _selectedCompany,
  _onCompanyChange,
}) => {
  const [globalFilter, setGlobalFilter] = useState("");

  const columns = useMemo<Column<DataRow>[]>(
    () => [
      {
        Header: "Score",
        id: "quant_score",

        accessor: (row: DataRow) => {
          const value = row.quant_score;

          if (value === null || value === undefined) {
            return null;
          }

          const parsed = Number(value);
          return Number.isFinite(parsed) ? parsed : null;
        },

        sortType: "numericSort",
        sortDescFirst: true,
        className: "w-28",

        Cell: ({ value }: { value: number | null | undefined }) => (
          <span className={`inline-flex items-center justify-center min-w-[3.5rem] px-3 py-1 rounded-full text-sm font-bold tabular-nums ${scoreBadge(value)}`}>
            {value != null && Number.isFinite(value) ? value.toFixed(2) : "--"}
          </span>
        ),
      },
      {
        Header: "Stable",
        id: "Stable",
        accessor: (row: DataRow) => getStableValue(row),
        sortType: "basic",
        className: "w-16",
        Cell: ({ value }: { value: boolean | null | undefined }) => {
          if (value === true) {
            return (
              <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-emerald-500/15 ring-1 ring-emerald-500/25">
                <FaCheck className="text-emerald-600 dark:text-emerald-400 text-xs" />
              </span>
            );
          }
          if (value === false) {
            return (
              <span className="inline-flex items-center justify-center w-8 h-8 rounded-full bg-red-500/15 ring-1 ring-red-500/25">
                <FaTimes className="text-red-500 dark:text-red-400 text-xs" />
              </span>
            );
          }
          return <span className="text-gray-400">--</span>;
        },
      },
      {
        Header: "nonOperating",
        accessor: "non_operating_pct",
        sortType: "numericSort",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-lg text-xs font-medium tabular-nums ${nonOpBadge(value)}`}>
            {value != null && Number.isFinite(value) ? value.toFixed(2) + "%" : "--"}
          </span>
        ),
      },
      {
        Header: "EPS Growth",
        accessor: "eps_growth",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number }) => (
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-lg text-xs font-medium tabular-nums ${growthBadge(value)}`}>
            {value != null ? value.toFixed(2) + "%" : "--"}
          </span>
        ),
      },
      {
        Header: "Sales Growth",
        accessor: "sales_growth",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number }) => (
          <span className={`inline-flex items-center px-2.5 py-0.5 rounded-lg text-xs font-medium tabular-nums ${growthBadge(value)}`}>
            {value != null ? value.toFixed(2) + "%" : "--"}
          </span>
        ),
      },
      {
        Header: "Company",
        accessor: "company_name",
        className: "w-32",
        Cell: ({ value }: { value: string }) => (
          <span className="font-bold text-gray-800 dark:text-white text-sm">
            {value}
          </span>
        ),
      },
      {
        Header: "ردیف",
        id: "row_number",
        Cell: () => null,
        disableSortBy: true,
        className: "w-20",
      },
    ],
    [],
  );

  const tableInstance = useTable(
    {
      columns,
      data,
      initialState: { hiddenColumns: [] },
      sortTypes: {
        numericSort,
      },
    },
    useGlobalFilter,
    useSortBy,
  );

  const {
    getTableProps,
    getTableBodyProps,
    headerGroups,
    rows,
    prepareRow,
  } = tableInstance;

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value || "";
    setGlobalFilter(value);
    // Plugin-added method from useGlobalFilter
    (tableInstance as Record<string, (v: string) => void>).setGlobalFilter(value);
  };

  const handleSortBy = (sorts: { id: string; desc: boolean }[]) => {
    // Plugin-added method from useSortBy
    (tableInstance as Record<string, (s: { id: string; desc: boolean }[]) => void>).setSortBy(sorts);
  };

  return (
    <div className="animate-fade-in-up glass-border glass-border-active rounded-3xl border border-gray-200/80 dark:border-gray-700/60 bg-white/70 dark:bg-gray-800/50 backdrop-blur-xl shadow-2xl shadow-indigo-500/5 dark:shadow-indigo-500/10 py-4 px-6">
      {/* ── Toolbar ── */}
      <div className="flex items-center gap-3 mb-4 flex-wrap">
        {/* Search */}
        <div className="relative flex-1 max-w-md">
          <FaSearch className="absolute top-1/2 left-3.5 -translate-y-1/2 text-gray-400 dark:text-gray-500 text-sm" />
          <input
            type="text"
            value={globalFilter}
            onChange={handleSearch}
            placeholder="جستجوی شرکت..."
            dir="rtl"
            className="w-full py-2.5 pr-4 pl-10 rounded-2xl border border-gray-200 dark:border-gray-700 bg-white/60 dark:bg-gray-800/60 backdrop-blur-sm text-gray-900 dark:text-gray-100 text-sm placeholder:text-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/40 focus:border-indigo-400 transition-all duration-300 shadow-sm focus:shadow-md focus:shadow-indigo-500/10"
          />
        </div>

        {/* Silver filter button */}
        <button
          onClick={() =>
            handleSortBy([
              { id: "Stable", desc: true },
              { id: "eps_growth", desc: true },
            ])
          }
          className="px-5 py-2.5 rounded-2xl border border-gray-200 dark:border-gray-600 bg-gradient-to-br from-gray-50 via-gray-100 to-gray-200 dark:from-gray-700 dark:via-gray-800 dark:to-gray-900 text-gray-700 dark:text-gray-200 text-sm font-semibold shadow-sm hover:-translate-y-0.5 hover:shadow-lg hover:shadow-gray-400/20 dark:hover:shadow-gray-900/40 transition-all duration-200 active:translate-y-0"
        >
          ◇ Silver
        </button>
      </div>

      {/* ── Table ── */}
      <div className="overflow-auto max-h-[82vh] rounded-2xl">
        <table
          {...getTableProps()}
          className="min-w-full text-sm border-collapse"
          style={{ borderSpacing: 0 }}
        >
          {/* Header */}
          <thead className="sticky top-0 z-10">
            {headerGroups.map((headerGroup) => {
              const hgProps = headerGroup.getHeaderGroupProps();
              return (
                <tr
                  {...hgProps}
                  key={hgProps.key}
                  className="bg-gradient-to-r from-indigo-600 via-indigo-500 to-purple-600 shadow-lg shadow-indigo-500/25"
                >
                  {headerGroup.headers.map((column) => {
                    const col = column as Record<string, unknown>;
                    const getSortProps = col.getSortByToggleProps as (() => Record<string, unknown>) | undefined;
                    const sortProps = getSortProps ? getSortProps() : {};
                    const headerProps = column.getHeaderProps(sortProps);
                    return (
                      <th
                        {...headerProps}
                        key={headerProps.key}
                        className={`p-4 text-center text-white/95 font-semibold text-xs uppercase tracking-wider select-none cursor-pointer hover:bg-white/10 transition-colors duration-200 ${
                          (col.className as string) || ""
                        }`}
                      >
                        <div className="flex items-center justify-center gap-2">
                          <span>{column.render("Header")}</span>
                          <span className="flex items-center text-white/60">
                            {col.isSorted ? (
                              col.isSortedDesc ? (
                                <FaSortDown className="text-white/90" />
                              ) : (
                                <FaSortUp className="text-white/90" />
                              )
                            ) : (
                              <FaSort className="opacity-30" />
                            )}
                          </span>
                        </div>
                      </th>
                    );
                  })}
                </tr>
              );
            })}
          </thead>

          {/* Body */}
          <tbody
            {...getTableBodyProps()}
            className="divide-y divide-gray-100 dark:divide-gray-800/80"
          >
            {rows.map((row, rowIndex) => {
              prepareRow(row);
              const score = row.original.quant_score;

              return (
                <tr
                  {...row.getRowProps()}
                  key={row.getRowProps().key}
                  onClick={async () => {
                    const companyName = row.original.company_name;

                    try {
                      await addViewedItem(companyName);
                    } catch (err) {
                      console.error("Failed to save viewed item:", err);
                    }

                    const url = `http://rfa.systemgroup.net?companyname=${encodeURIComponent(
                      companyName,
                    )}`;

                    window.open(url, "_blank");
                  }}
                  className={`
                    cursor-pointer transition-all duration-200 ease-out
                    border-l-[3px] ${rowBorderColor(score)}
                    hover:bg-indigo-50/70 dark:hover:bg-indigo-950/30
                    hover:shadow-lg hover:shadow-indigo-500/5
                    hover:-translate-y-[1px]
                    ${rowIndex % 2 === 0
                      ? "bg-white/40 dark:bg-gray-900/20"
                      : "bg-gray-50/40 dark:bg-gray-800/20"
                    }
                  `}
                >
                  {row.cells.map((cell) => (
                    <td
                      {...cell.getCellProps()}
                      key={cell.getCellProps().key}
                      className={`p-3 text-center text-gray-600 dark:text-gray-300 ${
                        (cell.column as Record<string, unknown>).className as string || ""
                      }`}
                    >
                      {cell.column.id === "row_number" ? (
                        <span className="font-medium text-gray-400 dark:text-gray-500 text-xs tabular-nums">
                          {rowIndex + 1}
                        </span>
                      ) : (
                        cell.render("Cell")
                      )}
                    </td>
                  ))}
                </tr>
              );
            })}

            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={columns.length}
                  className="text-center p-10 text-gray-400 dark:text-gray-500"
                >
                  داده‌ای یافت نشد
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export default BigDataTable;
