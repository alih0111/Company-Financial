import { monthlyStrategyId } from "./monthlyBasketPlan.js";

const close = (a, b) => Number.isFinite(a) && Number.isFinite(b) && Math.abs(a - b) < 1;
const validDate = value => typeof value === "string" && /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value));

export function validateMonthlyPortfolio(data) {
  const fail = () => { throw new Error("اطلاعات سبد ماهانه با دفتر معاملات سازگار نیست؛ گزارش را دوباره دریافت کنید."); };
  if (data?.schema_version !== 1 || data.strategy_id !== monthlyStrategyId || data.mode !== "historical_replay" ||
      data.ledger_reconciled !== true || !/^[a-f0-9]{64}$/.test(data.policy_sha256) ||
      !validDate(data.start) || !validDate(data.as_of) || data.start > data.as_of ||
      !Number.isFinite(data.initial_toman) || data.initial_toman <= 0 ||
      !Number.isFinite(data.nav_toman) || data.nav_toman <= 0 || !Number.isFinite(data.cash_toman) || data.cash_toman < 0 ||
      !Array.isArray(data.positions) || !Array.isArray(data.trades) ||
      !validDate(data.last_decision?.date) || data.last_decision.date < data.start || data.last_decision.date > data.as_of ||
      !Array.isArray(data.last_decision.targets) || data.last_decision.targets.some(s => typeof s !== "string" || !s) ||
      data.downloads?.trades !== "from-1401-monthly15-trades.csv") fail();
  const units = new Map();
  let cash = data.initial_toman, buys = 0, sells = 0, previous = data.start;
  for (const t of data.trades) {
    if (!validDate(t.session) || !validDate(t.decision) || t.session < previous || t.session > data.as_of ||
        t.decision < data.start || t.decision >= t.session || typeof t.symbol !== "string" || !t.symbol ||
        !["BUY", "SELL"].includes(t.side) ||
        [t.gross_toman, t.units, t.index_price].some(v => !Number.isFinite(v) || v <= 0) ||
        [t.fee_toman, t.slippage_toman].some(v => !Number.isFinite(v) || v < 0) ||
        !close(t.gross_toman, t.units * t.index_price + (t.side === "BUY" ? t.slippage_toman : -t.slippage_toman))) fail();
    const buy = t.side === "BUY";
    buys += Number(buy); sells += Number(!buy);
    cash += (buy ? -t.gross_toman : t.gross_toman) - t.fee_toman;
    const held = (units.get(t.symbol) ?? 0) + (buy ? t.units : -t.units);
    if (held < -1e-6 || cash < -1) fail();
    units.set(t.symbol, held);
    previous = t.session;
  }
  const seen = new Set();
  for (const p of data.positions) {
    if (typeof p.symbol !== "string" || !p.symbol || seen.has(p.symbol) ||
        [p.market_value_toman, p.index_units, p.cost_basis_toman, p.average_cost_toman, p.last_index_price_toman].some(v => !Number.isFinite(v) || v <= 0) ||
        !Number.isFinite(p.unrealized_pnl_toman) || !Number.isFinite(p.weight) || p.weight < 0 || p.weight > 1 ||
        !validDate(p.price_date) || p.price_date > data.as_of || !Number.isInteger(p.price_age_days) || p.price_age_days < 0 ||
        (Date.parse(data.as_of) - Date.parse(p.price_date)) / 86400000 !== p.price_age_days ||
        !["HOLD", "EXIT_UNFILLED"].includes(p.action) ||
        !validDate(p.first_buy) || !validDate(p.last_buy) || p.first_buy < data.start || p.first_buy > p.last_buy || p.last_buy > data.as_of ||
        !close(p.market_value_toman, p.index_units * p.last_index_price_toman) ||
        !close(p.cost_basis_toman, p.index_units * p.average_cost_toman) ||
        !close(p.unrealized_pnl_toman, p.market_value_toman - p.cost_basis_toman) ||
        Math.abs(p.weight - p.market_value_toman / data.nav_toman) > 1e-9 ||
        Math.abs((units.get(p.symbol) ?? 0) - p.index_units) > 1e-6) fail();
    seen.add(p.symbol);
  }
  if ([...units].some(([symbol, value]) => !seen.has(symbol) && Math.abs(value) > 1e-6) ||
      !close(cash, data.cash_toman) || buys !== data.buy_count || sells !== data.sell_count ||
      !close(data.cash_toman + data.positions.reduce((sum, p) => sum + p.market_value_toman, 0), data.nav_toman)) fail();
  return data;
}
