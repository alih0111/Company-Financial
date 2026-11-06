import type { PerformanceCase, PerformanceReport } from "./factorMixTypes";
export type BenchmarkDefinition = {id:string;label:string;color:string;maxAgeDays?:number;rows:{date:string;closing_price:number;last_price?:number}[]};
export type BenchmarkSnapshot = {
  schema_version:number;start:string;as_of:string;identity_verified:boolean;synthetic_prices:boolean;
  series:Record<string,{label:string;unit:string;public_instrument_id:string;count:number;
    rows:{date:string;closing_price:number}[]}>;
};
export type AlignedBenchmarks = {
  points: {date:string;nav_toman:number;baseline_toman:number;[key:string]:string|number|null}[];
  start:string|null;end:string|null;
  series:{id:string;label:string;color:string;anchor_date:string;anchor_value:number;end_value:number;
    end_price_date:string;final_toman:number|null;return_fraction:number|null}[];
};
export function validatePerformanceReport(report: unknown): PerformanceReport;
export function validateBenchmarkSnapshot(snapshot: unknown): BenchmarkSnapshot;
export function selectBenchmarkRows(live:BenchmarkDefinition['rows'],cached:BenchmarkDefinition['rows'],start:string,end:string):BenchmarkDefinition['rows'];
export function alignBenchmarks(replay:PerformanceCase,definitions:BenchmarkDefinition[],maxAgeDays?:number,preserveWindow?:boolean):AlignedBenchmarks;
export type DrawdownComparison = {
  points:{date:string;drawdown:number;baseline_drawdown:number;[key:string]:string|number|null}[];
  series:{id:string;label:string;color:string;max_drawdown:number}[];
  start:string;end:string;
};
export function drawdownComparison(replay:PerformanceCase,definitions:BenchmarkDefinition[],maxAgeDays?:number,preserveWindow?:boolean):DrawdownComparison;

export function familyHistoryPrices(history:import("../utils/api").FamilyHistoryRow[]):BenchmarkDefinition["rows"];
