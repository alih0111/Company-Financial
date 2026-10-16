import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import { createRequire } from 'node:module';

// Render the actual component without changing the authenticated app or live JSON.
const require = createRequire(import.meta.url);
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { MemoryRouter } = require('react-router-dom');
const generated = path.resolve('node_modules/.cache/return-v4-render.cjs');
await build({ entryPoints: ['src/components/ResearchRankingPage.tsx'], outfile: generated,
  bundle: true, platform: 'node', format: 'cjs', packages: 'external', jsx: 'automatic',
  define: { 'import.meta.env.BASE_URL': '"/"' }, logLevel: 'error' });
{
  const { ResearchRankingView } = require(generated);
  const normal = JSON.parse(fs.readFileSync('public/research/return-v4.json', 'utf8'));
  const cases = {
    normal,
    partial: { ...normal, eligible_count: 2, rows: normal.rows.slice(0, 2) },
    empty: { ...normal, status: 'unavailable', eligible_count: 0, rows: [], reason: 'دادهٔ کافی وجود ندارد' },
  };
  const results = [];
  for (const [name, data] of Object.entries(cases)) {
    const html = renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(ResearchRankingView, { data })));
    assert(html.includes('رتبه‌بندی نمادهای دارای دادهٔ کافی'));
    assert(html.includes('این فهرست، رتبه‌بندی امروز نیست'));
    assert(html.includes('۲۵۴'));
    if (name === 'empty') assert(html.includes('نامزد معتبری برای نمایش وجود ندارد'));
    else assert(html.includes(data.rows[0].symbol));
    if (name === 'partial') assert(!html.includes(normal.rows[2].symbol));
    results.push({ state: name, passed: true, displayed_rows: data.rows.length });
  }
  const target = path.resolve('../docs/artifacts/return_v4_frontend_states.json');
  fs.writeFileSync(target, JSON.stringify({ checked_at: new Date().toISOString(), run_id: normal.run_id, component: 'ResearchRankingView', actual_component_ssr: true, cases: results }, null, 2));
  console.log(JSON.stringify(results));
}
