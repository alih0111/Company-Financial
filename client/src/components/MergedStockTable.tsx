import React, { useEffect, useMemo, useState } from "react";
import { useTable, useSortBy, useGlobalFilter } from "react-table";
import { FaSort, FaSortUp, FaSortDown, FaSearch } from "react-icons/fa";
import * as XLSX from "xlsx";
import { saveAs } from "file-saver";
import {
  addViewedItem,
  getAIStockSummary,
  type AIStockMetric,
} from "../utils/api";

interface DataRow {
  company_id: string;
  company_name: string;
  eps_growth?: number | null;
  sales_growth?: number | null;
  pe?: number | null;
  stable?: boolean | null;
  Stable?: boolean | null;
  operation?: number | null;
}

interface Props {
  data: DataRow[];
  selectedCompany: string;
  onCompanyChange: (name: string) => void;
}

type MergedRow = DataRow & {
  ai?: AIStockMetric | null;
};

const fmt = (v: number | null | undefined, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return v.toFixed(digits);
};

const pct = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return `${v.toFixed(2)}%`;
};

const normalize = (v?: string | null) => (v || "").trim().toLowerCase();

const getStableValue = (row: MergedRow) => {
  return row.stable ?? row.Stable ?? null;
};

const getRisks = (row?: AIStockMetric | null) => {
  if (!row) return "";

  return [
    row.bad_pe_flag ? "P/E" : "",
    row.weak_sales_flag ? "فروش" : "",
    row.weak_operating_profit_flag ? "سود عملیاتی" : "",
    row.weak_liquidity_flag ? "نقدشوندگی" : "",
  ]
    .filter(Boolean)
    .join("، ");
};

const PercentCell = ({ value }: { value: number | null | undefined }) => {
  let colorClass = "";

  if (value != null && value > 30) {
    colorClass = "text-green-600 dark:text-green-400 font-semibold";
  } else if (value != null && value < -10) {
    colorClass = "text-red-600 dark:text-red-400 font-semibold";
  }

  return <span className={colorClass}>{pct(value)}</span>;
};

const PECell = ({ value }: { value: number | null | undefined }) => {
  let colorClass = "";

  if (value != null && value > 0 && value < 6) {
    colorClass = "text-green-600 dark:text-green-400 font-semibold";
  } else if (value != null && (value <= 0 || value > 80)) {
    colorClass = "text-red-600 dark:text-red-400 font-semibold";
  }

  return <span className={colorClass}>{fmt(value)}</span>;
};

