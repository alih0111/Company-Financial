const finite = Number.isFinite;
const close = (a, b, tolerance = 1) => finite(a) && finite(b) && Math.abs(a - b) <= tolerance;
const error = () => new Error("گزارش عملکرد با مسیر سرمایه یا بازهٔ انتخاب‌شده سازگار نیست؛ نمایش اعداد متوقف شد.");

export function validatePerformanceReport(report) {
  if (report?.schema_version !== 1 || report.mode !== "historical_replay" ||
      report.strategy_id !== "RFA-FactorMix-033-Q40-Buffer8-v1.0.0" ||
      !/^[a-f0-9]{64}$/.test(report.policy_sha256) || !report.integrity?.separate_initial_capital_verified ||
      !report.integrity.annual_and_daily_metrics_reconciled || !Array.isArray(report.cases) || report.cases.length !== 2 ||
      !["from-1401", "from-1402"].every(id => report.cases.some(c => c.id === id)) ||
      !report.cases.some(c => c.id === report.default_case)) throw error();
  for (const c of report.cases) {
    if (c.initial_toman !== 100_000_000 || c.id !== `from-${c.start_year}` ||
        !Array.isArray(c.path) || c.path.length < 2 || !Array.isArray(c.annual) || !c.annual.length) throw error();
    if (c.path[0].date !== c.start || c.path[c.path.length - 1].date !== c.as_of ||
        c.path[0].nav_toman !== c.initial_toman || c.path[0].baseline_toman !== c.initial_toman) throw error();
    let peak = c.initial_toman, basePeak = c.initial_toman, dd = 0, baseDD = 0;
    for (let i = 0; i < c.path.length; i++) {
      const p = c.path[i];
      if (!/^\d{4}-\d{2}-\d{2}$/.test(p.date) || (i && p.date <= c.path[i-1].date) ||
          !finite(p.nav_toman) || p.nav_toman <= 0 || !finite(p.baseline_toman) || p.baseline_toman <= 0 ||
          !finite(p.cash_toman) || p.cash_toman < 0) throw error();
      peak = Math.max(peak,p.nav_toman); basePeak = Math.max(basePeak,p.baseline_toman);
      const d = p.nav_toman / peak - 1, bd = p.baseline_toman / basePeak - 1;
      if (!close(p.drawdown,d,1e-10) || !close(p.baseline_drawdown,bd,1e-10)) throw error();
      dd = Math.min(dd,d); baseDD = Math.min(baseDD,bd);
    }
    for (const [label,key,drawdown] of [["candidate","nav_toman",dd],["baseline","baseline_toman",baseDD]]) {
      const a = c.accounts?.[label], last = c.path[c.path.length-1];
      if (!a || a.start !== c.start || a.end !== c.as_of || !close(a.final_toman,last[key]) ||
          !close(a.max_drawdown,drawdown,1e-10) || !close(a.total_return,a.final_toman/c.initial_toman-1,1e-10) ||
          !close(a.cash_toman+a.holdings_value_toman,a.final_toman) ||
          !finite(a.fees_toman) || !finite(a.slippage_toman) ||
          a.buy_count+a.sell_count !== a.trade_count || !finite(a.cagr)) throw error();
    }
    let last = c.initial_toman, baseLast = c.initial_toman;
    for (const y of c.annual) {
      const end = c.path.find(p => p.date === y.end);
      if (!end || !close(y.initial_toman,last) || !close(y.baseline_initial_toman,baseLast) ||
          !close(y.final_toman,end.nav_toman) || !close(y.baseline_final_toman,end.baseline_toman) ||
          !close(y.return_fraction,y.final_toman/y.initial_toman-1,1e-10) ||
          !close(y.baseline_return_fraction,y.baseline_final_toman/y.baseline_initial_toman-1,1e-10)) throw error();
      last = y.final_toman; baseLast = y.baseline_final_toman;
    }
    if (!close(last,c.accounts.candidate.final_toman) || !close(baseLast,c.accounts.baseline.final_toman) ||
        !c.downloads || Object.values(c.downloads).some(v => typeof v !== "string" || !/^[a-z0-9.-]+$/.test(v) || v.includes(".."))) throw error();
    if (c.monthly15) {
      const m=c.monthly15,a=m.account;
      if (m.strategy_id !== "RFA-FactorMix-033-M15-Buffer8-v1.0.0" || !/^[a-f0-9]{64}$/.test(m.policy_sha256) ||
          !/^[a-f0-9]{64}$/.test(m.archive_sha256) || !m.same_frozen_inputs_as_parent || !m.only_review_calendar_changed ||
          !a || a.start!==c.start || a.end!==c.as_of || c.path[0].monthly15_toman!==c.initial_toman ||
          !m.downloads || Object.values(m.downloads).some(v=>typeof v!=="string" || !/^[a-z0-9.-]+$/.test(v) || v.includes(".."))) throw error();
      let high=c.initial_toman,worst=0,previous=c.initial_toman;
      for (const p of c.path) {
        if (!finite(p.monthly15_toman) || p.monthly15_toman<=0) throw error();
        high=Math.max(high,p.monthly15_toman);
        const dd=p.monthly15_toman/high-1;
        if (!close(dd,p.monthly15_drawdown,1e-10)) throw error();
        worst=Math.min(worst,dd);
      }
      if (!close(a.final_toman,c.path.at(-1).monthly15_toman) || !close(a.max_drawdown,worst,1e-10) ||
          !close(a.total_return,a.final_toman/c.initial_toman-1,1e-10) || !close(a.cash_toman+a.holdings_value_toman,a.final_toman) ||
          !finite(a.fees_toman) || !finite(a.slippage_toman) || a.trade_count!==a.buy_count+a.sell_count ||
          a.decision_count+m.stale_decisions_skipped!==m.reviews_scheduled || !Array.isArray(m.annual) || !m.annual.length) throw error();
      for (const y of m.annual) {
        const end=c.path.find(p=>p.date===y.end);
        if (!end || !close(y.initial_toman,previous) || !close(y.final_toman,end.monthly15_toman) ||
            !close(y.return_fraction,y.final_toman/y.initial_toman-1,1e-10)) throw error();
        previous=y.final_toman;
      }
      if (!close(previous,a.final_toman)) throw error();
    }
  }
  return report;
}

