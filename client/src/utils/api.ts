const API_BASE = "http://rfa_back.systemgroup.net/api";

const getAuthHeaders = () => {
  const token = localStorage.getItem("token");
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
};

export const fetchCompanyNames = async (): Promise<string[]> => {
  const res = await fetch(`${API_BASE}/CompanyNames`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch company names");
  return res.json();
};

export const fetchSalesData = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/SalesData?companyName=${encodeURIComponent(companyName)}`,
    {
      headers: getAuthHeaders(),
    }
  );

  if (!res.ok) throw new Error("Failed to fetch sales data");
  return res.json();
};

export const fetchSalesData2 = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/SalesData2?companyName=${encodeURIComponent(companyName)}`,
    {
      headers: getAuthHeaders(),
    }
  );

  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

export const fetchSalesDataScore = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/CompanyScores?companyName=${encodeURIComponent(companyName)}`,
    {
      headers: getAuthHeaders(),
    }
  );

  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

export const fetchSalesDataAllScore = async () => {
  const res = await fetch(`${API_BASE}/AllCompanyScores`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

export const fetchStockPriceScore = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/StockPriceScore?companyName=${encodeURIComponent(
      companyName
    )}`,
    {
      headers: getAuthHeaders(),
    }
  );

  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

export const fetchFullPE = async () => {
  const res = await fetch(`${API_BASE}/FetchFullPE`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

// export const fetchStockPrice = async (companyName: string) => {
//   const res = await fetch(
//     `${API_BASE}/StockPrice?companyName=${encodeURIComponent(companyName)}`
//   );
//   if (!res.ok) throw new Error("Failed to fetch sales data 2");
//   return res.json();
// };

export const fetchUrlForScript = async (
  companyName: string,
  script: "script1" | "script2" | "stockPrices"
) => {
  const url =
    script === "script1"
      ? `${API_BASE}/GetUrl`
      : script === "script2"
      ? `${API_BASE}/GetUrl2`
      : `${API_BASE}/GetUrl2`;
  const res = await fetch(url, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ companyName }),
  });
  if (!res.ok) throw new Error("Failed to fetch URL for script");
  return res.json();
};

export const runScript = async (
  script: "script1" | "script2" | "stockPrices" | "full",
  metadata: any
) => {
  const url =
    // script === "script1"
    //   ? "http://localhost:5000/run-script"
    //   : "http://localhost:5000/run-script2";
    script === "script1"
      ? `${API_BASE}/run-script`
      : script === "script2"
      ? `${API_BASE}/run-script2`
      : script === "stockPrices"
      ? `${API_BASE}/run_script_price`
      : "";
  const res = await fetch(url, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(metadata),
  });
  if (!res.ok) throw new Error("Failed to run script");
  return res.json();
};

export const runBulkScript = async (
  script: "script1" | "script2",
  companies: string[],
  rowMeta: number = 20,
  pageNumbers: number[] = [1, 2, 3, 4]
) => {
  const res = await fetch(`${API_BASE}/fetchAllData`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ script, companies, rowMeta, pageNumbers }),
  });

  if (!res.ok) {
    const error = await res.json();
    throw new Error(error?.error || "Failed to run bulk script");
  }

  return res.json();
};
