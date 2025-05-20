import React, { useEffect, useState } from "react";
import ChartComponent from "./ChartComponent";
import Select from "react-select";
import { FaSun, FaMoon } from "react-icons/fa"; // optional, if you want icons

interface Metadata {
  companyName: string;
  rowMeta: number;
  baseUrl: string;
  pageNumbers: number[];
}

interface OptionType {
  value: string;
  label: string;
}

interface CompanyData {
  companyName: string;
  [key: string]: any;
}

function App() {
  const [data, setData] = useState<CompanyData[]>([]);
  const [selectedCompany, setSelectedCompany] = useState<string>("");
  const [showModal, setShowModal] = useState<boolean>(false);
  const [metadata, setMetadata] = useState<Metadata>({
    companyName: "",
    rowMeta: 20,
    baseUrl: "",
    pageNumbers: [1, 2],
  });
  const [companyOptions, setCompanyOptions] = useState<string[]>([]);

  const [loadingCompanies, setLoadingCompanies] = useState<boolean>(true);
  const [loadingData, setLoadingData] = useState<boolean>(false);
  const [runningScript, setRunningScript] = useState<boolean>(false);

  const [darkMode, setDarkMode] = useState<boolean>(false);

  useEffect(() => {
    loadCompanyNames();
  }, []);

  useEffect(() => {
    if (selectedCompany) {
      setLoadingData(true);
      fetch(
        `http://localhost:5000/api/SalesData?companyName=${encodeURIComponent(
          selectedCompany
        )}`
      )
        .then((res) => res.json())
        .then((json) => setData(json))
        .catch((err) => {
          console.error("Failed to fetch company data", err);
        })
        .finally(() => {
          setLoadingData(false);
        });
    }
  }, [selectedCompany]);

  const handleSubmitMetadata = () => {
    setShowModal(false);
    setRunningScript(true);

    fetch("http://localhost:5000/run-script", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(metadata),
    })
      .then((res) => res.json())
      .then((result) => {
        alert(result.message);
        loadCompanyNames();
      })
      .catch((err) => {
        alert("Error running script");
        console.error(err);
      })
      .finally(() => {
        setRunningScript(false);
      });
  };

  const loadCompanyNames = () => {
    setLoadingCompanies(true);
    fetch("http://localhost:5000/api/CompanyNames")
      .then((res) => res.json())
      .then((json: string[]) => {
        setCompanyOptions(json);
        if (json.length > 0) {
          setSelectedCompany(json[0]);
        }
      })
      .catch((err) => {
        console.error("Failed to fetch company options", err);
      })
      .finally(() => {
        setLoadingCompanies(false);
      });
  };

  const btnClicked = () => {
    getUrl();
    setShowModal(true);
  };

  const getUrl = () => {
    if (!data[0]?.companyName) return;

    setLoadingCompanies(true);
    fetch("http://localhost:5000/api/GetUrl", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ companyName: data[0].companyName }),
    })
      .then((res) => res.json())
      .then((json: { url: string }) => {
        setMetadata((prev) => ({
          ...prev,
          baseUrl: json.url || "",
          companyName: data[0].companyName,
        }));
      })
      .catch((err) => {
        console.error("Failed to fetch company URL", err);
      })
      .finally(() => {
        setLoadingCompanies(false);
      });
  };

  const companySelectOptions: OptionType[] = companyOptions.map((name) => ({
    value: name,
    label: name,
  }));

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  }, [darkMode]);
  

  return (
    // <div className="min-h-screen p-6 bg-gray-100 dark:bg-gray-900 dark:text-white transition-colors duration-300">
    //   <div className="max-w-4xl mx-auto bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8">
    //     <h1 className="text-2xl font-semibold text-gray-900 dark:text-white mb-6 text-center">
    //       📊 Company Financial Overview
    //     </h1>
    //     <span className="mt-6 text-center">
    //       <button
    //         onClick={() => setDarkMode(!darkMode)}
    //         className="px-4 py-2 bg-gray-300 dark:bg-gray-700 rounded-md focus:outline-none hover:bg-gray-400 dark:hover:bg-gray-600 transition"
    //       >
    //         Toggle {darkMode ? "Light" : "Dark"} Mode
    //       </button>
    //     </span>

    //     {loadingCompanies ? (
    //       <p className="text-center text-gray-500 dark:text-gray-300">Loading company options...</p>
    //     ) : (
    //       <div className="grid grid-cols-6 gap-4 items-end mb-6">
    //         <div className="col-span-2">
    //           {!runningScript ? (
    //             <button
    //               onClick={btnClicked}
    //               disabled={runningScript}
    //               className="w-full h-10 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition"
    //             >
    //               Set Metadata & Run Script
    //             </button>
    //           ) : (
    //             <div className="w-full h-10 flex justify-center items-center bg-gray-200 rounded-lg">
    //               <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600"></div>
    //               <span className="ml-2 text-indigo-700 font-medium">Running script...</span>
    //             </div>
    //           )}
    //         </div>

    //         <div className="col-span-4">
    //           <label htmlFor="company" className="block mb-1 text-sm font-medium text-gray-700 dark:text-gray-300">
    //             Select a Company:
    //           </label>
    //           <Select
    //             id="company"
    //             options={companySelectOptions}
    //             value={companySelectOptions.find((opt) => opt.value === selectedCompany)}
    //             onChange={(selectedOption) => {
    //               if (selectedOption) setSelectedCompany(selectedOption.value);
    //             }}
    //             isSearchable
    //             placeholder="Search or select company..."
    //             isRtl={true}
    //             className="text-gray-900"
    //           />
    //         </div>
    //       </div>
    //     )}

    //     {showModal && (
    //       <div className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50">
    //         <div className="bg-white dark:bg-gray-700 rounded-xl p-8 w-96 max-w-full shadow-lg flex flex-col gap-4">
    //           <h2 className="text-xl font-semibold text-center text-gray-900 dark:text-white">Set Metadata</h2>
    //           <input
    //             type="text"
    //             placeholder="Company Name"
    //             value={metadata.companyName}
    //             onChange={(e) => setMetadata({ ...metadata, companyName: e.target.value })}
    //             className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
    //           />
    //           <input
    //             type="number"
    //             placeholder="Row Meta"
    //             value={metadata.rowMeta}
    //             onChange={(e) => setMetadata({ ...metadata, rowMeta: Number(e.target.value) })}
    //             className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
    //           />
    //           <input
    //             type="text"
    //             placeholder="Base URL"
    //             value={metadata.baseUrl}
    //             onChange={(e) => setMetadata({ ...metadata, baseUrl: e.target.value })}
    //             className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
    //           />
    //           <input
    //             type="text"
    //             placeholder="Page Numbers (e.g. 1,2,3)"
    //             value={metadata.pageNumbers.join(",")}
    //             onChange={(e) =>
    //               setMetadata({
    //                 ...metadata,
    //                 pageNumbers: e.target.value
    //                   .split(",")
    //                   .map((n) => parseInt(n.trim()))
    //                   .filter((n) => !isNaN(n)),
    //               })
    //             }
    //             className="px-3 py-2 rounded-lg border border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 dark:bg-gray-600 dark:border-gray-500 dark:text-white"
    //           />
    //           <button
    //             onClick={handleSubmitMetadata}
    //             disabled={runningScript}
    //             className="bg-indigo-600 hover:bg-indigo-700 disabled:bg-indigo-400 text-white rounded-lg py-3 font-semibold transition disabled:cursor-not-allowed"
    //           >
    //             {runningScript ? "Running..." : "Run Script"}
    //           </button>
    //           <button
    //             onClick={() => setShowModal(false)}
    //             className="bg-transparent border border-gray-400 hover:bg-gray-100 dark:border-gray-600 dark:hover:bg-gray-600 rounded-lg py-3 font-semibold transition"
    //           >
    //             Cancel
    //           </button>
    //         </div>
    //       </div>
    //     )}

    //     {!showModal && (
    //       <>
    //         {loadingData ? (
    //           <p className="text-center text-gray-500 dark:text-gray-300">Loading company data...</p>
    //         ) : data.length > 0 ? (
    //           <ChartComponent data={data} />
    //         ) : (
    //           <p className="text-center text-gray-500 dark:text-gray-300">No data available</p>
    //         )}
    //       </>
    //     )}

        
    //   </div>
    // </div>

    
  <div className="min-h-screen p-6 bg-gray-100 dark:bg-gray-900 dark:text-white transition-colors duration-300">
    <div className="max-w-4xl mx-auto bg-white dark:bg-gray-800 rounded-xl shadow-lg p-8">
      <h1 className="text-2xl font-semibold text-gray-900 dark:text-white mb-6 text-center">
        📊 Company Financial Overview
      </h1>

      {/* Removed old toggle button here */}

      {loadingCompanies ? (
        <p className="text-center text-gray-500 dark:text-gray-300">Loading company options...</p>
      ) : (
        <div className="grid grid-cols-6 gap-4 items-end mb-6">
          <div className="col-span-2">
            {!runningScript ? (
              <button
                onClick={btnClicked}
                disabled={runningScript}
                className="w-full h-10 bg-indigo-600 hover:bg-indigo-700 text-white rounded-lg font-medium disabled:opacity-50 disabled:cursor-not-allowed transition"
              >
                Set Metadata & Run Script
              </button>
            ) : (
              <div className="w-full h-10 flex justify-center items-center bg-gray-200 rounded-lg">
                <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-indigo-600"></div>
                <span className="ml-2 text-indigo-700 font-medium">Running script...</span>
              </div>
            )}
          </div>

          <div className="col-span-4">
            <label
              htmlFor="company"
              className="block mb-1 text-sm font-medium text-gray-700 dark:text-gray-300"
            >
              Select a Company:
            </label>
            <Select
              id="company"
              options={companySelectOptions}
              value={companySelectOptions.find((opt) => opt.value === selectedCompany)}
              onChange={(selectedOption) => {
                if (selectedOption) setSelectedCompany(selectedOption.value);
              }}
              isSearchable
              placeholder="Search or select company..."
              isRtl={true}
              className="text-gray-900"
            />
          </div>
        </div>
      )}

      {showModal && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex justify-center items-center z-50">
          <div className="bg-white dark:bg-gray-700 rounded-xl p-8 w-96 max-w-full shadow-lg flex flex-col gap-4">
            {/* Modal content unchanged */}
            ...
          </div>
        </div>
      )}

      {!showModal && (
        <>
          {loadingData ? (
            <p className="text-center text-gray-500 dark:text-gray-300">Loading company data...</p>
          ) : data.length > 0 ? (
            <ChartComponent data={data} />
          ) : (
            <p className="text-center text-gray-500 dark:text-gray-300">No data available</p>
          )}
        </>
      )}

    </div>

    {/* Dark mode toggle icon fixed top-right */}
    <button
      onClick={() => setDarkMode(!darkMode)}
      aria-label="Toggle Dark Mode"
      className="fixed top-4 right-4 p-2 rounded-full bg-gray-200 dark:bg-gray-700 text-gray-800 dark:text-yellow-300 shadow-lg hover:scale-110 transition-transform"
    >
      {darkMode ? <FaSun size={20} /> : <FaMoon size={20} />}
    </button>
  </div>
);

}

export default App;