const MergedStockTable: React.FC<Props> = ({
  data,
  selectedCompany,
  onCompanyChange,
}) => {
  const [globalFilter, setGlobalFilter] = useState("");
  const [aiData, setAiData] = useState<AIStockMetric[]>([]);
  const [aiLoading, setAiLoading] = useState(false);

  const loadAIData = async () => {
    setAiLoading(true);

    try {
      const rows = await getAIStockSummary(30);
      setAiData(Array.isArray(rows) ? rows : []);
    } catch (err) {
      console.error("Failed to load AI stock summary:", err);
      setAiData([]);
    } finally {
      setAiLoading(false);
    }
  };

  useEffect(() => {
    loadAIData();
  }, []);

  const mergedData = useMemo<MergedRow[]>(() => {
    const aiById = new Map<string, AIStockMetric>();
    const aiByName = new Map<string, AIStockMetric>();

    aiData.forEach((row) => {
      if (row.company_id) aiById.set(row.company_id, row);
      if (row.company_name) aiByName.set(normalize(row.company_name), row);
    });

    return data.map((row) => ({
      ...row,
      ai:
        aiById.get(row.company_id) ||
        aiByName.get(normalize(row.company_name)) ||
        null,
    }));
  }, [data, aiData]);

  const columns = useMemo<any[]>(
    () => [
      {
        Header: "Stable",
        id: "Stable",
        accessor: (row: MergedRow) => getStableValue(row),
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
        Header: "حاشیه سود عملیاتی",
        accessor: "operation",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null) {
            if (value >= 25) {
              colorClass = "text-green-600 dark:text-green-400 font-bold";
            } else if (value >= 15) {
              colorClass = "text-green-600 dark:text-green-400 font-medium";
            } else if (value >= 10) {
              colorClass = "text-lime-600 dark:text-lime-400";
            } else if (value >= 5) {
              colorClass = "text-yellow-600 dark:text-yellow-400";
            } else if (value > 0) {
              colorClass = "text-orange-600 dark:text-orange-400";
            } else {
              colorClass = "text-red-600 dark:text-red-400 font-semibold";
            }
          }

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) + "%" : "--"}
            </span>
          );
        },
      },
      {
        Header: "P/E",
        accessor: "pe",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null && value < 6 && value > 0) {
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          }

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) : "--"}
            </span>
          );
        },
      },
      {
        Header: "EPS Growth",
        accessor: "eps_growth",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null && value > 30) {
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          } else if (value != null && value < -10) {
            colorClass = "text-red-600 dark:text-red-400 font-semibold";
          }

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
        Cell: ({ value }: { value: number | null | undefined }) => {
          let colorClass = "";

          if (value != null && value > 50) {
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          } else if (value != null && value < -10) {
            colorClass = "text-red-600 dark:text-red-400 font-semibold";
          }

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) + "%" : "--"}
            </span>
          );
        },
      },
      {
        Header: "Company Name",
        accessor: "company_name",
        className: "w-32",
        Cell: ({ value }: { value: string }) => (
          <span className="font-medium text-gray-900 dark:text-gray-100">
            {value}
          </span>
        ),
      },

      // AI columns start here
      {
        Header: "نماد",
        id: "symbol",
        accessor: (row: MergedRow) => row.ai?.symbol || "",
        sortType: "basic",
        className: "w-24",
        Cell: ({ value }: { value: string }) => (
          <span className="font-semibold text-gray-900 dark:text-gray-100">
            {value || "--"}
          </span>
        ),
      },
      {
        Header: "AI Score",
        id: "quant_score",
        accessor: (row: MergedRow) => row.ai?.quant_score ?? null,
        sortType: "basic",
        className: "w-28",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <span className="text-indigo-600 dark:text-indigo-400 font-semibold">
            {fmt(value)}
          </span>
        ),
      },
      {
        Header: "رشد فروش ۱۲M",
        id: "sales_growth_12m",
        accessor: (row: MergedRow) => row.ai?.sales_growth_12m ?? null,
        sortType: "basic",
        className: "w-36",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <PercentCell value={value} />
        ),
      },
      {
        Header: "رشد سود عملیاتی",
        id: "operating_profit_growth_yoy",
        accessor: (row: MergedRow) =>
          row.ai?.operating_profit_growth_yoy ?? null,
        sortType: "basic",
        className: "w-40",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <PercentCell value={value} />
        ),
      },
      {
        Header: "رشد سود خالص",
        id: "net_profit_growth_4_reports",
        accessor: (row: MergedRow) =>
          row.ai?.net_profit_growth_4_reports ?? null,
        sortType: "basic",
        className: "w-36",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <PercentCell value={value} />
        ),
      },
      {
        Header: "AI P/E",
        id: "pe_approx",
        accessor: (row: MergedRow) => row.ai?.pe_approx ?? null,
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <PECell value={value} />
        ),
      },
      {
        Header: "قیمت",
        id: "latest_price",
        accessor: (row: MergedRow) => row.ai?.latest_price ?? null,
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => fmt(value),
      },
      {
        Header: "بازده ۳۰D",
        id: "price_return_30d",
        accessor: (row: MergedRow) => row.ai?.price_return_30d ?? null,
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number | null | undefined }) => (
          <PercentCell value={value} />
        ),
      },
      {
        Header: "ارزش معاملات ۳۰D",
        id: "avg_trade_value_30d",
        accessor: (row: MergedRow) => row.ai?.avg_trade_value_30d ?? null,
        sortType: "basic",
        className: "w-44",
        Cell: ({ value }: { value: number | null | undefined }) =>
          fmt(value, 0),
      },
      {
        Header: "ریسک‌ها",
        id: "risks",
        accessor: (row: MergedRow) => getRisks(row.ai),
        disableSortBy: true,
        className: "w-44",
        Cell: ({ row }: any) => {
          const risks = getRisks(row.original.ai);

          if (!risks) {
            return (
              <span className="text-green-600 dark:text-green-400 font-semibold">
                --
              </span>
            );
          }

          return (
            <span className="text-red-600 dark:text-red-400 font-semibold">
              {risks}
            </span>
          );
        },
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

  const tableInstance = useTable<MergedRow>(
    {
      columns,
      data: mergedData,
      initialState: { hiddenColumns: [] },
    },
    useGlobalFilter,
    useSortBy,
  ) as any;

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

  const exportToExcel = () => {
    const exportData = mergedData.map((row, index) => ({
      ردیف: index + 1,
      "Company Name": row.company_name,
      "P/E": row.pe != null ? row.pe.toFixed(2) : "--",
      "EPS Growth (%)":
        row.eps_growth != null ? row.eps_growth.toFixed(2) + "%" : "--",
      "Sales Growth (%)":
        row.sales_growth != null ? row.sales_growth.toFixed(2) + "%" : "--",
      Stable:
        getStableValue(row) === true
          ? "Yes"
          : getStableValue(row) === false
            ? "No"
            : "--",
      "حاشیه سود عملیاتی": pct(row.operation),

      نماد: row.ai?.symbol || "--",
      "AI Score": fmt(row.ai?.quant_score),
      "رشد فروش ۱۲M": pct(row.ai?.sales_growth_12m),
      "رشد سود عملیاتی": pct(row.ai?.operating_profit_growth_yoy),
      "رشد سود خالص": pct(row.ai?.net_profit_growth_4_reports),
      "AI P/E": fmt(row.ai?.pe_approx),
      قیمت: fmt(row.ai?.latest_price),
      "بازده ۳۰D": pct(row.ai?.price_return_30d),
      "ارزش معاملات ۳۰D": fmt(row.ai?.avg_trade_value_30d, 0),
      ریسک‌ها: getRisks(row.ai) || "--",
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
        <div className="relative mb-2 max-w-md mx-auto text-md ml-2">
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

        <div className="text-center mb-2 mr-2">
          <button
            onClick={() =>
              setSortBy([
                { id: "Stable", desc: true },
                { id: "eps_growth", desc: true },
              ])
            }
            className="bg-indigo-600 hover:bg-indigo-700 text-white py-2 px-4 rounded-xl transition"
          >
            Golden Sort
          </button>
        </div>

        {/* <div className="text-center mb-2 mr-2">
          <button
            onClick={loadAIData}
            disabled={aiLoading}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white py-2 px-4 rounded-xl transition"
          >
            {aiLoading ? "در حال دریافت..." : "دریافت کاندیدها"}
          </button>
        </div> */}

        <div className="text-center mb-2 mr-2">
          <button
            onClick={exportToExcel}
            className="bg-green-600 hover:bg-green-700 text-white py-2 px-4 rounded-xl transition"
          >
            Export to Excel
          </button>
        </div>
      </div>

      <div className=" overflow-auto max-h-[82vh]">
        <table
          {...getTableProps()}
          className="min-w-full text-sm border-collapse rounded-xl overflow-auto max-h-[82vh]"
          style={{ borderSpacing: 0 }}
        >
          <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0 z-10">
            {headerGroups.map((headerGroup: any) => (
              <tr
                {...headerGroup.getHeaderGroupProps()}
                key={headerGroup.getHeaderGroupProps().key}
              >
                {headerGroup.headers.map((column: any) => (
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
            {rows.map((row: any, rowIndex: number) => {
              prepareRow(row);

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
                  className="cursor-pointer transition-colors duration-300 hover:bg-indigo-50 dark:hover:bg-gray-800"
                >
                  {row.cells.map((cell: any) => (
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

export default MergedStockTable;
