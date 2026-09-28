// ماک توسعه‌ی API — فقط در حالت dev و با پارامتر ‎?__mock=1 فعال می‌شود.
// برای پیش‌نمایش UI بدون بک‌اند: http://localhost:3000/dashboard?__mock=1
type MockBody =
  | Record<string, unknown>
  | unknown[]
  | string
  | number
  | boolean
  | null
  | ((u: URL, init?: RequestInit) => MockBody);
type Route = {
  path: string;
  body: MockBody;
};

const companies = [
  "فولاد مبارکه",
  "فملی",
  "شپدیس",
  "وبملت",
  "شستا",
  "پارسان",
  "کگل",
  "خودرو",
];
const symbols = ["فولاد", "فملی", "شپدیس", "وبملت", "شستا", "پارسان", "کگل", "خودرو"];
const basePrice = [12450, 8320, 2150, 4120, 9840, 3260, 15600, 890];

const genHistory = (n: number, start: number) => {
  const rows: unknown[] = [];
  let p = start;
  let d = new Date();
  d = new Date(d.getTime() - n * 86400000);
  let j = new Date(d);
  for (let i = 0; i < n; i++) {
    const drift = Math.sin(i / 11) * 1.1 + Math.sin(i / 3.7) * 0.5;
    const noise = (((i * 2654435761) % 1000) / 1000 - 0.5) * 2.6;
    const chg = drift + noise;
    const open = p;
    p = Math.max(start * 0.45, p * (1 + chg / 100));
    const close = p;
    const last = close * (1 + ((((i * 40503) % 100) / 100 - 0.5) * 0.9) / 100);
    const hi = Math.max(open, close, last) * (1 + (((i * 7919) % 100) / 100) * 1.2 / 100);
    const lo = Math.min(open, close, last) * (1 - (((i * 104729) % 100) / 100) * 1.2 / 100);
    const jal = new Intl.DateTimeFormat("fa-IR-u-nu-latn", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).format(j);
    rows.push({
      date: d.toISOString().slice(0, 10),
      jalali_date: jal,
      closing_price: Math.round(close),
      last_price: Math.round(last),
      high_price: Math.round(hi),
      low_price: Math.round(lo),
      volume: Math.round(50e6 + ((i * 7919) % 400) * 1e6),
      trade_value: Math.round(close * 1e8),
      change_percent: Number(chg.toFixed(2)),
    });
    d = new Date(d.getTime() + 86400000);
    j = new Date(j.getTime() + 86400000);
    if (d.getUTCDay() === 5) {
      d = new Date(d.getTime() + 86400000);
      j = new Date(j.getTime() + 86400000);
    }
  }
  return rows.reverse(); // جدیدترین اول — کامپوننت reverse می‌کند
};

