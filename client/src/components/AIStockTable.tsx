// import React, { useEffect, useState } from "react";
// import {
//   analyzeTopStocks,
//   getAIStockSummary,
//   type AIStockMetric,
// } from "../utils/api";

// const fmt = (v: number | null | undefined, digits = 2) => {
//   if (v === null || v === undefined || Number.isNaN(v)) return "--";
//   return v.toFixed(digits);
// };

// const pct = (v: number | null | undefined) => {
//   if (v === null || v === undefined || Number.isNaN(v)) return "--";
//   return `${v.toFixed(2)}%`;
// };

// const AIStockTable: React.FC = () => {
//   const [data, setData] = useState<AIStockMetric[]>([]);
//   const [loading, setLoading] = useState(false);
//   const [aiLoading, setAiLoading] = useState(false);
//   const [aiResult, setAiResult] = useState<string>("");

//   const loadData = async () => {
//     setLoading(true);
//     try {
//       const rows = await getAIStockSummary(30);
//       setData(rows);
//     } finally {
//       setLoading(false);
//     }
//   };

//   const runAI = async () => {
//     setAiLoading(true);
//     setAiResult("");

//     try {
//       const result = await analyzeTopStocks(20);
//       setAiResult(result.ai_result || "");
//     } catch (err: any) {
//       setAiResult(err.message || "AI error");
//     } finally {
//       setAiLoading(false);
//     }
//   };

//   useEffect(() => {
//     loadData();
//   }, []);

//   return (
//     <div className="p-4 rounded-2xl border border-gray-200 dark:border-gray-700">
//       <div className="flex gap-2 mb-4">
//         <button
//           onClick={loadData}
//           disabled={loading}
//           className="px-4 py-2 rounded-xl bg-indigo-600 text-white disabled:opacity-50"
//         >
//           {loading ? "در حال دریافت..." : "دریافت کاندیدها"}
//         </button>

//         <button
//           onClick={runAI}
//           disabled={aiLoading}
//           className="px-4 py-2 rounded-xl bg-green-600 text-white disabled:opacity-50"
//         >
//           {aiLoading ? "در حال تحلیل..." : "تحلیل با AI"}
//         </button>
//       </div>

//       <div className="overflow-auto max-h-[70vh]">
//         <table className="min-w-full text-sm border-collapse">
//           <thead className="sticky top-0 bg-gray-100 dark:bg-gray-800">
//             <tr>
//               <th className="p-2">رتبه</th>
//               <th className="p-2">نماد</th>
//               <th className="p-2">شرکت</th>
//               <th className="p-2">امتیاز</th>
//               <th className="p-2">رشد فروش ۱۲M</th>
//               <th className="p-2">رشد سود عملیاتی</th>
//               <th className="p-2">رشد سود خالص</th>
//               <th className="p-2">P/E تقریبی</th>
//               <th className="p-2">قیمت</th>
//               <th className="p-2">بازده ۳۰D</th>
//               <th className="p-2">ارزش معاملات ۳۰D</th>
//               <th className="p-2">ریسک‌ها</th>
//             </tr>
//           </thead>

//           <tbody>
//             {data.map((row, index) => (
//               <tr
//                 key={row.company_id}
//                 className="border-b border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800"
//               >
//                 <td className="p-2 text-center">{index + 1}</td>
//                 <td className="p-2 text-center font-semibold">
//                   {row.symbol || "--"}
//                 </td>
//                 <td className="p-2 text-center">{row.company_name}</td>
//                 <td className="p-2 text-center font-semibold">
//                   {fmt(row.quant_score)}
//                 </td>
//                 <td className="p-2 text-center">{pct(row.sales_growth_12m)}</td>
//                 <td className="p-2 text-center">
//                   {pct(row.operating_profit_growth_yoy)}
//                 </td>
//                 <td className="p-2 text-center">
//                   {pct(row.net_profit_growth_4_reports)}
//                 </td>
//                 <td className="p-2 text-center">{fmt(row.pe_approx)}</td>
//                 <td className="p-2 text-center">{fmt(row.latest_price)}</td>
//                 <td className="p-2 text-center">{pct(row.price_return_30d)}</td>
//                 <td className="p-2 text-center">
//                   {fmt(row.avg_trade_value_30d, 0)}
//                 </td>
//                 <td className="p-2 text-center">
//                   {[
//                     row.bad_pe_flag ? "P/E" : "",
//                     row.weak_sales_flag ? "فروش" : "",
//                     row.weak_operating_profit_flag ? "سود عملیاتی" : "",
//                     row.weak_liquidity_flag ? "نقدشوندگی" : "",
//                   ]
//                     .filter(Boolean)
//                     .join("، ") || "--"}
//                 </td>
//               </tr>
//             ))}
//           </tbody>
//         </table>
//       </div>

