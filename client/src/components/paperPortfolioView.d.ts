export type MarketState =
  | "source_error"
  | "confirmed_session_missing_data"
  | "calendar_verified_waiting"
  | "natural_weekly_closure"
  | "calendar_unknown";

export function assessMarketState(input: {
  checkedAtUtc: string;
  lastConfirmedSession: string | null;
  latestQuoteDate?: string | null;
  calendarVerified: boolean;
  confirmedSessions?: string[];
  sourceError?: boolean;
}): { state: MarketState; missedSession: string | null };

export function estimateTarget(input: {
  cashToman: number;
  priceRial: number;
  feeRate?: number;
}): { shares: number; grossToman: number; feeToman: number; totalToman: number; remainingToman: number } | null;

export function sessionCountLabel(input: { calendarVerified: boolean; observed: number; expirySessions: number }): string;

export function isPostDecisionPrice(priceDate: string | null, decisionAtUtc: string | null): boolean;
