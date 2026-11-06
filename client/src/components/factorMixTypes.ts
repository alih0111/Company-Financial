export type FactorMixHolding = {
  symbol: string; index_units: number; cost_basis_toman: number; average_cost_toman: number;
  last_index_price_toman: number; price_date: string; price_age_days: number; market_value_toman: number;
  weight: number; unrealized_pnl_toman: number; realized_pnl_toman: number; first_buy: string;
  last_buy: string; decision_rank: number | null; action: "HOLD" | "EXIT_UNFILLED";
  pending_order: boolean; target_weight: number;
};
export type FactorMixTrade = {
  id: string; session: string; decision: string; symbol: string; side: "BUY" | "SELL";
  gross_toman: number; fee_toman: number; slippage_toman: number; units: number; index_price: number;
  cash_delta_toman: number; cash_after_toman: number; realized_pnl_toman: number | null;
};
export type FactorMixDecision = {
  date: string; signal_date: string; nav_toman: number; targets: { symbol: string; rank: number; weight: number }[];
  held: string[]; entrants: string[]; exits: string[]; fill_count: number;
};
export type FactorMixRanking = {
  date: string; financial_snapshot_date: string; signal_age_days: number;
  universe_count: number; eligible_count: number; excluded_count: number;
  model: string; basis: string;
  rows: { rank: number; symbol: string; score: number; selected_in_last_decision: boolean; held_at_portfolio_end: boolean }[];
};
export type FactorMixDashboard = {
  schema_version: number; strategy_id: string; version: string; mode: string; as_of: string; start: string;
  generated_at_utc: string; initial_toman: number; nav_toman: number; cash_toman: number;
  realized_pnl_toman: number; unrealized_pnl_toman: number; fees_toman: number; slippage_toman: number;
  policy_sha256: string; manifest_sha256: string; next_nominal_review: string;
  metrics: { final_toman: number; total_return: number; cagr: number; max_drawdown: number };
  baseline: { final_toman: number; total_return: number; max_drawdown: number };
  holdings: FactorMixHolding[]; trades: FactorMixTrade[]; decisions: FactorMixDecision[];
  rankings: { decision: FactorMixRanking; latest: FactorMixRanking };
  orders: { symbol: string; side: string; status: string; reason: string; decision_date: string;
    eligible_sessions_observed: number; lifetime_sessions: number; target_weight: number; partial_units: number }[];
  path: { date: string; nav_toman: number; baseline_toman: number; cash_toman: number; drawdown: number }[];
  annual: { year: number; start: string; end: string; initial_toman: number; final_toman: number; return_fraction: number }[];
  policy: { block_weights: Record<string, number>; rules: { target_names: number; exit_when_rank_exceeds: number };
    execution: { fee: number; slippage: number; capacity: number; order_life: number } };
  integrity: { verified_files: number; daily_nav_reproduced: boolean; ledger_reconciled: boolean };
  forward: { status: string; started_at_utc: string | null; initial_toman: number | null; cash_toman: number | null;
    nav_toman: number | null; holdings: unknown[]; trades: unknown[]; execution_enabled: boolean;
    automatic_updates_enabled: boolean; events: { id: string; at_utc: string; kind: string }[] };
};

export type PerformanceAccount = {
  start: string; end: string; final_toman: number; total_return: number; cagr: number; max_drawdown: number;
  fees_toman: number; slippage_toman: number; trade_count: number; buy_count: number; sell_count: number;
  decision_count: number; first_fill: string; cash_toman: number; holdings_value_toman: number;
  positions: { symbol: string; market_value_toman: number; price_date?: string; price_age_days?: number; action?: string }[];
};
export type PerformancePoint = {
  date: string; nav_toman: number; baseline_toman: number; cash_toman: number;
  drawdown: number; baseline_drawdown: number; n_positions: number; baseline_positions: number;
  monthly15_toman?: number; monthly15_drawdown?: number;
};
export type PerformanceCase = {
  id: string; start_year: number; start: string; as_of: string; initial_toman: number;
  accounts: { candidate: PerformanceAccount; baseline: PerformanceAccount };
  path: PerformancePoint[];
  annual: { year: number; start: string; end: string; initial_toman: number; final_toman: number;
    return_fraction: number; baseline_initial_toman: number; baseline_final_toman: number; baseline_return_fraction: number }[];
  downloads: Record<string, string>;
  monthly15?: { strategy_id:string;label:string;policy_sha256:string;archive_sha256:string;account:PerformanceAccount;
    annual:{year:number;start:string;end:string;initial_toman:number;final_toman:number;return_fraction:number}[];
    downloads:Record<string,string>;reviews_scheduled:number;stale_decisions_skipped:number;
    same_frozen_inputs_as_parent:boolean;only_review_calendar_changed:boolean };
};
export type PerformanceReport = {
  schema_version: number; strategy_id: string; policy_sha256: string; mode: string; default_case: string;
  cases: PerformanceCase[];
  integrity: { archive_verified_files: number; extended_delivery_manifest_sha256: string;
    separate_initial_capital_verified: boolean; annual_and_daily_metrics_reconciled: boolean };
};