//       {aiResult && (
//         <pre className="mt-4 p-4 rounded-xl bg-gray-100 dark:bg-gray-900 overflow-auto text-xs whitespace-pre-wrap">
//           {aiResult}
//         </pre>
//       )}
//     </div>
//   );
// };

// export default AIStockTable;
import React, { useEffect, useMemo, useState } from "react";
import {
  analyzeTopStocks,
  getAIStockSummary,
  type AIStockMetric,
} from "../utils/api";
import { FaSearch, FaSort, FaSortDown, FaSortUp } from "react-icons/fa";

const fmt = (v: number | null | undefined, digits = 2) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return v.toFixed(digits);
};

const pct = (v: number | null | undefined) => {
  if (v === null || v === undefined || Number.isNaN(v)) return "--";
  return `${v.toFixed(2)}%`;
};

type SortKey =
  | "rank"
  | "symbol"
  | "company_name"
  | "quant_score"
  | "sales_growth_12m"
  | "operating_profit_growth_yoy"
  | "net_profit_growth_4_reports"
  | "pe_approx"
  | "latest_price"
  | "price_return_30d"
  | "avg_trade_value_30d"
  | "risks";

type SortState = {
  key: SortKey;
  desc: boolean;
};

type Column = {
  key: SortKey;
  title: string;
  className?: string;
  sortable?: boolean;
};

const columns: Column[] = [
  { key: "rank", title: "ردیف", className: "w-20", sortable: false },
  { key: "symbol", title: "نماد", className: "w-24", sortable: true },
  { key: "company_name", title: "شرکت", className: "w-48", sortable: true },
  { key: "quant_score", title: "امتیاز", className: "w-28", sortable: true },
  {
    key: "sales_growth_12m",
    title: "رشد فروش ۱۲M",
    className: "w-36",
    sortable: true,
  },
  {
    key: "operating_profit_growth_yoy",
    title: "رشد سود عملیاتی",
    className: "w-40",
    sortable: true,
  },
  {
    key: "net_profit_growth_4_reports",
    title: "رشد سود خالص",
    className: "w-36",
    sortable: true,
  },
  { key: "pe_approx", title: "P/E تقریبی", className: "w-32", sortable: true },
  { key: "latest_price", title: "قیمت", className: "w-32", sortable: true },
  {
    key: "price_return_30d",
    title: "بازده ۳۰D",
    className: "w-32",
    sortable: true,
  },
  {
    key: "avg_trade_value_30d",
    title: "ارزش معاملات ۳۰D",
    className: "w-44",
    sortable: true,
  },
  { key: "risks", title: "ریسک‌ها", className: "w-44", sortable: false },
];

const getRisks = (row: AIStockMetric) => {
  return [
    row.bad_pe_flag ? "P/E" : "",
    row.weak_sales_flag ? "فروش" : "",
    row.weak_operating_profit_flag ? "سود عملیاتی" : "",
    row.weak_liquidity_flag ? "نقدشوندگی" : "",
  ]
    .filter(Boolean)
    .join("، ");
};

const getSortValue = (row: AIStockMetric, key: SortKey, index: number) => {
  if (key === "rank") return index + 1;
  if (key === "risks") return getRisks(row);
  return row[key as keyof AIStockMetric] as string | number | boolean | null;
};