const mkMetric = (i: number) => {
  const r = (min: number, max: number, dec = 1) =>
    Number((min + ((i * 37 + 13) % 100) / 100 * (max - min)).toFixed(dec));
  const rank = () => Number((0.15 + ((i * 53 + 29) % 70) / 100).toFixed(2));
  return {
    company_id: String(i + 1), symbol: symbols[i], company_name: companies[i],
    quant_score: r(45, 88), data_quality_score: r(0.7, 0.95, 2), has_enough_data: true,
    latest_sales_report_date: "1405/05/01", latest_profit_report_date: "1405/04/30", latest_market_date: "1405/06/29",
    sales_growth_12m: r(-5, 45), sales_growth_3m: r(-8, 30), sales_stability: r(0.55, 0.92, 2),
    operating_profit_growth_yoy: r(-10, 55), operating_profit_growth_4_reports: r(-10, 50), net_profit_growth_4_reports: r(-15, 60),
    operating_margin_latest: r(5, 35), net_margin_latest: r(3, 28), revenue_growth_yoy: r(-5, 40),
    interest_coverage: r(1.2, 12, 1), non_operating_pct: r(2, 25),
    net_profit_margin_12m: r(3, 28), operating_margin_12m: r(5, 35), operating_margin_trend: r(-3, 4, 1), ps_ratio: r(0.6, 4, 2),
    latest_eps: r(500, 5000, 0), latest_operating_eps: r(700, 6000, 0), latest_price: basePrice[i], pe_approx: r(4, 14, 1),
    price_return_7d: r(-6, 9), price_return_30d: r(-12, 25), price_return_90d: r(-20, 40),
    avg_trade_value_30d: r(20, 400, 0) * 1e9, avg_volume_30d: r(5, 90, 0) * 1e6, volatility_30d: r(0.8, 4.2, 2), price_position_90d: r(0.2, 0.95, 2),
    bad_pe_flag: false, weak_sales_flag: i % 4 === 3, weak_operating_profit_flag: i % 5 === 4, weak_liquidity_flag: false,
    loss_maker_flag: false, weak_coverage_flag: i % 6 === 5, margin_contraction_flag: i % 3 === 2,
    growth_score: r(8, 34, 1), profitability_score: r(6, 25, 1), valuation_score: r(3, 15, 1), market_score: r(3, 10, 1),
    growth_penalty: i % 4 === 3 ? 6 : 0, profitability_penalty: i % 5 === 4 ? 4 : 0, valuation_penalty: 0, market_penalty: 0,
    profit_report_age_months: r(0, 2, 0), market_data_age_days: r(0, 3, 0), stale_data_flag: false,
    ttm_net_profit: r(2, 30, 0) * 1e12, ttm_eps: r(500, 5000, 0), score_version: "3.2",
    sales_growth_rank: rank(), sales_growth_3m_rank: rank(), revenue_growth_rank: rank(), operating_profit_growth_rank: rank(),
    net_profit_growth_rank: rank(), operating_margin_rank: rank(), net_margin_rank: rank(), margin_trend_rank: rank(),
    interest_coverage_rank: rank(), earnings_quality_rank: rank(), pe_rank: rank(), ps_rank: rank(),
    liquidity_rank: rank(), stability_rank: rank(), low_volatility_rank: rank(), momentum_rank: rank(),
    roe: r(8, 38), financial_leverage: r(0.6, 2.4, 2), current_ratio: r(0.9, 2.6, 2), cash_conversion: r(0.4, 1.6, 2),
    pb_ratio: r(0.7, 3.5, 2), roe_rank: rank(), leverage_rank: rank(), current_ratio_rank: rank(), cash_conversion_rank: rank(), pb_rank: rank(),
  };
};

const aiMetrics = companies.map((_, i) => mkMetric(i));

const allScores = companies.map((c, i) => ({
  company_id: String(i + 1),
  company_name: c,
  eps_growth: aiMetrics[i].net_profit_growth_4_reports,
  sales_growth: aiMetrics[i].sales_growth_12m,
  pe: aiMetrics[i].pe_approx,
  price: basePrice[i],
  Stable: i % 3 !== 1,
  operation: Number((0.3 + ((i * 41) % 60) / 100).toFixed(2)),
  epsGrowth: aiMetrics[i].net_profit_growth_4_reports,
  priceScore: 50 + ((i * 17) % 50),
}));

const salesChart = (seed: number) =>
  Array.from({ length: 8 }, (_, i) => ({
    companyName: "x",
    reportDate: `140${4 + (i % 2)}/0${1 + i}`,
    percentage: Number((Math.sin((i + seed) * 1.3) * 22 + (i - 3) * 3).toFixed(1)),
    wow: (i + seed) % 3 === 0 ? -1 : 1,
  }));

