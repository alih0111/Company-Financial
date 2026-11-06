import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { familyHistoryPrices, alignBenchmarks, drawdownComparison, selectBenchmarkRows, validateBenchmarkSnapshot, validatePerformanceReport } from "../src/components/strategyPerformanceData.js";

const source = JSON.parse(readFileSync(new URL("../public/strategies/factormix-033/performance/performance.json", import.meta.url)));
const clone = () => structuredClone(source);

test("published periods are separate 100m accounts with the approved final values", () => {
  const report = validatePerformanceReport(clone());
  assert.equal(report.default_case,"from-1401");
  const [a,b] = report.cases;
  assert.equal(a.start,"2022-03-26"); assert.equal(b.start,"2023-03-25");
  assert.ok(Math.abs(a.accounts.candidate.final_toman-2547465821.316608)<1);
  assert.ok(Math.abs(a.accounts.baseline.final_toman-1539972413.5330396)<1);
  assert.ok(Math.abs(b.accounts.candidate.final_toman-1290465605.5777485)<1);
  assert.equal(a.path[0].nav_toman,b.path[0].nav_toman);
  assert.ok(a.downloads.candidate_nav.startsWith("from-1401-"));
  assert.ok(b.downloads.candidate_nav.startsWith("from-1402-"));
});

test("a 1402 slice from the earlier account cannot be mislabeled as a fresh trial", () => {
  const report=clone();
  report.cases[1].path=report.cases[0].path.filter(p=>p.date>=report.cases[1].start);
  assert.throws(()=>validatePerformanceReport(report),/سازگار نیست/);
});

test("wrong terminal metrics, NaN, drawdowns and annual resets are rejected", () => {
  for (const change of [
    r=>r.cases[0].accounts.candidate.final_toman+=100_000,
    r=>r.cases[0].path[10].nav_toman=NaN,
    r=>r.cases[0].path[15].drawdown=0.25,
    r=>r.cases[0].annual[1].initial_toman=100_000_000,
    r=>r.cases[0].downloads.chart="../wrong.png",
  ]) { const report=clone(); change(report); assert.throws(()=>validatePerformanceReport(report)); }
});

const replay = {
  start:"2022-01-01", as_of:"2022-01-20", initial_toman:100,
  path:[
    {date:"2022-01-01",nav_toman:100,baseline_toman:100},
    {date:"2022-01-03",nav_toman:120,baseline_toman:110},
    {date:"2022-01-05",nav_toman:150,baseline_toman:125},
    {date:"2022-01-07",nav_toman:180,baseline_toman:140},
    {date:"2022-01-20",nav_toman:200,baseline_toman:160},
  ],
};
const series=(id,rows)=>({id,label:id,color:"#000",rows:rows.map(([date,closing_price])=>({date,closing_price}))});

test("all benchmark and strategy lines start at 100 on the SAME common date", () => {
  const result=alignBenchmarks(replay,[
    series("index",[["2022-01-01",10],["2022-01-05",15],["2022-01-20",20]]),
    series("gold",[["2022-01-03",1000],["2022-01-07",1400],["2022-01-20",2000]]),
  ]);
  assert.equal(result.start,"2022-01-03");
  const first=result.points[0];
  for (const key of ["nav_toman","baseline_toman","index","gold"]) assert.equal(first[key],100);
  const last=result.points.at(-1);
  assert.equal(last.index,200); assert.equal(last.gold,200);
  assert.ok(Math.abs(last.nav_toman-100*200/120)<1e-12);
  assert.ok(Math.abs(last.baseline_toman-100*160/110)<1e-12);
});

test("future prices never fill earlier dates; old marks produce visible gaps", () => {
  const result=alignBenchmarks(replay,[series("index",[["2022-01-01",10],["2022-01-20",20]])]);
  assert.equal(result.points[0].index,100);
  const sparse={...replay,path:[...replay.path.slice(0,4),{date:"2022-01-15",nav_toman:190,baseline_toman:150},replay.path.at(-1)]};
  const gap=alignBenchmarks(sparse,[series("index",[["2022-01-01",10],["2022-01-20",20]])]);
  assert.equal(gap.points.find(p=>p.date==="2022-01-15").index,null);
  assert.equal(gap.points.at(-1).index,200);
});

