// Read-only sidecar fields consumed by the QVT views. These types do not
// establish provenance or turn missing fields into valid observations.
export type QFactor = {
  factor: string; fa?: string; status?: string; status_fa?: string;
  value?: number | null; value_pp?: number | null; n_valid_years?: number;
  window?: number[]; mean_roe_pct?: number | null; blended_score_preserved?: number | null;
  components?: Record<string, { status?: string }>;
  missing_reason?: string; excluded_years?: { fy: number | string; reason: string }[];
};
export type QVerdict = { verdict: string; condition?: string };
export type AuditComponent = {
  value_pct?: number | null; period_current?: string; period_base?: string;
  current_ttm?: number | null; base?: number | null; status_fa?: string; status?: string;
  value_match_with_engine?: boolean | null;
};
export type EconomicAudit = {
  verdict: string; verdict_fa?: string; components?: Record<string, AuditComponent>;
  warnings?: string[]; limitations?: string[]; in_official_composite?: boolean;
  _meta?: { reproduction_summary?: { n_components_value_compared?: number; n_value_diff?: number };
    classification_counts?: { verified?: number; verified_with_limitation?: number; insufficient_evidence?: number };
    quarantine_leak_proof?: { verdict?: string; n_quarantined_components_checked?: number };
    economic_quality_note?: string; disclaimer?: string };
};
type DiagnosticMeta = {
  quarantine_verdict?: string; verdict?: string; quarantine_companies?: number;
  n_companies_with_quarantined_base?: number; quarantine_leaks?: number;
  n_valid_despite_quarantine?: number; sentinel_rows_total?: number; sentinel_check?: string;
  consistency_verdict?: string; consistency_scores_checked?: number; n_company_factor_scores_checked?: number;
  independent_reproduction?: { n_years_compared?: number; n_match?: number; n_mismatch?: number };
};
export type QDiagnostics = {
  factors?: { roe_stability?: QFactor; margin_trend?: QFactor; earnings_growth?: QFactor };
  activation_readiness?: Record<string, QVerdict>; factors_meta?: { activation_readiness?: Record<string, QVerdict> };
  _meta?: DiagnosticMeta; quarantine_proof?: DiagnosticMeta; consistency_with_production_artifact?: DiagnosticMeta;
  independent_reproduction?: DiagnosticMeta["independent_reproduction"];
};
type DossierFactor = { factor: string; fa: string; score: number; contribution?: number; weight?: number; warnings?: string[]; plain?: string; raw_value?: number | null };
type DossierRatio = { name: string; fa: string; raw_value?: number | null; included?: boolean; peer_rank?: number | null; n_peers?: number | null; reliability: string; reliability_fa?: string; warnings?: string[] };
type CapitalEvent = { outcome?: string; ex_date?: string; old_shares?: number; new_shares?: number; funding_tags?: string[]; codal_reference?: string; implied_vs_recorded_rel_diff?: number; ratio_classification?: {pe?: string; ps?: string; pb?: string}; caveat?: string };
export type DecisionDossier = { sections?: {
  quality?: { strengths?: DossierFactor[]; weaknesses?: DossierFactor[]; excluded_diagnostic?: {factor:string;fa:string;reason:string}[]; coverage?: {covered_weight?:number;missing_weight?:number}; evidence_note?:string };
  value?: {ratios?:DossierRatio[];caveats?:string[]};
  market?: {factors?:DossierFactor[];price?:{price_rial?:number|null;trade_date?:string;market_cap_rial?:number|null;share_source?:string;note?:string};adjustment_status?:string};
  evidence?: {independent_validation?:{status?:string;status_definition?:string;status_label?:string};effective_dates?:{winner_publish_at?:string;winner_period_end?:string;winner_tracing_no?:string;price_trade_date?:string};risk_gate?:{financial_warnings?:string[]};capital_events?:CapitalEvent[]};
  summary?: {why_review?:string[];main_risk?:string[];needed_evidence?:string[]};
} };
export type IndependentValidation = { status:string;status_definition?:string;status_label?:string;reasons?:string[];checks?: {
  q_cell_trace?: {cell?:string;version_no?:number;tracing_no?:string;publish_at?:string}[];
  independent_valuation?: {compare?:Record<string,{mine?:number|null;artifact?:number|null}>};
  independent_market?: {share_source?:string;price?:number|null;shares?:number|null};
  eps_cross_check?: {flag?:boolean;used_vs_implied_ratio?:number};
  event_coverage?: {snapshot_history?:boolean;steps_without_events?:number;share_count_steps?:number};
  t_probe?: {compare?:Record<string,{match?:boolean}>};
} };
export type OverlayCompany = {
  publish_recovery?: {scoring_rows?:{resolved?:{status?:string;publish_at?:string}}[];q_origin_before?:string;q_origin_after?:string;codal_symbol?:string};
  valuation_audit?: {verdict?:string;verdict_label?:string};
  independent_validation?:IndependentValidation; decision_dossier?:DecisionDossier;
  q_factor_diagnostics?:QDiagnostics; eg_economic_audit?:EconomicAudit;
};