const portfolio = {
  total_cost: 4820000000,
  total_cost_raw: 4820000000,
  total_market_value: 5396400000,
  total_gain: 576400000,
  total_gain_pct: 11.96,
  holdings_count: 4,
  holdings: [
    { company_id: "1", symbol: "فولاد", company_name: "فولاد مبارکه", quantity: 120000, buy_price: 10200, buy_date: "1404/02/15", note: "", latest_price: 12450, has_live_price: true, market_value: 1494000000, cost_basis: 1224000000, gain: 270000000, gain_pct: 22.06, weight: 27.7 },
    { company_id: "2", symbol: "فملی", company_name: "ملی صنایع مس", quantity: 90000, buy_price: 7900, buy_date: "1404/03/10", note: "", latest_price: 8320, has_live_price: true, market_value: 748800000, cost_basis: 711000000, gain: 37800000, gain_pct: 5.32, weight: 13.9 },
    { company_id: "4", symbol: "وبملت", company_name: "بانک ملت", quantity: 500000, buy_price: 4400, buy_date: "1404/01/20", note: "", latest_price: 4120, has_live_price: true, market_value: 2060000000, cost_basis: 2200000000, gain: -140000000, gain_pct: -6.36, weight: 38.2 },
    { company_id: "5", symbol: "شستا", company_name: "سرمایه‌گذاری تأمین اجتماعی", quantity: 110000, buy_price: 9100, buy_date: "1404/04/02", note: "", latest_price: 9840, has_live_price: true, market_value: 1082400000, cost_basis: 1001000000, gain: 81400000, gain_pct: 8.13, weight: 20.1 },
  ],
};

const famAssets = [
  { asset_id: 1, name: "فولاد مبارکه", symbol: "فولاد", category: "stock", commission_rate: 0.0152, sort_order: 1, latest_price: 12450, price_date: "1405/06/29", total_quantity: 430000, total_cost: 4120000000, total_value: 5353500000, total_profit: 1233500000, profit_pct: 0.2994, weight: 0.4418 },
  { asset_id: 2, name: "طلا ۱۸ عیار", symbol: "", category: "gold", commission_rate: 0.009, sort_order: 2, latest_price: 8400000, price_date: "1405/06/29", total_quantity: 420, total_cost: 2900000000, total_value: 3528000000, total_profit: 628000000, profit_pct: 0.2166, weight: 0.291 },
  { asset_id: 3, name: "دلار", symbol: "", category: "dollar", commission_rate: 0.004, sort_order: 3, latest_price: 1045000, price_date: "1405/06/29", total_quantity: 1500, total_cost: 1100000000, total_value: 1567500000, total_profit: 467500000, profit_pct: 0.425, weight: 0.1293 },
  { asset_id: 4, name: "وبملت", symbol: "وبملت", category: "stock", commission_rate: 0.0152, sort_order: 4, latest_price: 4120, price_date: "1405/06/29", total_quantity: 1200000, total_cost: 4680000000, total_value: 4944000000, total_profit: 264000000, profit_pct: 0.0564, weight: 0.1379 },
];

const mkHoldings = (qtyMap: Record<number, number>) =>
  famAssets
    .filter((a) => qtyMap[a.asset_id])
    .map((a) => ({
      asset_id: a.asset_id,
      asset_name: a.name,
      quantity: qtyMap[a.asset_id],
      cost_basis: Math.round((a.total_cost * qtyMap[a.asset_id]) / a.total_quantity),
      value: Math.round(a.latest_price * qtyMap[a.asset_id]),
      profit: Math.round(
        a.latest_price * qtyMap[a.asset_id] - (a.total_cost * qtyMap[a.asset_id]) / a.total_quantity,
      ),
      profit_pct: a.profit_pct,
      weight: a.weight,
    }));

const people = [
  { person_id: 1, name: "علی", sort_order: 1, cash_balance: 850000000, holdings: mkHoldings({ 1: 260000, 2: 200, 3: 900 }), holdings_value: 5861000000, total_value: 5861000000, total_cost: 4450000000, profit: 1411000000, profit_pct: 0.317, share_of_total: 0.428 },
  { person_id: 2, name: "مریم", sort_order: 2, cash_balance: 1240000000, holdings: mkHoldings({ 2: 150, 3: 400 }), holdings_value: 1678000000, total_value: 2918000000, total_cost: 2300000000, profit: 618000000, profit_pct: 0.269, share_of_total: 0.213 },
  { person_id: 3, name: "رضا", sort_order: 3, cash_balance: 320000000, holdings: mkHoldings({ 1: 170000, 4: 1200000 }), holdings_value: 7060500000, total_value: 7380500000, total_cost: 6490000000, profit: 890500000, profit_pct: 0.137, share_of_total: 0.359 },
];

