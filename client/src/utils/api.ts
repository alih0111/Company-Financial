import { API_BASE } from "../config";

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

// جمع‌آوری قدیمی (run-script/GetUrl وابسته به SQL Server بازنشسته شده)؛
// جایگزین canonical: syncCodal و collectBrsPrices.

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

/**
 * Score freshness (public endpoint, no auth). `score_as_of` is the data visibility
 * date of the served run; `score_computed_at` is when that run finished; `score_stale`
 * is true when inputs have arrived since the run was computed. Without this the table
 * shows a frozen score with no indication that it is frozen.
 */
export interface ShadowHealth {
  score_version?: string;
  score_run_id?: string;
  score_run_seq?: number;
  score_as_of?: string;
  score_computed_at?: string;
  data_as_of?: string;
  score_stale?: boolean;
  score_stale_reasons?: string[] | null;
  analytics_status?: string;
}

export async function getShadowHealth(): Promise<ShadowHealth> {
  const res = await fetch(`${API_BASE}/health/shadow`);
  if (!res.ok) {
    throw new Error(`Failed to fetch score freshness: ${res.status}`);
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

export type BrsCollectMode = "daily" | "backfill" | "sync";

export async function collectBrsPrices(
  mode: BrsCollectMode = "daily",
  options?: {
    limit?: number;
    symbol?: string;
    force?: boolean;
    raw?: boolean;
    threshold?: number;
    api?: boolean;
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
      api: options?.api,
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `BRS collect failed: ${res.status}`);
  }

  return res.json();
}

// ----------------------------- Family Assets -----------------------------

export interface FamilyHolding {
  asset_id: number;
  asset_name: string;
  quantity: number;
  cost_basis: number;
  value: number;
  profit: number;
  profit_pct: number;
  weight: number;
}

export interface FamilyPerson {
  person_id: number;
  name: string;
  sort_order: number;
  cash_balance: number;
  holdings: FamilyHolding[];
  holdings_value: number;
  total_value: number;
  total_cost: number;
  profit: number;
  profit_pct: number;
  share_of_total: number;
}

export interface FamilyAsset {
  asset_id: number;
  name: string;
  symbol: string;
  category: string;
  commission_rate: number;
  sort_order: number;
  latest_price: number;
  price_date: string;
  total_quantity: number;
  total_cost: number;
  total_value: number;
  total_profit: number;
  profit_pct: number;
  weight: number;
}

export interface FamilySummary {
  latest_datekey: string;
  holdings_value: number;
  total_cash: number;
  grand_total: number;
  total_cost: number;
  total_profit: number;
  total_profit_pct: number;
  best_tomorrow: number;
  worst_tomorrow: number;
  stocks_total: number;
  gold_total: number;
  dollar_total: number;
}

export interface FamilyState {
  today_datekey: string;
  assets: FamilyAsset[];
  people: FamilyPerson[];
  summary: FamilySummary;
}

export interface FamilyHistoryRow {
  date_key: string;
  total: number;
  has_total: boolean;
  people: Record<string, number>;
}

export interface FamilyCashFlow {
  id: number;
  date_key: string;
  amount: number;
  direction: string;
  note: string;
}

async function familyFetch<T>(
  path: string,
  init?: RequestInit
): Promise<T> {
  const res = await fetch(`${API_BASE}/family${path}`, {
    ...init,
    headers: getAuthHeaders(),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `Family API failed: ${res.status}`);
  }
  return res.json();
}

export const getFamilyAssets = () => familyFetch<FamilyState>("/assets");

export const saveFamilyPrices = (dateKey: string, prices: { asset_id: number; price: number }[]) =>
  familyFetch<{ message: string; date_key: string; total_value: number }>("/prices", {
    method: "POST",
    body: JSON.stringify({ date_key: dateKey, prices }),
  });

export interface FamilySyncResult {
  updated: {
    asset_id: number;
    name: string;
    symbol: string;
    date_key: string;
    price: number;
  }[];
  missing: string[];
}

export const syncFamilyPrices = (backfill = false) =>
  familyFetch<FamilySyncResult>("/sync-prices", {
    method: "POST",
    body: JSON.stringify({ backfill }),
  });

export const upsertFamilyHolding = (payload: {
  person_id: number;
  asset_id: number;
  quantity: number;
  cost_basis: number;
}) =>
  familyFetch<{ message: string }>("/holdings", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const deleteFamilyHolding = (personId: number, assetId: number) =>
  familyFetch<{ message: string }>(
    `/holdings?person_id=${personId}&asset_id=${assetId}`,
    { method: "DELETE" }
  );

export const createFamilyPerson = (name: string) =>
  familyFetch<{ message: string; person_id: number }>("/people", {
    method: "POST",
    body: JSON.stringify({ name }),
  });

export const createFamilyAsset = (
  name: string,
  category: string
) =>
  familyFetch<{ message: string; asset_id: number }>("/assets", {
    method: "POST",
    body: JSON.stringify({ name, category }),
  });

export const updateFamilyAccount = (personId: number, cashBalance: number) =>
  familyFetch<{ message: string }>("/account", {
    method: "PUT",
    body: JSON.stringify({ person_id: personId, cash_balance: cashBalance }),
  });

export const getFamilyCashFlows = (limit = 200) =>
  familyFetch<FamilyCashFlow[]>(`/cashflows?limit=${limit}`);

export const addFamilyCashFlow = (payload: {
  date_key: string;
  amount: number;
  direction: string;
  note: string;
}) =>
  familyFetch<{ message: string; id: number }>("/cashflows", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const deleteFamilyCashFlow = (id: number) =>
  familyFetch<{ message: string }>(`/cashflows/${id}`, {
    method: "DELETE",
  });

export const getFamilyHistory = () =>
  familyFetch<FamilyHistoryRow[]>("/history");

// ----------------------------- کارگزاری آگاه -----------------------------

export interface FamilyBrokerAccount {
  person_id: number;
  person_name: string;
  broker: string;
  username: string;
  has_secret: boolean;
  is_active: boolean;
  last_synced_at: string | null;
  last_status: string;
  last_error: string;
}

export interface FamilyBrokerHolding {
  symbol: string;
  name: string;
  quantity: number;
  avg_buy_price: number;
  last_price: number;
}

export interface FamilyBrokerJob {
  job_id: string;
  person_id: number;
  state: "running" | "done" | "error";
  message: string;
  started_at: string;
  updated_at: string;
  needs_captcha?: boolean;
  captcha_image?: string;
  result?: {
    ok: boolean;
    holdings: FamilyBrokerHolding[];
    cash: { available: number | null };
    source?: string;
    needs_discovery?: boolean;
    login?: { mode?: string; attempts?: number; error?: string | null };
    captured?: { responses: number; dump_dir: string };
  };
}

export const getFamilyBrokerAccounts = () =>
  familyFetch<FamilyBrokerAccount[]>("/broker");

export const saveFamilyBrokerAccount = (payload: {
  person_id: number;
  username: string;
  password?: string;
  is_active?: boolean;
}) =>
  familyFetch<{ message: string }>("/broker", {
    method: "PUT",
    body: JSON.stringify(payload),
  });

export const deleteFamilyBrokerAccount = (personId: number) =>
  familyFetch<{ message: string }>(`/broker?person_id=${personId}`, {
    method: "DELETE",
  });

export const startFamilyBrokerSync = (payload: { person_id?: number; all?: boolean }) =>
  familyFetch<{ jobs: FamilyBrokerJob[] }>("/sync-broker", {
    method: "POST",
    body: JSON.stringify(payload),
  });

export const getFamilyBrokerJob = (jobId: string) =>
  familyFetch<FamilyBrokerJob>(`/sync-broker/status?job_id=${encodeURIComponent(jobId)}`);

export const submitFamilyBrokerCaptcha = (jobId: string, code: string) =>
  familyFetch<{ message: string }>("/sync-broker/captcha", {
    method: "POST",
    body: JSON.stringify({ job_id: jobId, code }),
  });

// ----------------------------- Quick Codal Sync -----------------------------
// جمع‌آوری سریع: فقط گزارش‌های جدید کدال برای نمادهای tracked.

export type SyncCodalMode = "all" | "financial" | "monthly";

export interface SyncCodalFeedSummary {
  letter_type: number;
  pages: number;
  scanned: number;
  skipped_unknown_ticker: number;
  skipped_unsupported_type: number;
  skipped_missing_metadata: number;
  already: number;
  new: number;
  fetched: number;
  processed: number;
  completed: number;
  failed: number;
  unsupported: number;
  errors: { report_id: string; error: string | null }[];
}

export interface SyncCodalTotal {
  scanned: number;
  skipped_unknown_ticker: number;
  skipped_unsupported_type: number;
  skipped_missing_metadata: number;
  already: number;
  new: number;
  fetched: number;
  completed: number;
  failed: number;
  unsupported: number;
  // مسیر canonical (sync-codal): گزارش‌های نماد خارج از universe
  quarantined?: number;
}

export interface SyncCodalSummary {
  success: boolean;
  dry_run: boolean;
  financial?: SyncCodalFeedSummary;
  monthly?: SyncCodalFeedSummary;
  total: SyncCodalTotal;
  error?: string;
  output?: string;
}

export interface SyncCodalPayload {
  mode?: SyncCodalMode;
  dry_run?: boolean;
  max_pages?: number;
  limit?: number;
  // جمع‌آوری فقط برای یک نماد (خالی = sync سراسری feed کدال)
  symbol?: string;
}

export async function syncCodal(
  payload: SyncCodalPayload = {}
): Promise<SyncCodalSummary> {
  const res = await fetch(`${API_BASE}/sync-codal`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      mode: payload.mode ?? "all",
      dry_run: payload.dry_run ?? false,
      ...(payload.max_pages ? { max_pages: payload.max_pages } : {}),
      ...(payload.limit ? { limit: payload.limit } : {}),
      ...(payload.symbol ? { symbol: payload.symbol } : {}),
    }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(
      err?.error || err?.output || `Quick sync failed: ${res.status}`
    );
  }

  return res.json();
}
// ----------------------------- Investment Chat -----------------------------

export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

export interface ChatResponse {
  reply: string;
  intent?: string;
}

export async function sendChatMessage(
  messages: ChatMessage[]
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ messages }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `Chat failed: ${res.status}`);
  }

  return res.json();
}