const SortIcon = ({ active, desc }: { active: boolean; desc: boolean }) => {
  if (!active) return <FaSort className="opacity-40" />;
  return desc ? <FaSortDown /> : <FaSortUp />;
};

const PercentCell = ({ value }: { value: number }) => {
  let colorClass = "";

  if (value != null && value > 30) {
    colorClass = "text-green-600 dark:text-green-400 font-semibold";
  } else if (value != null && value < -10) {
    colorClass = "text-red-600 dark:text-red-400 font-semibold";
  }

  return <span className={colorClass}>{pct(value)}</span>;
};

const ScoreCell = ({ value }: { value: number }) => {
  let colorClass = "";

  // if (value >= 70) {
  //   colorClass = "text-green-600 dark:text-green-400 font-semibold";
  // } else if (value < 45) {
  //   colorClass = "text-red-600 dark:text-red-400 font-semibold";
  // } else {
  // }
  colorClass = "text-indigo-600 dark:text-indigo-400 font-semibold";

  return <span className={colorClass}>{fmt(value)}</span>;
};

const PECell = ({ value }: { value: number }) => {
  let colorClass = "";

  if (value != null && value > 0 && value < 6) {
    colorClass = "text-green-600 dark:text-green-400 font-semibold";
  } else if (value <= 0 || value > 80) {
    colorClass = "text-red-600 dark:text-red-400 font-semibold";
  }

  return <span className={colorClass}>{fmt(value)}</span>;
};

const RiskCell = ({ row }: { row: AIStockMetric }) => {
  const risks = getRisks(row);

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
};

