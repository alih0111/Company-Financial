const API_BASE = "http://localhost:5000/api";

export const fetchCompanyNames = async (): Promise<string[]> => {
  const res = await fetch(`${API_BASE}/CompanyNames`);
  if (!res.ok) throw new Error("Failed to fetch company names");
  return res.json();
};

export const fetchSalesData = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/SalesData?companyName=${encodeURIComponent(companyName)}`
  );
  if (!res.ok) throw new Error("Failed to fetch sales data");
  return res.json();
};

export const fetchSalesData2 = async (companyName: string) => {
  const res = await fetch(
    `${API_BASE}/SalesData2?companyName=${encodeURIComponent(companyName)}`
  );
  if (!res.ok) throw new Error("Failed to fetch sales data 2");
  return res.json();
};

export const fetchUrlForScript = async (
  companyName: string,
  script: "script1" | "script2"
) => {
  const url =
    script === "script1" ? `${API_BASE}/GetUrl` : `${API_BASE}/GetUrl2`;
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ companyName }),
  });
  if (!res.ok) throw new Error("Failed to fetch URL for script");
  return res.json();
};

export const runScript = async (
  script: "script1" | "script2",
  metadata: any
) => {
  const url =
    script === "script1"
      ? "http://localhost:5000/run-script"
      : "http://localhost:5000/run-script2";
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(metadata),
  });
  if (!res.ok) throw new Error("Failed to run script");
  return res.json();
};