export interface ChatProgressEvent {
  kind: "open" | "round" | "tool_start" | "tool_done" | "tool_error" | "notice";
  tool?: string;
  round?: number;
  message?: string;
}

// sendChatMessageStream همان /chat است ولی روی /chat/stream با رویدادهای SSE؛
// هر ابزار که دستیار صدا می‌زند از طریق onEvent لحظه‌ای گزارش می‌شود.
// اگر استریم شکست بخورد، فراخوان می‌تواند به sendChatMessage برگردد.
export async function sendChatMessageStream(
  messages: ChatMessage[],
  onEvent: (e: ChatProgressEvent) => void,
  signal?: AbortSignal
): Promise<ChatResponse> {
  const res = await fetch(`${API_BASE}/chat/stream`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({ messages }),
    signal,
  });
  if (!res.ok || !res.body) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || `Chat stream failed: ${res.status}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let final: ChatResponse | null = null;

  const handleFrame = (frame: string) => {
    const evMatch = frame.match(/^event: (.+)$/m);
    const dataMatch = frame.match(/^data: (.+)$/m);
    const ev = evMatch ? evMatch[1].trim() : "";
    let data: Record<string, unknown> = {};
    try {
      data = JSON.parse(dataMatch ? dataMatch[1] : "{}");
    } catch {
      return;
    }
    if (ev === "progress") {
      onEvent({
        kind: (data.type as ChatProgressEvent["kind"]) || "round",
        tool: data.tool as string | undefined,
        round: data.round as number | undefined,
      });
    } else if (ev === "notice") {
      onEvent({ kind: "notice", message: data.message as string });
    } else if (ev === "final") {
      final = { reply: String(data.reply ?? ""), intent: data.intent as string | undefined };
    } else if (ev === "error") {
      throw new Error(String(data.error ?? "stream error"));
    }
  };

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const frame = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      if (frame.trim()) handleFrame(frame);
    }
  }

  if (!final) throw new Error("stream ended without a final answer");
  return final;
}

// ── دارایی‌های بازار: شاخص‌ها + صندوق‌های طلا/کالا ──
export interface MarketIndex {
  code: string;
  name: string;
  value: number;
  change: number;
  change_percent: number;
  min: number;
  max: number;
  trade_date: string;
  jalali_date: string;
  market_value_rial: number;
  trade_value_rial: number;
}

export interface MarketFund {
  symbol: string;
  name: string;
  kind: string;
  last_price: number;
  change_percent: number;
  trade_date: string;
  jalali_date: string;
  observations: number;
}

export interface MarketAssets {
  indices: MarketIndex[];
  funds: MarketFund[];
  source: string;
}

export async function getMarketAssets(): Promise<MarketAssets> {
  const res = await fetch(`${API_BASE}/market/assets`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok) throw new Error("Failed to fetch market assets");
  return res.json();
}

export async function collectMarketAssets(
  mode: "daily" | "backfill" | "ensure" = "daily",
  options?: { symbol?: string; limit?: number; all?: boolean }
): Promise<any> {
  const res = await fetch(`${API_BASE}/market/collect`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: JSON.stringify({
      mode,
      symbol: options?.symbol,
      limit: options?.limit,
      all: options?.all,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => null);
    throw new Error(err?.error || "Failed to run market collector");
  }
  return res.json();
}

// ── تحلیل QVT نسخه ۲ (آزمایشی) — فید فقط‌خواندنی روی آرتیفکت‌های واقعی ──
export interface QvtAxisView {
  present: boolean;
  points: number | null;
  covered_weight: number | null;
  max_weight: number;
  coverage_ratio: number | null;
  coverage_threshold_met: boolean | null;
  pilot_eligible: boolean;
  eligibility_known: boolean;
  essential_missing?: string[];
  aggregation_status?: string;
  scope_reason?: string;
  data_confidence_status?: string;
  risk_gate_status?: string;
  financial_warnings?: string[];
  trading_warnings?: string[];
  n_warnings: number;
}

export interface QvtCompanyRow {
  company_id: string;
  symbol: string;
  model_family: string;
  industry: string;
  q: QvtAxisView;
  v: QvtAxisView;
  t: QvtAxisView;
  all_three_eligible: boolean;
  any_axis_eligible: boolean;
  // اعتبارسنجی اقتصادی مستقل (۲-ک-۲) — فقط برای نامزدهای فهرست کوتاه پر می‌شود
  shortlisted?: boolean;
  validation_status?: "independently_checked" | "consistent_but_not_independent" | "insufficient_evidence" | "conflicting";
  validation_status_label?: string;
  validation_needs_review?: boolean;
  validation_reason_count?: number;
  validation_reason_preview?: string;
}

export interface QvtV2Summary {
  stage: string;
  pilot: boolean;
  disclaimer: string;
  boundaries: Record<string, string>;
  as_of: string;
  cutoff: string;
  axis_targets: { quality: number; valuation: number; timing: number };
  consistency: {
    checked: boolean;
    as_of_cutoff_match: boolean;
    identity_conflicts: number;
    companies: number;
  };
  counts: {
    n_total: number;
    n_q_eligible: number;
    n_v_eligible: number;
    n_t_eligible: number;
    n_q_and_v: number;
    n_q_and_t: number;
    n_v_and_t: number;
    n_all_three: number;
    validation?: {
      independently_checked?: number;
      consistent_but_not_independent?: number;
      insufficient_evidence?: number;
      conflicting?: number;
    };
  };
  companies: QvtCompanyRow[];
  sources: Record<
    "q" | "v" | "t",
    { file: string; modified_at: string; sha256?: string; size_bytes?: number }
  >;
  bundle_integrity?: QvtBundleIntegrity;
}

const qvtServerError = async (res: Response, fallback: string) => {
  const body = await res.json().catch(() => null);
  return new Error(body?.error || fallback);
};

export async function fetchQvtV2Summary(): Promise<QvtV2Summary> {
  const res = await fetch(`${API_BASE}/qvt-v2`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok)
    throw await qvtServerError(res, "خروجی پایلوت QVT در دسترس نیست");
  return res.json();
}

export async function fetchQvtV2Detail(companyId: string): Promise<any> {
  const res = await fetch(
    `${API_BASE}/qvt-v2?company_id=${encodeURIComponent(companyId)}`,
    { headers: getAuthHeaders() }
  );
  if (!res.ok) throw await qvtServerError(res, "جزئیات شرکت یافت نشد");
  return res.json();
}

// ── Data Confidence مستقل (گام ۲-ز-۱) — ارزیابی کیفی شواهد، بدون عدد اطمینان ──
export type QvtConfidenceStatus = "findings" | "no_findings" | "not_evaluable";

export interface QvtConfidenceDimension {
  key: string;
  title: string;
  sources: string;
  status: QvtConfidenceStatus;
  reasons: string[];
}

export interface QvtConfidence {
  overall: "findings" | "no_findings_recorded" | "not_evaluable";
  overall_label: string;
  overall_note: string;
  dimension_counts: { findings: number; no_findings: number; not_evaluable: number };
  dimensions: QvtConfidenceDimension[];
  serious_warnings: string[];
  serious_note: string;
}

// ── Risk Gate مستقل (گام ۲-ح-۱) — فقط‌خواندنی، با قواعد مسدودسازی صریح ──
export type QvtRiskGateStatus =
  | "blocked"
  | "review_required"
  | "insufficient_evidence"
  | "no_verified_blocker";

export interface QvtRiskFinding {
  kind: string;
  axis: string;
  area: "data" | "fundamental" | "market";
  category: string;
  severity: string;
  severity_label: string;
  reason: string;
  evidence: string[];
  gate_effect: "blocked" | "review_required" | "none";
  blocking_rule?: string;
}

export interface QvtRiskArea {
  key: QvtRiskFinding["area"];
  title: string;
  status: QvtRiskGateStatus;
  status_label: string;
  findings: QvtRiskFinding[];
  evidence_gaps: string[];
  checks: string[];
}

export interface QvtRiskGate {
  status: QvtRiskGateStatus;
  status_label: string;
  status_note: string;
  areas: QvtRiskArea[];
  blockers: QvtRiskFinding[];
  review_findings: QvtRiskFinding[];
  evidence_gaps: string[];
  warning_kinds: string[];
  note: string;
}

// ── کشف فرصت‌های QVT — همان snapshot، گروه‌بندی مقایسه‌پذیر و پارتو ──
export type QvtDiscoveryModeName = "balanced" | "quality" | "value" | "timing";

export interface QvtDiscoveryFactorIssue {
  factor: string;
  kind: string; // not_included | raw_not_valid
  reason?: string;
}

export interface QvtDiscoveryAxis {
  points: number | null;
  covered_weight: number | null;
  coverage_ratio: number | null;
  max_weight: number;
  scored_factors: string[];
  factor_issues: QvtDiscoveryFactorIssue[];
}

export interface QvtDiscoveryCompany {
  company_id: string;
  symbol: string;
  model_family: string;
  industry: string;
  q: QvtDiscoveryAxis;
  v: QvtDiscoveryAxis;
  t: QvtDiscoveryAxis;
  warnings: {
    n: number;
    financial?: string[];
    trading?: string[];
  };
  confidence: QvtConfidence;
  risk_gate: QvtRiskGate;
}

export interface QvtDiscoveryRow {
  company_id: string;
  display_order: number;
  comparability: "comparable" | "small_group" | "missing_scores";
  pareto_layer?: number;
  group_rank?: number;
  group_size: number;
  group_valid: boolean;
  group_label: string;
  reason: string;
}

export interface QvtDiscoveryModeResult {
  mode: QvtDiscoveryModeName;
  title: string;
  order_note: string;
  counts: {
    companies: number;
    ranked: number;
    not_ranked: number;
    groups_total: number;
    groups_valid: number;
  };
  rows: QvtDiscoveryRow[];
}

// ── فهرست کوتاه کاربردی (گام ۲-ط-۱) ──
export interface QvtPriceFreshness {
  requested: boolean;
  available: boolean; // منبع مستقل پاسخ داد
  row_found: boolean; // ردیف قیمت در پنجره PIT یافت شد
  note: string;
  source?: string;
  company_id?: string;
  security_id?: string;
  last_trade_date?: string;
  collected_at?: string;
  as_of_date?: string;
  age_days?: number | null;
  policy_days?: number | null;
  policy_basis?: string;
  window_rule?: string;
  violation?: boolean | null;
}

export interface QvtShortlistEntry {
  company_id: string;
  symbol: string;
  model_family: string;
  industry: string;
  q: QvtDiscoveryAxis;
  v: QvtDiscoveryAxis;
  t: QvtDiscoveryAxis;
  warnings: {
    n: number;
    financial?: string[];
    trading?: string[];
  };
  confidence: QvtConfidence;
  risk_gate: QvtRiskGate;
  pareto_layer: number | null;
  group_rank?: number;
  group_size: number;
  group_label: string;
  reason: string;
  price_freshness: QvtPriceFreshness | null;
  // وضعیت اعتبارسنجی اقتصادی مستقل (۲-ک-۲) — مستقل از امتیاز و Risk Gate؛
  // غیبت یعنی «ارزیابی نشده»، نه «تأییدشده»
  validation_status?: "independently_checked" | "consistent_but_not_independent" | "insufficient_evidence" | "conflicting";
  validation_status_label?: string;
  validation_needs_review?: boolean;
  validation_reason?: string;
}

export interface QvtShortlistGroup {
  group_label: string;
  industry: string;
  model_family: string;
  group_size: number;
  entries: QvtShortlistEntry[];
}

export interface QvtShortlist {
  title: string;
  basis: string;
  not_a_signal: string;
  counts: { groups: number; companies: number };
  groups: QvtShortlistGroup[];
  non_ranked: { n: number; note: string };
}

// ── فرصت‌های قابل بررسی بازار (گام ۲-ک-۷ + لایهٔ تصمیم ۲-ک-۸) ──────────────
// هیچ امتیاز ترکیبی یا رتبه بنیادی بین صنایع ندارد؛ «نامزد جذاب» یعنی علاوه
// بر گیت‌های شواهد، ترکیب بنیادی/ارزندگی/ورود با آستانه‌های اعلامی سیاست
// تصمیم پاس شد — نه توصیه خرید. صفر نامزد جذاب ممکن و صادقانه است.
export interface QvtBoardAxisStatus {
  points: number | null;
  max: number;
  covered_weight: number | null;
  coverage_ratio: number | null;
  n_scored_factors: number;
  n_factor_issues: number;
  status: "computed" | "missing";
}

export interface QvtBoardEntry {
  company_id: string;
  symbol: string;
  industry: string;
  model_family: string;
  group:
    | "attractive_candidates"
    | "fundamentals_waiting"
    | "apparent_value_risk"
    | "blocked_or_insufficient";
  conclusion: string;
  group_reason: string;
  top_reason: string;
  top_risk: string;
  why: string[];
  careful: string[];
  review_when: string[];
  q: QvtBoardAxisStatus;
  v: QvtBoardAxisStatus;
  t: QvtBoardAxisStatus;
  // لایهٔ تصمیم ۲-ک-۸
  fundamental: "strong" | "acceptable" | "weak" | "insufficient";
  fundamental_label: string;
  fundamental_note: string[];
  roe_pct: number | null;
  margin_pct: number | null;
  leverage_pct: number | null;
  interest_coverage_pct: number | null;
  cash_conversion_pct?: number | null;
  value_mean: number | null;
  value_label: string;
  value_cheap: boolean;
  value_defensible: boolean;
  value_note: string[];
  value_basis_note?: string;
  entry: "ok" | "neutral" | "hostile" | "insufficient";
  entry_label: string;
  entry_note: string[];
  // گام ۲-ک-۹ — قید کیفیت اقتصادی (تبدیل نقد ضعیف / سود عملیاتی منفی)
  conditional?: boolean;
  conditional_reasons?: string[];
  negative_operating_profit?: boolean;
  pareto_layer?: number;
  group_size: number;
  group_label: string;
  risk_gate_status: QvtRiskGateStatus;
  risk_gate_label: string;
  confidence_overall: string;
  confidence_label: string;
  price_freshness: QvtPriceFreshness | null;
  freshness_label: string;
  validation_status?: string;
  validation_status_label?: string;
  display_rank: number;
}

export interface QvtDecisionPolicy {
  version: string;
  q_strong_roe: number;
  q_weak_roe: number;
  q_strong_margin: number;
  q_safety_min: number;
  q_weak_factor: number;
  q_weak_factor_n: number;
  q_cash_min?: number;
  v_cheap: number;
  v_expensive: number;
  v_multiple_min: number;
  v_min_sector_support?: number;
  t_momentum_ok: number;
  t_momentum_hostile: number;
  t_rs_hostile: number;
  t_liq_floor_rial: number;
  note: string;
}

export interface QvtOpportunityBoard {
  title: string;
  subtitle: string;
  not_a_signal: string;
  as_of: string;
  default_visible: number;
  empty_note: string;
  systemic_caveats?: string[];
  counts: {
    // قرارداد صریح گام ۲-ک-۱۰: گروه‌های تصمیم mutually exclusive و مجموع‌بخش.
    groups: {
      attractive_candidates: number;
      fundamentals_waiting: number;
      apparent_value_risk: number;
      blocked_or_insufficient: number;
      total: number;
      universe: number;
      mutually_exclusive: boolean;
      reconciles: boolean;
    };
    // صفت‌های مستقل از گروه — هرگز به شمارش گروه‌ها افزوده نمی‌شوند.
    attributes: {
      conditional_total: number;
      conditional_in_waiting: number;
      conditional_blocking: number;
      negative_operating_profit: number;
      risk_review_required: number;
      price_freshness_verified: number;
    };
    n_triple_universe: number;
    not_in_attractive_reasons: Record<string, number>;
    blocked_breakdown: Record<string, number>;
    // سازگاری پس‌رو (نسخه‌های قدیمی backend) — اختیاری و فقط خواندنی
    attractive_candidates?: number;
    fundamentals_waiting?: number;
    apparent_value_risk?: number;
    blocked_or_insufficient?: number;
    conditional_candidates?: number;
    n_conditional_blocking?: number;
    n_price_freshness_verified?: number;
    n_risk_review_required?: number;
  };
  attractive_candidates: QvtBoardEntry[];
  fundamentals_waiting: QvtBoardEntry[];
  apparent_value_risk: QvtBoardEntry[];
  blocked_or_insufficient: QvtBoardEntry[];
  decision_policy: QvtDecisionPolicy;
  rules: Record<string, string>;
  engine_note: string;
}

// ── پرونده تصمیم‌یار سهم (گام ۲-ک-۳ P2) — sidecar نسخه‌دار decision_dossier ──
// فقط شواهد آرتیفکت‌های همین snapshot؛ هیچ امتیاز ترکیبی یا وزن پنهانی ندارد.
export interface QvtDossierFactorRow {
  factor: string;
  fa: string;
  direction?: "higher" | "lower";
  score?: number | null;
  contribution?: number | null;
  weight?: number | null;
  raw_value?: number | null;
  plain?: string | null;
  warnings?: string[];
}

export interface QvtDossierRatioRow extends QvtDossierFactorRow {
  name: "pe" | "pb" | "ps";
  essential?: boolean;
  included?: boolean;
  n_peers_sector?: number | null;
  n_peers_family?: number | null;
  peer_rank?: number | null;
  n_peers?: number | null;
  peer_values?: { symbol: string; company_id: string; value: number | null }[];
  reliability: "reliable" | "time_limited" | "missing";
  reliability_fa: string;
}

export interface QvtDecisionDossier {
  company_id: string;
  symbol: string;
  display_name?: string | null;
  industry?: string | null;
  model_family?: string | null;
  sections: {
    quality: {
      strengths: QvtDossierFactorRow[];
      weaknesses: QvtDossierFactorRow[];
      excluded_diagnostic: { factor: string; fa: string; reason: string }[];
      coverage: { covered_weight?: number | null; missing_weight?: number | null; coverage_ratio?: number | null };
      evidence_note: string;
    };
    value: {
      ratios: QvtDossierRatioRow[];
      caveats: string[];
      points?: number | null;
      covered_weight?: number | null;
      missing_weight?: number | null;
    };
    market: {
      factors: QvtDossierFactorRow[];
      points?: number | null;
      price: {
        price_rial?: number | null;
        trade_date?: string | null;
        shares?: number | null;
        market_cap_rial?: number | null;
        share_source?: string | null;
        note?: string;
      };
      adjustment_status: string;
    };
    evidence: {
      data_confidence: {
        status?: string | null;
        covered_weight?: number | null;
        pit_status_counts?: Record<string, number>;
        missing_reasons?: Record<string, string>;
      };
      risk_gate: { status?: string | null; financial_warnings: string[]; note?: string | null };
      independent_validation: {
        status: string;
        status_label: string;
        status_definition?: string | null;
        reasons: string[];
      };
      capital_events: {
        outcome: string;
        ex_date?: string | null;
        old_shares?: number | null;
        new_shares?: number | null;
        funding_tags?: string[] | null;
        codal_reference?: string | null;
        implied_vs_recorded_rel_diff?: number | null;
        caveat: string;
      }[];
      effective_dates: {
        as_of?: string | null;
        cutoff?: string | null;
        winner_period_end?: string | null;
        winner_publish_at?: string | null;
        winner_tracing_no?: string | null;
        price_trade_date?: string | null;
      };
    };
    summary: { why_review: string[]; main_risk: string[]; needed_evidence: string[] };
  };
}

export interface QvtPriceSourceMeta {
  source: string;
  window_rule: string;
  policy_basis: string;
  policy_source: string;
  security_selection: string;
  read_only: string;
  independent_of_warning_text: string;
  available: boolean;
  note?: string;
}

// ── زنجیره شواهد ورودی (گام ۲-ی-۱) — قرارداد چهار وضعیتی، فقط‌خواندنی ──
export interface QvtEvidenceField {
  k: string;
  v: string;
}

export interface QvtEvidenceItem {
  key: string;
  label: string;
  status: "verified_from_source" | "partially_verified" | "unverified" | "conflicting";
  status_label: string;
  checked: boolean; // false = کنترل ممکن نشد — جدا از «داده نبود»
  structural?: boolean; // یافته ساختاری درباره خود آرتیفکت — در جمع‌بندی محور نمی‌آید
  source?: string;
  summary?: string;
  fields?: QvtEvidenceField[];
  limitations?: string[];
  conflicts?: string[];
}

export interface QvtAxisEvidence {
  axis: string;
  axis_label: string;
  status: QvtEvidenceItem["status"];
  status_label: string;
  items: QvtEvidenceItem[];
}

export interface QvtEvidenceChain {
  company_id: string;
  overall: QvtEvidenceItem["status"];
  overall_label: string;
  status_counts: Record<string, number>;
  axes: QvtAxisEvidence[];
  notes: string[];
}

export interface QvtBundleIntegrity {
  artifact_files: Record<
    "q" | "v" | "t",
    { file: string; sha256: string; size_bytes: number; modified_at: string }
  >;
  chain_linkage: {
    q_to_v: Record<string, unknown>;
    q_to_t: Record<string, unknown>;
    v_to_t: Record<string, unknown>;
    status: QvtEvidenceItem["status"];
    status_label: string;
    note: string;
  };
  run_identity: { status: string; limitation: string; fix_plan: string };
  publication_atomicity: {
    writer: string;
    reader_mitigation: string;
    residual_risk: string;
  };
  load_verified_stable: boolean;
}

export interface QvtDiscoveryResponse {
  stage: string;
  pilot: boolean;
  disclaimer: string;
  boundaries: Record<string, string>;
  as_of: string;
  cutoff: string;
  universe: {
    n_all_artifacts: number;
    n_triple_eligible: number;
    note: string;
  };
  mode_rules: Record<string, string>;
  shortlist_rules: Record<string, unknown>;
  confidence_rules: Record<string, unknown>;
  risk_gate_rules: Record<string, unknown>;
  price_source: QvtPriceSourceMeta;
  snapshot_consistency: {
    files: Record<
      "q" | "v" | "t",
      { as_of?: string; cutoff?: string; sha256?: string }
    >;
    consistent: boolean;
    problems: string[];
    note: string;
  };
  companies: QvtDiscoveryCompany[];
  shortlist: QvtShortlist;
  opportunity_board?: QvtOpportunityBoard;
  modes: Record<QvtDiscoveryModeName, QvtDiscoveryModeResult>;
  sources: Record<
    "q" | "v" | "t",
    {
      file: string;
      modified_at: string;
      sha256?: string;
      as_of?: string;
      cutoff?: string;
    }
  >;
}

export async function fetchQvtV2Discovery(): Promise<QvtDiscoveryResponse> {
  const res = await fetch(`${API_BASE}/qvt-v2/discovery`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok)
    throw await qvtServerError(res, "کشف فرصت‌های QVT در دسترس نیست");
  return res.json();
}

// ── رتبه‌بندی سادهٔ اولویت بررسی (گام ۲-ک-۱۱) ───────────────────────────────
// یک شاخص آزمایشی ۰..۱۰۰ روی نمادهایی که هر سه محور Q/V/T آن‌ها دادهٔ کافی و
// معتبر دارند. فرمول رسمی Q/V/T و وزن‌های آن دست‌نخورده است؛ امتیاز هرگز بر
// پوشش تقسیم و وزن مفقود بازتوزیع نمی‌شود.
export type QvtRankStatus = "buy_review" | "wait" | "weak";

export interface QvtRankAxis {
  points: number | null;
  covered_weight: number | null;
  max: number;
  coverage_ratio: number | null;
  n_scored_factors: number;
  n_factor_issues: number;
}

export interface QvtRankedStock {
  company_id: string;
  symbol: string;
  industry: string;
  model_family: string;

  rank: number;
  score: number;
  score_ceiling: number;

  status: QvtRankStatus;
  status_label: string;
  status_reason: string;

  main_reason: string;
  main_risk: string;

  conditional: boolean;
  conditional_reasons: string[];
  negative_operating_profit: boolean;

  critical: boolean;
  critical_flags: string[];

  risk_gate_status: QvtRiskGateStatus;
  risk_gate_label: string;
  validation_status?: string;
  validation_status_label?: string;

  confidence_overall: string;
  confidence_label: string;

  coverage_min: number | null;
  score_confidence: string;
  score_confidence_label: string;

  practical_ceiling: number;
  full_coverage: boolean;
  comparability: string;
  comparability_label: string;

  peer_group_size: number;
  peer_group_valid: boolean;
  peer_group_label: string;

  extrapolated_score: number;
  sensitivity_rank: number;
  rank_shift: number;

  q: QvtRankAxis;
  v: QvtRankAxis;
  t: QvtRankAxis;

  board_group: string;
  board_group_label: string;
  group_reason: string;
  why: string[];
  careful: string[];
  review_when: string[];
}

export interface QvtUnscoredAxis {
  present: boolean;
  eligible: boolean;
  coverage_ratio: number | null;
  covered_weight: number | null;
  max: number;
  missing_essentials: string[];
}

export interface QvtUnscoredStock {
  company_id: string;
  symbol: string;
  industry: string;
  model_family: string;
  reason_code: string;
  reason_label: string;
  blocking_axes: string[];
  q: QvtUnscoredAxis;
  v: QvtUnscoredAxis;
  t: QvtUnscoredAxis;
}

export interface QvtRankingResponse {
  stage: string;
  pilot: boolean;
  disclaimer: string;
  boundaries: Record<string, unknown>;
  as_of: string;
  cutoff: string;
  title: string;
  subtitle: string;
  score_name: string;
  not_a_signal: string;
  score_ceiling: number;
  universe: {
    n_all_artifacts: number;
    n_scored: number;
    n_unscored: number;
    note: string;
  };
  score_contract: Record<string, string>;
  coverage_impact: {
    n_scored: number;
    n_full_coverage: number;
    n_partial_coverage: number;
    spearman_raw_vs_coverage_equalized: number;
    spearman_score_vs_q_coverage: number;
    max_rank_shift: number;
    n_shift_gt5: number;
    n_shift_gt10: number;
    practical_ceiling_min: number;
    practical_ceiling_max: number;
    interpretation: string;
  };
  peer_group_impact: {
    n_scored: number;
    n_valid_group: number;
    n_small_group: number;
    n_group_not_evaluated: number;
    min_group_size: number;
    top10_small_group: number;
    min_group_rule: number;
    interpretation: string;
  };
  data_completion_plan: {
    goal: string;
    why_q_only: string;
    structural_gap: string;
    differentiating_gaps: string;
    residual_causes: string;
    steps: string[];
    success_criterion: string;
    not_a_new_score: string;
  };
  sensitivity_note: string;
  status_legend: Record<string, string>;
  experimental_bundle?: {
    active: boolean;
    dir: string;
    note: string;
  };
  snapshot_consistency: {
    files: Record<
      "q" | "v" | "t",
      { as_of?: string; cutoff?: string; sha256?: string }
    >;
    consistent: boolean;
    problems: string[];
    note: string;
  };
  price_source: QvtPriceSourceMeta;
  ranked: QvtRankedStock[];
  unscored: QvtUnscoredStock[];
  sources: Record<
    "q" | "v" | "t",
    { as_of?: string; cutoff?: string; sha256?: string }
  >;
}

export async function fetchQvtV2Ranking(): Promise<QvtRankingResponse> {
  const res = await fetch(`${API_BASE}/qvt-v2/ranking`, {
    headers: getAuthHeaders(),
  });
  if (!res.ok)
    throw await qvtServerError(res, "رتبه‌بندی سهام در دسترس نیست");
  return res.json();
}
