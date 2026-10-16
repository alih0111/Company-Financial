import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';
const require=createRequire(import.meta.url);
const React=require('react');
const {renderToStaticMarkup}=require('react-dom/server');
const {MemoryRouter}=require('react-router-dom');
const generated=path.resolve('node_modules/.cache/return-v6-render.cjs');
await build({entryPoints:['src/components/ResearchRankingPage.tsx'],outfile:generated,bundle:true,platform:'node',format:'cjs',packages:'external',jsx:'automatic',define:{'import.meta.env.BASE_URL':'"/"'},logLevel:'error'});
const {ResearchRankingView}=require(generated);
const normal=JSON.parse(fs.readFileSync('public/research/return-v6.json','utf8'));
const cases={normal,partial:{...normal,eligible_count:2,rows:normal.rows.slice(0,2)},empty:{...normal,status:'unavailable',eligible_count:0,rows:[]}};
const result=[];
for(const [state,data] of Object.entries(cases)){
 const html=renderToStaticMarkup(React.createElement(MemoryRouter,null,React.createElement(ResearchRankingView,{data})));
 assert(html.includes('NAV'));assert(html.includes('افت بیشینه'));assert(html.includes('اطلاعات بنیاد در زمان تصمیم'));
 assert(html.includes('این فهرست، رتبه‌بندی امروز نیست'));
 if(state==='empty')assert(html.includes('نامزد معتبری برای نمایش وجود ندارد'));
 else assert(html.includes(data.rows[0].symbol));
 if(state==='partial')assert(!html.includes(normal.rows[2].symbol));
 result.push({state,passed:true,rows:data.rows.length});
}
fs.writeFileSync(path.join(process.argv[2],'frontend_states.json'),JSON.stringify({run_id:normal.run_id,actual_component_ssr:true,cases:result},null,2));
console.log(JSON.stringify(result));