function cleanPrices(rows,start,end) {
  const byDate = new Map();
  for (const row of rows) {
    const date = String(row.date).slice(0,10);
    const value = Number(row.closing_price) > 0 ? Number(row.closing_price) : Number(row.last_price);
    if (/^\d{4}-\d{2}-\d{2}$/.test(date) && date >= start && date <= end && finite(value) && value > 0) byDate.set(date,{date,value});
  }
  return [...byDate.values()].sort((a,b)=>a.date.localeCompare(b.date));
}

export function validateBenchmarkSnapshot(snapshot) {
  if (snapshot?.schema_version !== 1 || snapshot.identity_verified !== true || snapshot.synthetic_prices !== false) throw error();
  for (const [key,id,unit] of [["index_toman","32097828799138957","index_level"],["mesghal_toman","32469128621155736","rial"]]) {
    const s=snapshot.series?.[key];
    if (!s || s.public_instrument_id !== id || s.unit !== unit || !Array.isArray(s.rows) || s.rows.length<2 || s.rows.length!==s.count ||
        s.rows[0].date!==snapshot.start || s.rows[s.rows.length-1].date!==snapshot.as_of) throw error();
    for (let i=0;i<s.rows.length;i++) {
      const row=s.rows[i];
      if (!/^\d{4}-\d{2}-\d{2}$/.test(row.date) || !finite(row.closing_price) || row.closing_price<=0 ||
          (i && row.date<=s.rows[i-1].date)) throw error();
    }
  }
  return snapshot;
}

