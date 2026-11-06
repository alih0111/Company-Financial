import assert from "node:assert/strict";
import test from "node:test";
import {monthlyBasketPlan,parseToman} from "../src/components/monthlyBasketPlan.js";

const ranking={date:"2026-11-06",market_date:"2026-11-04",computed_at_utc:"2026-11-06T18:00:00Z",
  rows:Array.from({length:10},(_,i)=>({symbol:`سهم${i+1}`,rank:i+1,score:1-i/20,reason:null}))};
test("cash-only initial entry selects five 20% targets and does not execute",()=>{
  const plan=monthlyBasketPlan(ranking,[],100_000_000);
  assert.deepEqual(plan.rows.map(r=>r.symbol),["سهم1","سهم2","سهم3","سهم4","سهم5"]);
  assert.ok(plan.rows.every(r=>r.delta_toman===20_000_000 && r.action==="BUY"));
  assert.equal(plan.executed,false);
});
test("buffer keeps held rank 8, exits rank 9 and fills only missing slots",()=>{
  const plan=monthlyBasketPlan(ranking,[{symbol:"سهم8",value_toman:20},{symbol:"سهم9",value_toman:20}],60);
  assert.deepEqual(plan.rows.filter(r=>r.target_weight>0).map(r=>r.symbol),["سهم8","سهم1","سهم2","سهم3","سهم4"]);
  assert.equal(plan.rows.find(r=>r.symbol==="سهم8").action,"HOLD");
  assert.equal(plan.rows.find(r=>r.symbol==="سهم9").delta_toman,-20);
});
test("weight changes require over five percentage points; missing slots remain cash",()=>{
  const small={...ranking,rows:ranking.rows.slice(0,2)};
  const plan=monthlyBasketPlan(small,[{symbol:"سهم1",value_toman:25},{symbol:"سهم2",value_toman:26}],49);
  assert.equal(plan.rows[0].action,"HOLD");
  assert.equal(plan.rows[1].delta_toman,-6);
  assert.equal(plan.missing_slots,3);
});
test("invalid, duplicate, unknown and incomplete financial entries are rejected",()=>{
  for (const holdings of [[{symbol:"unknown",value_toman:10}],[{symbol:"سهم1",value_toman:-1}],
    [{symbol:"سهم1",value_toman:10},{symbol:"سهم1",value_toman:10}]]) {
    assert.throws(()=>monthlyBasketPlan(ranking,holdings,100));
  }
  assert.throws(()=>monthlyBasketPlan(ranking,[],NaN));
  assert.throws(()=>monthlyBasketPlan(ranking,[],0));
  assert.equal(parseToman("۱۰۰٬۰۰۰٬۰۰۰"),100_000_000);
  assert.equal(parseToman("١٢٣"),123);
  assert.ok(Number.isNaN(parseToman("")));
});