test("comparisons stop at the last common price, and missing gold does not block index", () => {
  const result=alignBenchmarks(replay,[series("index",[["2022-01-01",10],["2022-01-07",14]]),series("gold",[])]);
  assert.equal(result.end,"2022-01-07");
  assert.equal(result.series.length,1);
  assert.equal(result.series[0].id,"index");
  assert.equal(alignBenchmarks(replay,[series("index",[["2022-01-05",5]])]).points.length,0);
});

test("real collected benchmarks cover 1401 to the model endpoint without a late rebase", () => {
  const snapshot=validateBenchmarkSnapshot(JSON.parse(readFileSync(new URL("../public/strategies/factormix-033/performance/benchmarks.json",import.meta.url))));
  const account=source.cases.find(c=>c.start_year===1401);
  const definitions=Object.entries(snapshot.series).map(([id,s])=>({id,label:s.label,color:"#000",rows:s.rows}));
  const result=alignBenchmarks(account,definitions);
  assert.equal(snapshot.series.index_toman.count,1108);
  assert.equal(snapshot.series.mesghal_toman.count,1076);
  assert.equal(result.start,"2022-03-26");
  assert.equal(result.end,"2026-11-04");
  assert.equal(result.points.length,account.path.length);
  for (const id of ["nav_toman","baseline_toman","index_toman","mesghal_toman"]) assert.equal(result.points[0][id],100_000_000);
  assert.ok(Math.abs(result.points.at(-1).index_toman-568910092.0818973)<1);
  assert.ok(Math.abs(result.points.at(-1).mesghal_toman-2075902247.886162)<1);
  assert.equal(result.points.find(p=>p.date==="2025-06-22").mesghal_toman,null);
});

test("two recent API observations cannot truncate the four-series history", () => {
  const snapshot=JSON.parse(readFileSync(new URL("../public/strategies/factormix-033/performance/benchmarks.json",import.meta.url)));
  const recent=[{date:"2026-09-30",closing_price:7766531.26},{date:"2026-10-24",closing_price:8044655.81}];
  const rows=selectBenchmarkRows(recent,snapshot.series.index_toman.rows,"2022-03-26","2026-11-04");
  assert.equal(rows[0].date,"2022-03-26");assert.equal(rows.at(-1).date,"2026-11-04");
  assert.equal(rows.length,1108);
  assert.deepEqual(selectBenchmarkRows(recent,[],"2022-03-26","2026-11-04"),[]);
});

test("a wrong instrument or negative price invalidates a benchmark snapshot", () => {
  const snapshot=JSON.parse(readFileSync(new URL("../public/strategies/factormix-033/performance/benchmarks.json",import.meta.url)));
  snapshot.series.index_toman.public_instrument_id="wrong";
  assert.throws(()=>validateBenchmarkSnapshot(snapshot));
  snapshot.series.index_toman.public_instrument_id="32097828799138957";
  snapshot.series.mesghal_toman.rows[0].closing_price=-1;
  assert.throws(()=>validateBenchmarkSnapshot(snapshot));
});

test("each drawdown uses its own running high, including benchmark peaks between model sessions", () => {
  const account={...replay,path:[
    {date:"2022-01-01",nav_toman:100,baseline_toman:100},
    {date:"2022-01-03",nav_toman:120,baseline_toman:80},
    {date:"2022-01-05",nav_toman:90,baseline_toman:120},
    {date:"2022-01-07",nav_toman:130,baseline_toman:100},
    {date:"2022-01-20",nav_toman:104,baseline_toman:108},
  ]};
  const result=drawdownComparison(account,[
    series("index",[["2022-01-01",10],["2022-01-02",20],["2022-01-03",15],["2022-01-05",12],["2022-01-07",25],["2022-01-20",20]]),
    series("gold",[["2022-01-01",100],["2022-01-03",200],["2022-01-05",100],["2022-01-07",150],["2022-01-20",250]]),
  ]);
  const stats=Object.fromEntries(result.series.map(s=>[s.id,s.max_drawdown]));
  assert.ok(Math.abs(stats.drawdown+.25)<1e-12);
  assert.ok(Math.abs(stats.baseline_drawdown+.2)<1e-12);
  assert.ok(Math.abs(stats.index_drawdown+.4)<1e-12);
  assert.ok(Math.abs(stats.gold_drawdown+.5)<1e-12);
  assert.equal(result.points[1].index_drawdown,-.25);
  assert.equal(result.points[3].drawdown,0);
  assert.equal(result.points[4].gold_drawdown,0);
});