/** Use a complete series as one unit; do not splice different adjustment bases. */
export function selectBenchmarkRows(live,cached,start,end) {
  const normalize = rows => cleanPrices(rows,"0000-01-01","9999-12-31");
  const a=normalize(live), b=normalize(cached);
  const covers = rows => rows.length>=2 && rows[0].date<=start && rows[rows.length-1].date>=end;
  if (covers(a)) return a.map(p=>({date:p.date,closing_price:p.value}));
  if (covers(b)) return b.map(p=>({date:p.date,closing_price:p.value}));
  // A short response must not silently move a requested 1401 comparison to 1405.
  return [];
}

/** Rebase EVERY displayed series at one common date; never backfill prices. */
export function alignBenchmarks(replay,definitions,maxAgeDays=7,preserveWindow=false) {
  const usable = definitions.map(d=>({...d,points:cleanPrices(d.rows,preserveWindow ? "0000-01-01" : replay.start,replay.as_of)})).filter(d=>d.points.length>=2);
  if (!usable.length) return {points:[],series:[],start:null,end:null};
  const first = preserveWindow ? replay.start : usable.reduce((day,d)=>day > d.points[0].date ? day : d.points[0].date,replay.start);
  const last = preserveWindow ? replay.as_of : usable.reduce((day,d)=>day < d.points[d.points.length-1].date ? day : d.points[d.points.length-1].date,replay.as_of);
  const path = replay.path.filter(p=>p.date>=first && p.date<=last);
  if (path.length<2) return {points:[],series:[],start:null,end:null};
  const start = path[0].date, end = path[path.length-1].date, initial = replay.initial_toman;
  const age = (a,b)=>(Date.parse(a+"T12:00:00Z")-Date.parse(b+"T12:00:00Z"))/86_400_000;
  const state = usable.map(d=>{
    let cursor=0;
    while (cursor+1<d.points.length && d.points[cursor+1].date<=start) cursor++;
    return {...d,cursor,anchor:d.points[cursor]};
  }).filter(d=>d.anchor.date<=start && age(start,d.anchor.date)<=(d.maxAgeDays ?? maxAgeDays));
  if (!state.length) return {points:[],series:[],start:null,end:null};
  const points=path.map(p=>{
    const point={date:p.date,nav_toman:initial*p.nav_toman/path[0].nav_toman,
      baseline_toman:initial*p.baseline_toman/path[0].baseline_toman};
    if (replay.monthly15) point.monthly15_toman=initial*p.monthly15_toman/path[0].monthly15_toman;
    for (const s of state) {
      while (s.cursor+1<s.points.length && s.points[s.cursor+1].date<=p.date) s.cursor++;
      const mark=s.points[s.cursor];
      point[s.id]=mark.date<=p.date && p.date<=s.points[s.points.length-1].date && age(p.date,mark.date)<=(s.maxAgeDays ?? maxAgeDays) ? initial*mark.value/s.anchor.value : null;
    }
    return point;
  });
  return {points,start,end,series:state.map(s=>{
    const final=points[points.length-1][s.id];
    return {id:s.id,label:s.label,color:s.color,anchor_date:s.anchor.date,anchor_value:s.anchor.value,
      end_value:s.points[s.cursor].value,end_price_date:s.points[s.cursor].date,
      final_toman:final,return_fraction:final==null ? null : final/initial-1};
  })};
}

