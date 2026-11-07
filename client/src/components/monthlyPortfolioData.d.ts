export type MonthlyPortfolio = {
  schema_version: number; strategy_id: string; mode: "historical_replay"; policy_sha256: string;
  start: string; as_of: string; initial_toman: number; nav_toman: number; cash_toman: number;
  buy_count: number; sell_count: number; ledger_reconciled: boolean;
  last_decision: { date: string; targets: string[] }; downloads: { trades: string };
  positions: {
    symbol: string; index_units: number; market_value_toman: number; cost_basis_toman: number;
    average_cost_toman: number; unrealized_pnl_toman: number; weight: number;
    last_index_price_toman: number; price_age_days: number; price_date: string;
    action: "HOLD" | "EXIT_UNFILLED"; first_buy: string; last_buy: string;
  }[];
  trades: {
    session: string; decision: string; symbol: string; side: "BUY" | "SELL";
    gross_toman: number; fee_toman: number; slippage_toman: number; units: number; index_price: number;
  }[];
};
export function validateMonthlyPortfolio(data: unknown): MonthlyPortfolio;
