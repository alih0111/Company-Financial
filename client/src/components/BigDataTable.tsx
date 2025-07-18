import React, { useMemo, useState } from "react";
import { useTable, useSortBy, useGlobalFilter } from "react-table";
import { FaSort, FaSortUp, FaSortDown, FaSearch } from "react-icons/fa";
import * as XLSX from "xlsx";
import { saveAs } from "file-saver";

interface DataRow {
  company_id: string;
  company_name: string;
  eps_growth: number;
  sales_growth: number;
  pe: number;
  stable: boolean;
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
        accessor: "Stable",
        sortType: "basic",
        className: "w-16",
        Cell: ({ value }: { value: boolean | null | undefined }) => {
          let colorClass = "";
          if (value === true) {
            colorClass = "text-green-600 dark:text-green-400 font-semibold";
          } else {
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
        Header: "P/E",
        accessor: "pe",
        sortType: "basic",
        className: "w-32",
        Cell: ({ value }: { value: number }) => {
          let colorClass = "";
          if (value != null && value < 6 && value > 0)
            colorClass = "text-green-600 dark:text-green-400 font-semibold";

          return (
            <span className={colorClass}>
              {value != null ? value.toFixed(2) : "--"}
            </span>
          );
        },
      },
      {
        Header: "EPS Growth (%)",
        accessor: "eps_growth",
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

      {
        Header: "Sales Growth (%)",
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
      {
        Header: "ردیف",
        id: "row_number",
        Cell: ({ row }: { row: any }) => (
          <span className="font-medium text-gray-700 dark:text-gray-300">
            {row.index + 1}
          </span>
        ),
        disableSortBy: true,
        className: "w-20",
      },
    ],
    []
  );

  const tableInstance = useTable(
    {
      columns,
      data,
      initialState: { hiddenColumns: [] },
    },
    useGlobalFilter,
    useSortBy
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

  // Add this function inside your component
  const exportToExcel = () => {
    debugger;
    const exportData = data.map((row, index) => ({
      ردیف: index + 1,
      "Company Name": row.company_name,
      "P/E": row.pe?.toFixed(2),
      "EPS Growth (%)": row.eps_growth?.toFixed(2) + "%",
      "Sales Growth (%)": row.sales_growth?.toFixed(2) + "%",
      Stable: row.Stable ? "Yes" : "No",
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
    saveAs(dataBlob, "BigDataTable.xlsx");
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
            {rows.map((row) => {
              prepareRow(row);
              const rowCompanyName = row.original.company_name;

              return (
                <tr
                  {...row.getRowProps()}
                  key={row.getRowProps().key}
                  onClick={() => {
                    const url = `http://rfa.systemgroup.net?companyname=${row.original.company_name}`;
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
                      {cell.render("Cell")}
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
