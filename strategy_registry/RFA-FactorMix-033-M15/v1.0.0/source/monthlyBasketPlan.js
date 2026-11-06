export const monthlyStrategyId = "RFA-FactorMix-033-M15-Buffer8-v1.0.0";
export const normalizeSymbol = value => String(value).replace(/ي/g,"ی").replace(/ك/g,"ک").replace(/\s|\u200c/g,"");
export function parseToman(value) {
  const text = String(value).replace(/[۰-۹]/g,c=>String("۰۱۲۳۴۵۶۷۸۹".indexOf(c)))
    .replace(/[٠-٩]/g,c=>String("٠١٢٣٤٥٦٧٨٩".indexOf(c))).replace(/[,٬\s]/g,"").replace(/٫/g,".");
  return text === "" ? NaN : Number(text);
}

/** Read-only target proposal, using the registered buffer and weight band. */
export function monthlyBasketPlan(ranking, holdings, cash) {
  if (!ranking || !Array.isArray(ranking.rows) || !Number.isFinite(cash) || cash < 0) throw new Error("مقدار نقد معتبر به تومان وارد کنید.");
  const symbols = new Map(ranking.rows.map(r=>[normalizeSymbol(r.symbol),r]));
  const values = new Map();
  for (const h of holdings) {
    const row = symbols.get(normalizeSymbol(h.symbol));
    if (!row) throw new Error(`نماد «${h.symbol}» در جهان این مدل نیست؛ نام را بررسی کنید.`);
    if (values.has(row.symbol)) throw new Error(`نماد ${row.symbol} تکراری است.`);
    if (!Number.isFinite(h.value_toman) || h.value_toman <= 0) throw new Error("ارزش روز هر دارایی باید بیشتر از صفر باشد.");
    values.set(row.symbol,h.value_toman);
  }
  const nav = cash + [...values.values()].reduce((a,b)=>a+b,0);
  if (!Number.isFinite(nav) || nav <= 0) throw new Error("ارزش دارایی و نقد باید بیشتر از صفر باشد.");
  const eligible = ranking.rows.filter(r=>Number.isInteger(r.rank) && r.rank > 0 && Number.isFinite(r.score) && !r.reason).sort((a,b)=>a.rank-b.rank);
  if (!eligible.length) throw new Error("هیچ نماد واجد شرایطی در رتبه‌بندی نیست؛ ابتدا اطلاعات و امتیازها را بررسی کنید.");
  const selected = eligible.filter(r=>values.has(r.symbol) && r.rank <= 8).slice(0,5);
  for (const row of eligible) {
    if (selected.length >= 5) break;
    if (!selected.some(s=>s.symbol === row.symbol)) selected.push(row);
  }
  const targets = new Set(selected.map(r=>r.symbol));
  const ordered = [...selected, ...ranking.rows.filter(r=>values.has(r.symbol) && !targets.has(r.symbol))];
  const rows = ordered.map(r=>{
    const current = values.get(r.symbol) ?? 0;
    const target = targets.has(r.symbol) ? .2 : 0;
    const needed = (current > 0 && target === 0) || (target > 0 && (current === 0 || Math.abs(current/nav-target) > .05 + 1e-12));
    const delta = needed ? target*nav-current : 0;
    return {symbol:r.symbol,rank:r.rank,current_toman:current,current_weight:current/nav,target_weight:target,
      target_toman:target*nav,delta_toman:delta,action:delta > 0 ? "BUY" : delta < 0 ? "SELL" : "HOLD",
      reason:target === 0 ? "خارج از سبد هدف یا فاقد شرایط" : current === 0 ? "ورود برای پرکردن جای خالی" : needed ? "تنظیم انحراف بیش از ۵ واحد درصد" : "نگهداری در محدودهٔ مجاز"};
  });
  return {strategy_id:monthlyStrategyId,ranking_date:ranking.date,ranking_computed_at_utc:ranking.computed_at_utc,
    market_date:ranking.market_date,nav_toman:nav,cash_toman:cash,rows,
    changes:rows.filter(r=>r.action !== "HOLD").length,missing_slots:5-selected.length,
    amounts_before_costs:true,executed:false};
}
