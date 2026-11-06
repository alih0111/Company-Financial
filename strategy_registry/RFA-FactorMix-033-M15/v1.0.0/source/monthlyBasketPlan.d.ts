export type MonthlyRanking = {date:string;market_date:string;computed_at_utc:string;rows:{symbol:string;rank:number|null;score:number|null;reason:string|null}[]};
export type MonthlyPlan = {strategy_id:string;ranking_date:string;ranking_computed_at_utc:string;market_date:string;nav_toman:number;cash_toman:number;changes:number;missing_slots:number;amounts_before_costs:boolean;executed:boolean;
  rows:{symbol:string;rank:number|null;current_toman:number;current_weight:number;target_weight:number;target_toman:number;delta_toman:number;action:"BUY"|"SELL"|"HOLD";reason:string}[]};
export const monthlyStrategyId: string;
export function normalizeSymbol(value:string):string;
export function parseToman(value:string):number;
export function monthlyBasketPlan(ranking:MonthlyRanking,holdings:{symbol:string;value_toman:number}[],cash:number):MonthlyPlan;
