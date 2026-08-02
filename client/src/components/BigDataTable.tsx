import React, { useMemo, useState } from "react";
import { useTable, useSortBy, useGlobalFilter } from "react-table";
import { FaSort, FaSortUp, FaSortDown, FaSearch } from "react-icons/fa";
import * as XLSX from "xlsx";
import { saveAs } from "file-saver";
import { addViewedItem } from "../utils/api";

const API_BASE = "http://rfa_back.systemgroup.net/api";

const fmt = (v: number | null | undefined, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return v.toFixed(digits);
};

const pct = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return `${v.toFixed(2)}%`;
};

const getStableValue = (row: DataRow): boolean | null => {
  return row.stable ?? row.Stable ?? null;
};

const getRisks = (row: DataRow): string => {
  return [
    row.bad_pe_flag ? "P/E" : "",
    row.weak_sales_flag ? "فروش" : "",
    row.weak_operating_profit_flag ? "سود عملیاتی" : "",
    row.weak_liquidity_flag ? "نقدشوندگی" : "",
    row.loss_maker_flag ? "زیان‌ده" : "",
    row.weak_coverage_flag ? "بهره" : "",
    row.margin_contraction_flag ? "انقباض حاشیه" : "",
  ]
    .filter(Boolean)
    .join("، ");
};

// مرتب‌سازی عددی با مدیریت null
// nullها همیشه آخر (چه صعودی چه نزولی)
const numericSort = (
  rowA: any,
  rowB: any,
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

  // react-table نتیجه را در حالت desc معکوس می‌کند؛
  // بنابراین اینجا باید جهت را لحاظ کنیم تا null همیشه آخر بماند.
  if (a === null) return desc ? -1 : 1;
  if (b === null) return desc ? 1 : -1;

  return a - b;
};
// const numericSort = (
//   rowA: any,
//   rowB: any,
//   columnId: string,
//   desc?: boolean,
// ) => {
//   const a = rowA.values[columnId];
//   const b = rowB.values[columnId];

//   const aVal =
//     a == null || a === "" || Number.isNaN(Number(a)) ? null : Number(a);
//   const bVal =
//     b == null || b === "" || Number.isNaN(Number(b)) ? null : Number(b);

//   // هر دو null
//   if (aVal == null && bVal == null) return 0;
//   // null همیشه آخر (جهت‌مستقل)
//   if (aVal == null) return 1;
//   if (bVal == null) return -1;

//   // مقادیر واقعی
//   if (aVal === bVal) return 0;
//   // صعودی: a > b یعنی a بعد (1)
//   return aVal > bVal ? 1 : -1;
// };

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
  selectedCompany: string;
  onCompanyChange: (name: string) => void;
}

