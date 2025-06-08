import React, { useMemo, useState } from "react";
import { useTable, useSortBy, useGlobalFilter } from "react-table";
import { FaSort, FaSortUp, FaSortDown, FaSearch } from "react-icons/fa";

interface DataRow {
  company_id: string;
  company_name: string;
  eps_growth: number;
  sales_growth: number;
  pe: number;
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
  } = tableInstance;

  const handleSearch = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value || "";
    setGlobalFilter(value);
    setFilter(value);
  };

  return (
    <div className="shadow-lg backdrop-blur-lg rounded-3xl border border-gray-200 dark:border-gray-700 py-[10px] px-[25px] ">
      <div className="relative mb-2 max-w-md mx-auto text-md ">
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
                  onClick={() => onCompanyChange(rowCompanyName)}
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