const famHistory = Array.from({ length: 120 }, (_, i) => {
  const d = new Date(Date.now() - (120 - 1 - i) * 86400000);
  const jal = new Intl.DateTimeFormat("fa-IR-u-nu-latn", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
  const g = 8400000000 * (1 + i * 0.0016 + Math.sin(i / 9) * 0.012);
  return {
    date_key: jal,
    total: Math.round(g),
    has_total: true,
    people: { "1": Math.round(g * 0.42), "2": Math.round(g * 0.21), "3": Math.round(g * 0.36) },
  };
});

const routes: Route[] = [
  { path: "/CompanyNames", body: companies },
  { path: "/SalesData", body: (u) => salesChart((u.searchParams.get("companyName") || "x").length) },
  { path: "/SalesData2", body: (u) => salesChart((u.searchParams.get("companyName") || "x").length + 2) },
  { path: "/CompanyScores", body: [{ companyID: "1", companyName: "فولاد مبارکه", epsGrowth: 62.4, epsLevel: "قوی", finalScore: "78.5", salesGrowth: 34.2, salesStability: "پایدار" }] },
  { path: "/AllCompanyScores", body: allScores },
  { path: "/StockPriceScore", body: [] },
  { path: "/summary", body: aiMetrics },
  {
    path: "/price-history",
    body: (u) => {
      const sym = u.searchParams.get("companyName") || "فولاد مبارکه";
      const idx = Math.max(0, companies.indexOf(sym));
      return genHistory(240, basePrice[idx]);
    },
  },
  { path: "/portfolio", body: portfolio },
  { path: "/family/broker", body: [{ person_id: 1, person_name: "علی", broker: "آگاه", username: "ali1234", has_secret: true, is_active: true, last_synced_at: "2026-09-20T10:30:00Z", last_status: "ok", last_error: "" }] },
  { path: "/family/history", body: famHistory },
  { path: "/family/cashflows", body: [
    { id: 1, date_key: "1405/04/01", amount: 500000000, direction: "in", note: "آورده نقدی" },
    { id: 2, date_key: "1405/05/15", amount: 200000000, direction: "out", note: "هزینه مسکن" },
    { id: 3, date_key: "1405/06/01", amount: 1200000000, direction: "in", note: "فروش خودرو" },
  ] },
  { path: "/family", body: { today_datekey: "1405/06/29", assets: famAssets, people, summary: {
    latest_datekey: "1405/06/29", holdings_value: 14599600000, total_cash: 2410000000,
    grand_total: 13694000000, total_cost: 10960000000, total_profit: 2734000000, total_profit_pct: 0.2494,
    best_tomorrow: 14105000000, worst_tomorrow: 13283000000,
    stocks_total: 10297500000, gold_total: 3528000000, dollar_total: 1567500000,
  } } },
  { path: "/GetUrl", body: { url: "" } },
  { path: "/GetUrl2", body: { url: "" } },
];

// توکن JWT ساختگی (فقط decode سمت کلاینت می‌شود)
const b64url = (obj: unknown) =>
  btoa(JSON.stringify(obj)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");

export const installMockApi = () => {
  const origFetch = window.fetch.bind(window);
  window.fetch = async (input, init) => {
    const url = typeof input === "string" ? input : (input as Request)?.url || "";
    if (!url.includes("/api/")) return origFetch(input as RequestInfo, init);
    const u = new URL(url, location.href);
    const p = u.pathname.slice(u.pathname.indexOf("/api") + 4);
    const route = routes.find((r) => p === r.path || p.startsWith(r.path + "/"));
    const body = route ? (typeof route.body === "function" ? route.body(u, init) : route.body) : {};
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
  localStorage.setItem(
    "token",
    `${b64url({ alg: "none", typ: "JWT" })}.${b64url({
      exp: 4102444800,
      isAdmin: true,
      username: "علی",
    })}.mock`,
  );
  console.info("[mock] API mock فعال است (?__mock=1)");
};