/** Each series falls from its own observed running high, across quote gaps. */
export function drawdownComparison(replay,definitions,maxAgeDays=7,preserveWindow=false) {
  const aligned=alignBenchmarks(replay,definitions,maxAgeDays,preserveWindow);
  const path=aligned.points.length>=2 ? aligned.points : replay.path;
  const start=path[0].date,end=path[path.length-1].date;
  const series=[
    {id:"drawdown",label:"FactorMix · فصلی قدیمی",color:"#059669",max_drawdown:0},
    {id:"baseline_drawdown",label:"مدل قبلی P1",color:"#94a3b8",max_drawdown:0},
  ];
  if (replay.monthly15) series.push({id:"monthly15_drawdown",label:replay.monthly15.label,color:"#7c3aed",max_drawdown:0});
  const states=aligned.series.map(s=>{
    const definition=definitions.find(d=>d.id===s.id);
    // Include every benchmark quote in the window, including dates when the
    // strategy has no session. A hidden intervening peak still affects drawdown.
    const rows=[{date:start,value:s.anchor_value},...cleanPrices(definition.rows,start,end).filter(r=>r.date>start)];
    const summary={id:`${s.id}_drawdown`,label:s.label,color:s.color,max_drawdown:0};
    series.push(summary);
    return {rows,summary,cursor:-1,peak:s.anchor_value,last:null,drawdown:0,maxAgeDays:definition.maxAgeDays ?? maxAgeDays,end:rows[rows.length-1].date};
  });
  let peak=path[0].nav_toman,basePeak=path[0].baseline_toman,monthlyPeak=path[0].monthly15_toman;
  const points=path.map(p=>{
    peak=Math.max(peak,p.nav_toman);basePeak=Math.max(basePeak,p.baseline_toman);
    const dd=p.nav_toman/peak-1,baseDD=p.baseline_toman/basePeak-1;
    series[0].max_drawdown=Math.min(series[0].max_drawdown,dd);
    series[1].max_drawdown=Math.min(series[1].max_drawdown,baseDD);
    const result={date:p.date,drawdown:dd,baseline_drawdown:baseDD};
    if (replay.monthly15) {
      monthlyPeak=Math.max(monthlyPeak,p.monthly15_toman);
      result.monthly15_drawdown=p.monthly15_toman/monthlyPeak-1;
      series[2].max_drawdown=Math.min(series[2].max_drawdown,result.monthly15_drawdown);
    }
    for (const state of states) {
      while (state.cursor+1<state.rows.length && state.rows[state.cursor+1].date<=p.date) {
        const quote=state.rows[++state.cursor];state.last=quote;
        state.peak=Math.max(state.peak,quote.value);state.drawdown=quote.value/state.peak-1;
        state.summary.max_drawdown=Math.min(state.summary.max_drawdown,state.drawdown);
      }
      const age=state.last ? (Date.parse(p.date+"T12:00:00Z")-Date.parse(state.last.date+"T12:00:00Z"))/86_400_000 : Infinity;
      result[state.summary.id]=age>=0 && age<=state.maxAgeDays && p.date<=state.end ? state.drawdown : null;
    }
    return result;
  });
  return {points,series,start,end};
}

// Convert family Jalali keys through the same Persian calendar used by the UI.
export function familyHistoryPrices(history) {
  const formatter = new Intl.DateTimeFormat("en-US-u-ca-persian", {year:"numeric",month:"2-digit",day:"2-digit",timeZone:"UTC"});
  const keyAt = time => {
    const parts = Object.fromEntries(formatter.formatToParts(new Date(time)).map(p=>[p.type,p.value]));
    return `${parts.year}/${parts.month}/${parts.day}`;
  };
  const byDate = new Map();
  for (const row of history) {
    if (row.has_total !== true || !finite(row.total) || row.total<=0) continue;
    const key=String(row.date_key).replace(/[۰-۹]/g,c=>String("۰۱۲۳۴۵۶۷۸۹".indexOf(c))).replace(/[٠-٩]/g,c=>String("٠١٢٣٤٥٦٧٨٩".indexOf(c)));
    if (!/^1[34]\d{2}\/\d{2}\/\d{2}$/.test(key)) continue;
    const year=Number(key.slice(0,4));
    let lo=Date.UTC(year+621,0,1)/86400000,hi=Date.UTC(year+622,3,1)/86400000;
    while (lo<hi) {
      const mid=Math.floor((lo+hi)/2);
      if(keyAt(mid*86400000)<key) lo=mid+1; else hi=mid;
    }
    if (keyAt(lo*86400000)!==key) continue;
    const date=new Date(lo*86400000).toISOString().slice(0,10);
    byDate.set(date,{date,closing_price:row.total});
  }
  return [...byDate.values()].sort((a,b)=>a.date.localeCompare(b.date));
}