test("missing benchmark prices remain gaps, preserve the peak, and cannot see later prices", () => {
  const account={...replay,path:[...replay.path.slice(0,4),{date:"2022-01-15",nav_toman:190,baseline_toman:150},replay.path.at(-1)]};
  const definition=series("gold",[["2022-01-01",100],["2022-01-03",200],["2022-01-20",120]]);
  const result=drawdownComparison(account,[definition]);
  assert.equal(result.points.find(p=>p.date==="2022-01-15").gold_drawdown,null);
  assert.equal(result.points.at(-1).gold_drawdown,-.4);
  definition.rows.at(-1).closing_price=10000;
  const changed=drawdownComparison(account,[definition]);
  assert.deepEqual(changed.points.slice(0,-1),result.points.slice(0,-1));
});

test("both real trial windows expose all four drawdowns and retain approved model drawdowns", () => {
  const snapshot=validateBenchmarkSnapshot(JSON.parse(readFileSync(new URL("../public/strategies/factormix-033/performance/benchmarks.json",import.meta.url))));
  const definitions=Object.entries(snapshot.series).map(([id,s])=>({id,label:s.label,color:"#000",rows:s.rows}));
  for (const account of source.cases) {
    const result=drawdownComparison(account,definitions);
    assert.equal(result.start,account.start);assert.equal(result.end,account.as_of);
    assert.equal(result.series.length,4);
    const stats=Object.fromEntries(result.series.map(s=>[s.id,s.max_drawdown]));
    assert.ok(Math.abs(stats.drawdown-account.accounts.candidate.max_drawdown)<1e-12);
    assert.ok(Math.abs(stats.baseline_drawdown-account.accounts.baseline.max_drawdown)<1e-12);
    for (const [id,s] of Object.entries(snapshot.series)) {
      let peak=0,minimum=0;
      for (const row of s.rows.filter(r=>r.date>=account.start && r.date<=account.as_of)) {
        peak=Math.max(peak,row.closing_price);minimum=Math.min(minimum,row.closing_price/peak-1);
      }
      assert.ok(Math.abs(stats[`${id}_drawdown`]-minimum)<1e-12);
    }
    assert.equal(result.points.find(p=>p.date==="2025-06-22").mesghal_toman_drawdown,null);
  }
});


test("family total uses verified totals and converts Persian calendar dates including leap years", () => {
  const prices=familyHistoryPrices([
    {date_key:"۱۴۰۱/۰۱/۰۱",total:200,has_total:true},
    {date_key:"1401/01/06",total:220,has_total:true},
    {date_key:"1399/12/30",total:100,has_total:true},
    {date_key:"1400/12/30",total:900,has_total:true},
    {date_key:"1401/01/08",total:240,has_total:false},
    {date_key:"1401/01/09",total:-1,has_total:true},
  ]);
  assert.deepEqual(prices,[
    {date:"2021-03-20",closing_price:100},
    {date:"2022-03-21",closing_price:200},
    {date:"2022-03-26",closing_price:220},
  ]);
});

test("family is anchored at account start without shortening or rebasing other series", () => {
  const family={...series("family",[["2021-12-28",50],["2022-01-03",75],["2022-01-07",40]]),maxAgeDays:14};
  const primary=series("index",[["2022-01-01",10],["2022-01-20",20]]);
  const before=alignBenchmarks(replay,[primary],7,true);
  const result=alignBenchmarks(replay,[primary,family],7,true);
  assert.equal(result.start,replay.start);
  assert.equal(result.end,replay.as_of);
  assert.equal(result.points[0].family,replay.initial_toman);
  assert.equal(result.points.find(p=>p.date==="2022-01-03").family,150);
  assert.equal(result.points.at(-1).family,null);
  assert.deepEqual(result.points.map(p=>[p.date,p.nav_toman,p.baseline_toman,p.index]),before.points.map(p=>[p.date,p.nav_toman,p.baseline_toman,p.index]));
  const dd=drawdownComparison(replay,[primary,family],7,true);
  assert.ok(Math.abs(dd.points.find(p=>p.date==="2022-01-07").family_drawdown-(40/75-1))<1e-12);
  assert.equal(dd.points.at(-1).family_drawdown,null);
});

test("a family history starting after 1401 cannot invent an initial price", () => {
  const late=series("family",[["2022-01-03",100],["2022-01-20",200]]);
  const result=alignBenchmarks(replay,[late],7,true);
  assert.deepEqual(result.series,[]);
  assert.deepEqual(alignBenchmarks(replay,[series("family",[["2021-01-01",10],["2022-01-20",20]])],7,true).series,[]);
});