const AIStockTable: React.FC = () => {
  const [data, setData] = useState<AIStockMetric[]>([]);
  const [loading, setLoading] = useState(false);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<string>("");
  const [globalFilter, setGlobalFilter] = useState("");
  const [sortState, setSortState] = useState<SortState>({
    key: "quant_score",
    desc: true,
  });

  const loadData = async () => {
    setLoading(true);

    try {
      const rows = await getAIStockSummary(30);
      setData(rows);
    } finally {
      setLoading(false);
    }
  };

  const runAI = async () => {
    setAiLoading(true);
    setAiResult("");

    try {
      const result = await analyzeTopStocks(20);
      setAiResult(result.ai_result || "");
    } catch (err: any) {
      setAiResult(err.message || "AI error");
    } finally {
      setAiLoading(false);
    }
  };

  const handleSort = (key: SortKey, sortable = true) => {
    if (!sortable) return;

    setSortState((prev) => {
      if (prev.key === key) {
        return { key, desc: !prev.desc };
      }

      return { key, desc: true };
    });
  };

  const filteredRows = useMemo(() => {
    const search = globalFilter.trim().toLowerCase();

    const filtered = data.filter((row) => {
      if (!search) return true;

      return (
        row.company_name?.toLowerCase().includes(search) ||
        row.symbol?.toLowerCase().includes(search) ||
        row.company_id?.toLowerCase().includes(search)
      );
    });

    return [...filtered].sort((a, b) => {
      const aIndex = data.indexOf(a);
      const bIndex = data.indexOf(b);

      const av = getSortValue(a, sortState.key, aIndex);
      const bv = getSortValue(b, sortState.key, bIndex);

      if (typeof av === "number" && typeof bv === "number") {
        return sortState.desc ? bv - av : av - bv;
      }

      const as = String(av ?? "");
      const bs = String(bv ?? "");

      const result = as.localeCompare(bs, "fa");
      return sortState.desc ? -result : result;
    });
  }, [data, globalFilter, sortState]);

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px] w-[75vw] mt-8">
      <div className="flex justify-start flex-wrap gap-2">
        <div className="relative mb-2 max-w-md mx-auto text-md ml-2">
          <FaSearch className="absolute top-1/2 left-3 -translate-y-1/2 text-gray-400 dark:text-gray-500" />
          <input
            type="text"
            value={globalFilter}
            onChange={(e) => setGlobalFilter(e.target.value)}
            placeholder="جستجوی نماد یا شرکت..."
            dir="rtl"
            className="p-2 w-full rounded-xl border border-gray-300 dark:border-gray-700 bg-gray-50 dark:bg-gray-800 text-gray-900 dark:text-gray-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 transition"
          />
        </div>

        <div className="text-center mb-2 mr-2">
          <button
            onClick={loadData}
            disabled={loading}
            className="bg-indigo-600 hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed text-white py-2 px-4 rounded-xl transition"
          >
            {loading ? "در حال دریافت..." : "دریافت کاندیدها"}
          </button>
        </div>

        {/* <div className="text-center mb-2 mr-2">
          <button
            onClick={runAI}
            disabled={aiLoading}
            className="bg-green-600 hover:bg-green-700 disabled:opacity-50 disabled:cursor-not-allowed text-white py-2 px-4 rounded-xl transition"
          >
            {aiLoading ? "در حال تحلیل..." : "تحلیل با AI"}
          </button>
        </div> */}

        {/* <div className="text-center mb-2 mr-2">
          <button
            onClick={() => setSortState({ key: "quant_score", desc: true })}
            className="bg-indigo-600 hover:bg-indigo-700 text-white py-2 px-4 rounded-xl transition"
          >
            Golden Sort
          </button>
        </div> */}
      </div>

      <div className="overflow-auto max-h-[82vh]">
        <table
          className="min-w-full text-sm border-collapse rounded-xl overflow-auto max-h-[82vh]"
          style={{ borderSpacing: 0 }}
        >
          <thead className="bg-gray-50 dark:bg-gray-800 sticky top-0 z-10">
            <tr>
              {columns.map((column) => {
                const active = sortState.key === column.key;

                return (
                  <th
                    key={column.key}
                    onClick={() => handleSort(column.key, column.sortable)}
                    className={`p-4 text-center text-gray-700 dark:text-gray-300 font-semibold select-none ${
                      column.sortable ? "cursor-pointer" : ""
                    } ${column.className || ""}`}
                  >
                    <div className="flex items-center justify-center gap-2 whitespace-nowrap">
                      <span>{column.title}</span>

                      {column.sortable && (
                        <span className="flex items-center text-indigo-500">
                          <SortIcon active={active} desc={sortState.desc} />
                        </span>
                      )}
                    </div>
                  </th>
                );
              })}
            </tr>
          </thead>

          <tbody className="divide-y divide-gray-200 dark:divide-gray-700">
            {filteredRows.map((row, rowIndex) => (
              <tr
                key={row.company_id}
                className="cursor-pointer transition-colors duration-300 hover:bg-indigo-50 dark:hover:bg-gray-800"
              >
                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <span className="font-medium">{rowIndex + 1}</span>
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <span className="font-semibold text-gray-900 dark:text-gray-100">
                    {row.symbol || "--"}
                  </span>
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {row.company_name}
                  </span>
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <ScoreCell value={row.quant_score} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <PercentCell value={row.sales_growth_12m} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <PercentCell value={row.operating_profit_growth_yoy} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <PercentCell value={row.net_profit_growth_4_reports} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <PECell value={row.pe_approx} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  {fmt(row.latest_price)}
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <PercentCell value={row.price_return_30d} />
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  {fmt(row.avg_trade_value_30d, 0)}
                </td>

                <td className="p-2 text-center text-gray-700 dark:text-gray-300">
                  <RiskCell row={row} />
                </td>
              </tr>
            ))}

            {filteredRows.length === 0 && (
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

      {aiResult && (
        <pre
          dir="rtl"
          className="mt-4 p-4 rounded-2xl border border-gray-200 dark:border-gray-700 bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-100 overflow-auto text-xs whitespace-pre-wrap leading-6"
        >
          {aiResult}
        </pre>
      )}
    </div>
  );
};

export default AIStockTable;
