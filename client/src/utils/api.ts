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

export const addViewedItem = async (item: string) => {
  const res = await fetch(`${API_BASE}/users/get-items`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ item }),
  });

  if (!res.ok) {
    const error = await res.json().catch(() => null);
    throw new Error(error?.error || "Failed to add viewed item");
  }

  return res.json();
};


export interface AIStockMetric {
  company_id: string;
  symbol: string;
  company_name: string;

  quant_score: number;
  data_quality_score: number;
  has_enough_data: boolean;

  latest_sales_report_date: string;
  latest_profit_report_date: string;
  latest_market_date: string;

  sales_growth_12m: number;
  sales_growth_3m: number;
  sales_stability: number;

  operating_profit_growth_yoy: number;
  operating_profit_growth_4_reports: number;
  net_profit_growth_4_reports: number;

  operating_margin_latest: number;
  net_margin_latest: number;
  revenue_growth_yoy: number;
  interest_coverage: number;
  non_operating_pct: number;

  net_profit_margin_12m: number;
  operating_margin_12m: number;
  operating_margin_trend: number;
  ps_ratio: number;

  latest_eps: number;
  latest_operating_eps: number;
  latest_price: number;
  pe_approx: number;

  price_return_7d: number;
  price_return_30d: number;
  price_return_90d: number;

  avg_trade_value_30d: number;
  avg_volume_30d: number;
  volatility_30d: number;
  price_position_90d: number;

  bad_pe_flag: boolean;
  weak_sales_flag: boolean;
  weak_operating_profit_flag: boolean;
  weak_liquidity_flag: boolean;
  loss_maker_flag: boolean;
  weak_coverage_flag: boolean;
  margin_contraction_flag: boolean;

  growth_score: number;
  profitability_score: number;
  valuation_score: number;
  market_score: number;

  // ستون‌های شفافیت v3
  growth_penalty: number;
  profitability_penalty: number;
  valuation_penalty: number;
  market_penalty: number;
  profit_report_age_months: number;
  market_data_age_days: number;
  stale_data_flag: boolean;
  ttm_net_profit: number;
  ttm_eps: number;
  score_version: string;

  // رتبه‌ی درصدی هر فاکتور بین کل بازار (۰ تا ۱)
  sales_growth_rank: number;
  sales_growth_3m_rank: number;
  revenue_growth_rank: number;
  operating_profit_growth_rank: number;
  net_profit_growth_rank: number;
  operating_margin_rank: number;
  net_margin_rank: number;
  margin_trend_rank: number;
  interest_coverage_rank: number;
  earnings_quality_rank: number;
  pe_rank: number;
  ps_rank: number;
  liquidity_rank: number;
  stability_rank: number;
  low_volatility_rank: number;
  momentum_rank: number;

  // فاکتورهای v3.2 (ترازنامه و جریان نقدی)
  roe: number;
  financial_leverage: number;
  current_ratio: number;
  cash_conversion: number;
  pb_ratio: number;
  roe_rank: number;
  leverage_rank: number;
  current_ratio_rank: number;
  cash_conversion_rank: number;
  pb_rank: number;
}

export async function getAIStockSummary(limit = 20): Promise<AIStockMetric[]> {
  const res = await fetch(`${API_BASE}/summary?limit=${limit}`, {
    headers: getAuthHeaders(),
  });

  if (!res.ok) {
    throw new Error(`Failed to fetch AI stock summary: ${res.status}`);
  }

  return res.json();
}

// ----------------------------- Portfolio -----------------------------

export interface PortfolioHoldingEnriched {
  company_id: string;
  symbol?: string;
  company_name: string;
  quantity: number;
  buy_price: number;
  buy_date?: string;
  note?: string;

  latest_price: number;
  has_live_price: boolean;
  market_value: number;
  cost_basis: number;
  gain: number;
  gain_pct: number;
  weight: number;
}

export interface PortfolioSummary {
  total_cost: number;
  total_cost_raw: number;
  total_market_value: number;
  total_gain: number;
  total_gain_pct: number;
  holdings_count: number;
  holdings: PortfolioHoldingEnriched[];
}

export async function getPortfolio(): Promise<PortfolioSummary> {
  const res = await fetch(`${API_BASE}/portfolio`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || "Failed to fetch portfolio");
  }
  return res.json();
}

export interface UpsertHoldingPayload {
  company_id: string;
  symbol?: string;
  company_name: string;
  quantity: number;
  buy_price: number;
  buy_date?: string;
  note?: string;
}

export async function upsertHolding(
  payload: UpsertHoldingPayload
): Promise<any> {
  const res = await fetch(`${API_BASE}/portfolio`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || "Failed to save holding");
  }
  return res.json();
}

export async function deleteHolding(companyID: string): Promise<any> {
  const res = await fetch(
    `${API_BASE}/portfolio/${encodeURIComponent(companyID)}`,
    {
      method: "DELETE",
      headers: getAuthHeaders(),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || "Failed to delete holding");
  }
  return res.json();
}

// ----------------------------- Price History -----------------------------

export interface PriceHistoryRow {
  date: string;
  jalali_date: string;
  closing_price: number;
  last_price: number;
  high_price: number;
  low_price: number;
  volume: number;
  trade_value: number;
  change_percent: number;
}

export async function getPriceHistory(
  companyName: string,
  limit = 365
): Promise<PriceHistoryRow[]> {
  const res = await fetch(
    `${API_BASE}/price-history?companyName=${encodeURIComponent(
      companyName
    )}&limit=${limit}`,
    {
      headers: getAuthHeaders(),
    }
  );
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || "Failed to fetch price history");
  }
  return res.json();
}

export async function analyzeTopStocks(limit = 20): Promise<any> {
  const res = await fetch(`${API_BASE}/analyze`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      limit,
      min_avg_trade_value_30d: 0,
    }),
  });

  if (!res.ok) {
    const text = await res.text();
    throw new Error(`AI analyze failed: ${res.status} ${text}`);
  }

  return res.json();
}

// ----------------------------- BRS Price Collector -----------------------------

export type BrsCollectMode = "daily" | "backfill";

export async function collectBrsPrices(
  mode: BrsCollectMode = "daily",
  options?: {
    limit?: number;
    symbol?: string;
    force?: boolean;
    raw?: boolean;
    threshold?: number;
  }
): Promise<any> {
  const res = await fetch(`${API_BASE}/brs/collect`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      mode,
      limit: options?.limit,
      symbol: options?.symbol,
      force: options?.force,
      raw: options?.raw,
      threshold: options?.threshold,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `BRS collect failed: ${res.status}`);
  }

  return res.json();
}