const BigDataTable: React.FC<Props> = ({
  data,
  selectedCompany,
  onCompanyChange,
}) => {
  const [globalFilter, setGlobalFilter] = useState("");

  const columns = useMemo(
    () => [
      {
        Header: "Stable",
        id: "Stable",
        accessor: (row: DataRow) => getStableValue(row),
        sortType: "basic",
        className: "w-16",
        Cell: ({ value }: { value: boolean | null | undefined }) => {
          let colorClass = "";
          if (value === true) {
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          } else if (value === false) {
            colorClass = "text-red-700 dark:text-red-400 font-semibold";
          }

          return (
            <span className={colorClass}>
              {value === true ? "Yes" : value === false ? "No" : "--"}
            </span>
          );
        },
      },
      {
        Header: "nonOperating",
        accessor: "non_operating_pct",
        sortType: "numericSort",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null && Number.isFinite(value)) {
            if (value < 5) {
              colorClass = "text-green-600 dark:text-green-400";
            } else if (value < 15) {
              colorClass = "text-yellow-600 dark:text-yellow-400";
            } else if (value < 30) {
              colorClass = "text-orange-600 dark:text-orange-400";
            } else {
              colorClass = "text-red-600 dark:text-red-400 font-semibold";
            }
          }

          return (
            <span className={colorClass}>
              {value != null && Number.isFinite(value)
                ? value.toFixed(2) + "%"
                : "--"}
            </span>
          );
        },
      },
      // {
      //   Header: "حاشیه عملیاتی",
      //   accessor: "operation",
      //   sortType: "basic",
      //   className: "w-32",
      //   Cell: ({ value }: { value: number | null | undefined }) => {
      //     let colorClass = "";

      //     if (value != null) {
      //       if (value >= 25) {
      //         colorClass = "text-green-600 dark:text-green-400 font-bold";
      //       } else if (value >= 15) {
      //         colorClass = "text-green-600 dark:text-green-400 font-medium";
      //       } else if (value >= 10) {
      //         colorClass = "text-lime-600 dark:text-lime-400";
      //       } else if (value >= 5) {
      //         colorClass = "text-yellow-600 dark:text-yellow-400";
      //       } else if (value > 0) {
      //         colorClass = "text-orange-600 dark:text-orange-400";
      //       } else {
      //         colorClass = "text-red-600 dark:text-red-400 font-semibold";
      //       }
      //     }

      //     return (
      //       <span className={colorClass}>
      //         {value != null ? value.toFixed(2) + "%" : "--"}
      //       </span>
      //     );
      //   },
      // },
      {
        Header: "Score",
        id: "quant_score",

        accessor: (row: DataRow) => {
          const value = row.quant_score;

          if (value === null || value === undefined || value === "") {
            return null;
          }

          const parsed = Number(value);
          return Number.isFinite(parsed) ? parsed : null;
        },

        sortType: "numericSort",
        sortDescFirst: true,
        className: "w-28",

        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null) {
            if (value >= 70) {
              colorClass = "text-green-600 dark:text-green-400 font-bold";
            } else if (value >= 55) {
              colorClass = "text-green-600 dark:text-green-400 font-semibold";
            } else if (value >= 40) {
              colorClass = "text-indigo-600 dark:text-indigo-400 font-semibold";
            } else if (value >= 25) {
              colorClass = "text-yellow-600 dark:text-yellow-400";
            } else {
              colorClass = "text-red-600 dark:text-red-400 font-semibold";
            }
          }

          return (
            <span className={colorClass}>
              {value != null && Number.isFinite(value)
                ? value.toFixed(2)
                : "--"}
            </span>
          );
        },
      },

      {
        Header: "EPS Growth",
        accessor: "eps_growth",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number }) => {
          let colorClass = "";
          if (value != null && value > 30)
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          else if (value != null && value < -10)
            colorClass = "text-red-600 dark:text-red-400 font-semibold";

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) + "%" : "--"}
            </span>
          );
        },
      },
      {
        Header: "Sales Growth",
        accessor: "sales_growth",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number }) => {
          let colorClass = "";
          if (value != null && value > 50)
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          else if (value != null && value < -10)
            colorClass = "text-red-600 dark:text-red-400 font-semibold";

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) + "%" : "--"}
            </span>
          );
        },
      },
      // {
      //   Header: "P/E",
      //   accessor: "pe",
      //   sortType: "basic",
      //   className: "w-28",
      //   Cell: ({ value }: { value: number }) => {
      //     let colorClass = "";
      //     if (value != null && value < 6 && value > 0)
      //       colorClass = "text-green-600 dark:text-green-400 font-semibold";
      //     else if (value != null && (value <= 0 || value > 80))
      //       colorClass = "text-red-600 dark:text-red-400 font-semibold";

      //     return (
      //       <span className={colorClass}>
      //         {value != null ? value.toFixed(2) : "--"}
      //       </span>
      //     );
      //   },
      // },
      {
        Header: "Company",
        accessor: "company_name",
        className: "w-32",
        Cell: ({ value }: { value: string }) => (
          <span className="font-medium text-gray-900 dark:text-gray-100">
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
    setGlobalFilter: setFilter,
    setSortBy,
  } = tableInstance;

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value || "";
    setGlobalFilter(value);
    setFilter(value);
  };

  const exportFullScoresCSV = () => {
    const token = localStorage.getItem("token");
    const url = `${API_BASE}/export/scores?limit=1000`;
    fetch(url, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then((res) => {
        if (!res.ok) throw new Error("خطا در دریافت فایل");
        return res.blob();
      })
      .then((blob) => {
        const today = new Date().toISOString().slice(0, 10);
        saveAs(blob, `stock_scores_${today}.csv`);
      })
      .catch((err) => alert(err.message));
  };

  const exportToExcel = () => {
    const exportData = data.map((row, index) => ({
      ردیف: index + 1,
      "Company Name": row.company_name,
      Stable:
        getStableValue(row) === true
          ? "Yes"
          : getStableValue(row) === false
            ? "No"
            : "--",
      "AI Score": fmt(row.quant_score),
      غیرعملیاتی: pct(row.non_operating_pct),
      "حاشیه عملیاتی": pct(row.operation),
      "EPS Growth (%)":
        row.eps_growth != null ? row.eps_growth.toFixed(2) + "%" : "--",
      "Sales Growth (%)":
        row.sales_growth != null ? row.sales_growth.toFixed(2) + "%" : "--",
      "P/E": row.pe != null ? row.pe.toFixed(2) : "--",
    }));

    const worksheet = XLSX.utils.json_to_sheet(exportData);
    const workbook = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(workbook, worksheet, "Data");

    const excelBuffer = XLSX.write(workbook, {
      bookType: "xlsx",
      type: "array",
    });

    const dataBlob = new Blob([excelBuffer], {
      type: "application/octet-stream",
    });

    const today = new Date();
    const dateStr = today.toISOString().split("T")[0];

    saveAs(dataBlob, `RFADataTable_${dateStr}.xlsx`);
  };

  return (
    <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px] ">
      <div className="flex justify-start">
        <div className="relative mb-2 max-w-md mx-auto text-md ml-0">
          <FaSearch className="absolute top-1/2 left-3 -translate-y-1/2 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            value={globalFilter}
            onChange={handleSearch}
            placeholder="جستجوی شرکت..."
            dir="rtl"
            className="p-2 w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition"
          />
        </div>
        <div className="mb-2 mr-2 flex justify-center gap-3">
          <button
            onClick={() =>
              setSortBy([
                { id: "Stable", desc: true },
                { id: "eps_growth", desc: true },
              ])
            }
            className="
      rounded-xl border border-slate-300
      bg-gradient-to-br from-slate-100 via-slate-300 to-slate-400
      px-4 py-2 font-semibold text-slate-800
      shadow-md transition-all duration-200
      hover:-translate-y-0.5 hover:from-slate-200 hover:to-slate-500
      hover:shadow-lg
      focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2
    "
          >
            ◇ Silver
          </button>

          {/* <button
            onClick={() => setSortBy([{ id: "quant_score", desc: true }])}
            className="
              rounded-xl border border-amber-400
              bg-gradient-to-br from-amber-300 via-yellow-400 to-amber-500
              px-4 py-2 font-semibold text-amber-950
              shadow-md transition-all duration-200
              hover:-translate-y-0.5 hover:from-amber-400 hover:to-orange-500
              hover:shadow-lg
              focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2
            "
          >
            ★ Golden
          </button> */}
        </div>
        <div className="mb-2 mr-2 flex justify-center gap-2">
          {/* <button
            onClick={exportToExcel}
            className="
      inline-flex items-center gap-2
      rounded-xl border border-emerald-500
      bg-gradient-to-br from-emerald-400 via-emerald-500 to-green-600
      px-4 py-2 font-semibold text-white
      shadow-md transition-all duration-200
      hover:-translate-y-0.5 hover:from-emerald-500 hover:to-green-700
      hover:shadow-lg
      active:translate-y-0 active:shadow-md
      focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2
    "
          >
            <span aria-hidden="true">📊</span>
            Export
          </button> */}

          {/* <button
            onClick={exportFullScoresCSV}
            className="
      inline-flex items-center gap-2
      rounded-xl border border-indigo-500
      bg-gradient-to-br from-indigo-400 via-indigo-500 to-purple-600
      px-4 py-2 font-semibold text-white
      shadow-md transition-all duration-200
      hover:-translate-y-0.5 hover:from-indigo-500 hover:to-purple-700
      hover:shadow-lg
      active:translate-y-0 active:shadow-md
      focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2
    "
          >
            <span aria-hidden="true">🧠</span>
            امتیازات
          </button> */}
        </div>
      </div>
      <div className=" overflow-auto max-h-[82vh]">
        <table
          {...getTableProps()}
          className="min-w-full text-sm border-collapse rounded-xl overflow-auto max-h-[82vh]"
          style={{ borderSpacing: 0 }}
        >
          <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0 z-10">
            {headerGroups.map((headerGroup) => (
              <tr
                {...headerGroup.getHeaderGroupProps()}
                key={headerGroup.getHeaderGroupProps().key}
              >
                {headerGroup.headers.map((column) => (
                  <th
                    {...column.getHeaderProps(column.getSortByToggleProps())}
                    key={column.getHeaderProps().key}
                    className={`p-4 text-center text-gray-700 dark:text-gray-300 font-semibold select-none cursor-pointer ${
                      column.className || ""
                    }`}
                  >
                    <div className="flex items-center justify-center gap-2">
                      <span>{column.render("Header")}</span>
                      <span className="flex items-center text-indigo-500">
                        {column.isSorted ? (
                          column.isSortedDesc ? (
                            <FaSortDown />
                          ) : (
                            <FaSortUp />
                          )
                        ) : (
                          <FaSort className="opacity-40" />
                        )}
                      </span>
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>

          <tbody
            {...getTableBodyProps()}
            className="divide-y divide-gray-200 dark:divide-gray-700"
          >
            {rows.map((row, rowIndex) => {
              prepareRow(row);
              const rowCompanyName = row.original.company_name;

              return (
                <tr
                  {...row.getRowProps()}
                  key={row.getRowProps().key}
                  // onClick={() => {
                  //   const url = `http://rfa.systemgroup.net?companyname=${row.original.company_name}`;
                  //   window.open(url, "_blank");
                  // }}
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
                  className="cursor-pointer transition-colors duration-300 hover:bg-indigo-50 dark:hover:bg-gray-800"
                >
                  {row.cells.map((cell) => (
                    <td
                      {...cell.getCellProps()}
                      key={cell.getCellProps().key}
                      className={`p-2 text-center text-gray-700 dark:text-gray-300 ${
                        cell.column.className || ""
                      }`}
                    >
                      {cell.column.id === "row_number" ? (
                        <span className="font-medium text-gray-700 dark:text-gray-300">
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
                  className="text-center p-6 text-gray-500 dark:text-gray-400"
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
