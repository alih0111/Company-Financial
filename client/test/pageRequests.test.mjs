import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { build } from "esbuild";
import React, { act } from "react";
import { create } from "react-test-renderer";
import { MemoryRouter, useNavigate } from "react-router-dom";
import test, { afterEach } from "node:test";

// Keep the real router, data hooks, sidebar, freshness badge and captcha watcher.
// Only page bodies/charts and the DOM-based selector are replaced for this test.
const pageBodies = new Set([
  "Landing", "Login", "Register", "BigDataTable", "Portfolio", "FamilyAssets",
  "ChatPage", "MarketPage", "ComparePage", "WatchlistPage", "RankingHubPage",
  "FactorMixPage", "MonthlyFactorMixPage", "ReportFlowPage", "StrategyPerformancePage", "FinancialStatements",
  "DataUsageNotice", "StrategySummary", "DataAccessAdmin", "ChartComponent", "PriceChart", "ScoreBreakdown", "DonutChartComponent", "AppHeader",
]);
const generated = new URL(".generated/", import.meta.url);
await mkdir(generated, { recursive: true });
await build({
  stdin: {
    contents: 'export {default as App} from "./src/App"; export {cachedResource} from "./src/utils/cachedResource"; export {refreshSession} from "./src/hooks/useGetUser";',
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  outfile: fileURLToPath(new URL("pageRequests.mjs", generated)),
  bundle: true, format: "esm", platform: "node", packages: "external", jsx: "automatic",
  define: { "import.meta.env": '{"BASE_URL":"/","DEV":false}' },
  plugins: [{ name: "page-bodies", setup(builder) {
    builder.onLoad({ filter: /[\\/]components[\\/][^\\/]+\.tsx$/ }, ({ path }) => {
      const name = path.split(/[\\/]/).pop().replace(/\.tsx$/, "");
      if (name === "PriceChart") return { contents: 'import {useEffect} from "react"; export default function PriceChart({companyName,refreshTick}){useEffect(()=>{globalThis.__chartLoads.push(companyName)},[companyName,refreshTick]);return null}' };
      if (pageBodies.has(name)) return { contents: `export default function ${name}(){return null}` };
    });
    builder.onResolve({ filter: /^react-select$/ }, () => ({ path: "select", namespace: "test" }));
    builder.onLoad({ filter: /.*/, namespace: "test" }, () => ({
      contents: 'export default function Select(){return null}',
    }));
  } }],
});
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

let renderer;
let navigate;
let requests;
let timers;
let nextTimer;
let winEvents;
let docEvents;
let session = 0;
setup();
const { App, cachedResource, refreshSession } = await import(new URL("pageRequests.mjs", generated));

await build({
  stdin: {
    contents: 'export {default as Portfolio} from "./src/components/Portfolio"; export {default as FamilyAssets} from "./src/components/FamilyAssets"; export {default as ResearchHomePage} from "./src/components/ResearchHomePage"; export {ToastProvider} from "./src/components/Toast"; export {ConfirmProvider} from "./src/components/ConfirmDialog";',
    resolveDir: fileURLToPath(new URL("../", import.meta.url)),
  },
  outfile: fileURLToPath(new URL("tabRequests.mjs", generated)),
  bundle: true, format: "esm", platform: "node", packages: "external", jsx: "automatic",
  define: { "import.meta.env": '{"BASE_URL":"/","DEV":false}' },
  plugins: [{ name: "chart-widgets", setup(builder) {
    builder.onLoad({ filter: /[\\/](MarketPulseCards|LatestLockedRanking|PaperTrialPanel)\.tsx$/ }, () => ({ contents: "export default function Widget(){return null}" }));
    builder.onResolve({ filter: /^(react-select|recharts)$/ }, ({ path }) => ({ path, namespace: "test" }));
    builder.onLoad({ filter: /.*/, namespace: "test" }, ({ path }) => ({ contents: path === "react-select"
      ? "export default function Select(){return null}"
      : `function Chart(){return null} export {${["Area", "AreaChart", "CartesianGrid", "ComposedChart", "Line", "ResponsiveContainer", "Tooltip", "XAxis", "YAxis", "PieChart", "Pie", "Cell", "Legend", "Label"].map((name) => `Chart as ${name}`).join(",")}}`,
    }));
  } }],
});
const { Portfolio, FamilyAssets, ResearchHomePage, ToastProvider, ConfirmProvider } = await import(new URL("tabRequests.mjs", generated));

function setup({ admin = false, authenticated = true, respond } = {}) {
  session++;
  const storage = new Map();
  globalThis.localStorage = {
    getItem: (key) => storage.get(key) ?? null,
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  };
  requests = [];
  globalThis.__chartLoads = [];
  timers = new Map();
  nextTimer = 0;
  winEvents = new EventTarget();
  docEvents = new EventTarget();
  globalThis.window = {
    location: { origin: "http://localhost", pathname: "/", search: "" },
    matchMedia: () => ({ matches: false }),
    addEventListener: winEvents.addEventListener.bind(winEvents),
    removeEventListener: winEvents.removeEventListener.bind(winEvents),
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearTimeout: (id) => timers.delete(id),
    setInterval: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearInterval: (id) => timers.delete(id),
  };
  globalThis.document = {
    title: "", visibilityState: "visible", body: null,
    documentElement: { classList: { toggle() {} } },
    addEventListener: docEvents.addEventListener.bind(docEvents),
    removeEventListener: docEvents.removeEventListener.bind(docEvents),
  };
  globalThis.fetch = async (input, init) => {
    const url = new URL(String(input), window.location.origin);
    requests.push({ path: url.pathname, url, signal: init?.signal });
    if (url.pathname.endsWith("/me")) return authenticated
      ? Response.json({ username: `test-${session}`, isAdmin: admin })
      : new Response(null, { status: 401 });
    if (respond) {
      const result = respond(url, init);
      if (result) return result;
    }
    const data = url.pathname.endsWith("/CompanyNames") ? ["فولاد", "فملی"]
      : url.pathname.endsWith("/AllCompanyScores") ? [{ company_id: "1", company_name: "فولاد", eps_growth: 20 }]
      : url.pathname.endsWith("/summary") ? [{ company_id: "1", company_name: "فولاد", quant_score: 60 }]
      : url.pathname.endsWith("/active") ? { job: null }
      : url.pathname.endsWith("/shadow") ? {}
      : [];
    return Response.json(data);
  };
}

async function flush() {
  await act(async () => { await new Promise((resolve) => setImmediate(resolve)); });
}
async function mount(path) {
  await refreshSession();
  requests = [];
  function RouterControls() { navigate = useNavigate(); return null; }
  await act(async () => {
    renderer = create(React.createElement(React.StrictMode, null,
      React.createElement(MemoryRouter, { initialEntries: [path] },
        React.createElement(RouterControls), React.createElement(App))));
  });
  await flush();
}
async function go(path) { await act(async () => { await navigate(path); }); await flush(); }
async function mountContent(Component, path = "/") {
  await act(async () => {
    renderer = create(React.createElement(MemoryRouter, { initialEntries: [path] },
      React.createElement(ToastProvider, null,
        React.createElement(ConfirmProvider, null, React.createElement(Component)))));
  });
  await flush();
}
function textContent(node) { return node.children.map((child) => typeof child === "string" ? child : textContent(child)).join(""); }
async function click(label) {
  const button = renderer.root.findAllByType("button").find((node) => textContent(node).includes(label));
  assert.ok(button, `button '${label}' exists`);
  await act(async () => button.props.onClick());
  await flush();
}
const count = (suffix) => requests.filter((request) => request.path.endsWith(suffix)).length;
const paths = () => [...new Set(requests.map((request) => request.path))].sort();
const sidebar = () => renderer.root.find((node) => node.type?.name === "Sidebar");
afterEach(async () => { if (renderer) await act(async () => renderer.unmount()); renderer = null; });

test("dashboard requests company charts and displayed metrics, without unused score endpoints", async () => {
  setup();
  await mount("/dashboard?companyname=فولاد");
  assert.deepEqual(paths(), ["/api/CompanyNames", "/api/SalesData", "/api/SalesData2", "/api/health/shadow", "/api/summary"]);
  assert.equal(count("/CompanyNames"), 1, "StrictMode shares the in-flight names request");
  requests = [];
  await go("/dashboard?companyname=فملی");
  assert.deepEqual(paths(), ["/api/SalesData", "/api/SalesData2", "/api/summary"]);
  assert.ok(requests.every((request) => request.url.searchParams.get("companyName") === "فملی"));
});

test("market screener requests only a server page and never downloads all scores",async()=>{
  setup({respond(url){if(url.pathname==="/api/summary")return Response.json([{company_id:"1",company_name:"فولاد",symbol:"فولاد",quant_score:60}],{headers:{"X-Total-Count":"100"}});}});
  await mount("/Table");
  assert.deepEqual(paths(),["/api/health/shadow","/api/summary"]);
  assert.equal(count("/AllCompanyScores"),0);
  assert.equal(requests.find(r=>r.path.endsWith("/summary")).url.searchParams.get("page_size"),"20");
  requests=[];await click("بعدی");
  assert.equal(count("/summary"),1);
  assert.equal(requests[0].url.searchParams.get("page"),"2");
  assert.equal(count("/SalesData"),0);
});

test("dashboard shows data-service failures and retry recovers the company selection", async () => {
  let unavailable = true;
  setup({ respond(url) {
    if (unavailable && ["/api/CompanyNames", "/api/summary"].includes(url.pathname)) {
      return Response.json({ error: "service unavailable" }, { status: 503 });
    }
  } });
  await mount("/dashboard");
  const alert = renderer.root.findByProps({ role: "alert" });
  assert.ok(textContent(alert).includes("دریافت فهرست شرکت‌ها انجام نشد"));
  assert.equal(sidebar().props.selectedCompany, "");
  requests = [];
  unavailable = false;
  await click("تلاش دوباره");
  assert.equal(sidebar().props.selectedCompany, "فولاد");
  assert.equal(count("/CompanyNames"), 1);
  assert.equal(renderer.root.findAllByProps({ role: "alert" }).length, 0);
  assert.equal(count("/AllCompanyScores"), 0);
});

test("unrelated and unknown routes do not request root company/score data", async () => {
  setup({ admin: false });
  await mount("/chat");
  for (const path of ["/strategy", "/strategy/history", "/strategy/reportflow", "/strategy/performance", "/ranking", "/ranking/research", "/ranking/legacy-cash", "/ranking/research/v12-1", "/qvt", "/portfolio", "/market", "/compare", "/watchlist", "/not-found"]) {
    await go(path);
  }
  assert.deepEqual(paths(), []);
  assert.equal(timers.size, 0, "no global score refresh timers remain on these pages");
});

test("company search and profit review load only when opened", async () => {
  setup();
  await mount("/chat");
  await act(async () => sidebar().props.onCompanySearchOpen());
  await flush();
  assert.deepEqual(paths(), ["/api/CompanyNames"]);
  requests = [];
  await act(async () => sidebar().props.onProfitReviewToggle());
  await flush();
  assert.deepEqual(paths(), [], "profit review opens the paged market link without downloading a full dataset");
  requests = [];
  await act(async () => sidebar().props.onProfitReviewToggle());
  await act(async () => sidebar().props.onProfitReviewToggle());
  await flush();
  assert.deepEqual(paths(), [], "reopening uses the cached market scores");
});

test("leaving dashboard cancels company requests and removes score refresh listeners", async () => {
  setup();
  await mount("/dashboard?companyname=فولاد");
  const companyRequests = requests.filter((request) => request.path.includes("SalesData"));
  await go("/chat");
  assert.ok(companyRequests.every((request) => request.signal.aborted));
  requests = [];
  await act(async () => { winEvents.dispatchEvent(new Event("focus")); docEvents.dispatchEvent(new Event("visibilitychange")); });
  assert.deepEqual(paths(), []);
  assert.equal(timers.size, 0);
});

test("unauthenticated protected routes do not start data requests", async () => {
  setup({ authenticated: false });
  await mount("/dashboard?companyname=فولاد");
  for (const path of ["/", "/login", "/register"]) await go(path);
  assert.deepEqual(paths(), []);
});

test("admin has one captcha discovery poller, with slower idle polling", async () => {
  setup({ admin: true });
  await mount("/chat");
  assert.deepEqual(paths(), ["/api/sync-codal/jobs/active"]);
  assert.equal(timers.size, 1, "sidebar must not create a second poller");
  assert.equal([...timers.values()][0].delay, 30_000);
  requests = [];
  document.visibilityState = "hidden";
  const [id, timer] = [...timers][0];
  timers.delete(id);
  await act(async () => timer.callback());
  assert.deepEqual(paths(), [], "hidden tabs do not poll");
});

test("family assets page has no root company or market-score requests", async () => {
  setup({ admin: true });
  await mount("/assets");
  assert.deepEqual(paths(), ["/api/sync-codal/jobs/active"]);
});

test("cached reads share pending work, respect session boundaries, and invalidate safely", async () => {
  let resolve;
  let loads = 0;
  const resource = cachedResource(() => { loads++; return new Promise((done) => { resolve = done; }); }, 60_000);
  const first = resource.load("a");
  const resolveFirst = resolve;
  assert.equal(resource.load("a"), first);
  resource.invalidate();
  const second = resource.load("a");
  const resolveSecond = resolve;
  resolveSecond(2);
  assert.equal(await second, 2);
  resolveFirst(1);
  await first;
  assert.equal(await resource.load("a"), 2);
  const third = resource.load("b");
  resolve(3);
  assert.equal(await third, 3);
  assert.equal(loads, 3);
});

test("failed and expired cached reads are retried", async () => {
  let loads = 0;
  const resource = cachedResource(async () => {
    if (++loads === 1) throw new Error("temporarily unavailable");
    return loads;
  }, 0);
  await assert.rejects(resource.load("a"), /temporarily unavailable/);
  assert.equal(await resource.load("a"), 2);
  assert.equal(await resource.load("a"), 3);
});

test("focus and visibility events do not duplicate freshness requests", async () => {
  setup();
  await mount("/dashboard?companyname=فولاد");
  requests = [];
  await act(async () => {
    winEvents.dispatchEvent(new Event("focus"));
    docEvents.dispatchEvent(new Event("visibilitychange"));
  });
  assert.deepEqual(paths(), []);
  await act(async () => winEvents.dispatchEvent(new Event("rfa:score-refreshed")));
  await flush();
  assert.deepEqual(paths(), ["/api/health/shadow"]);
});

test("loading company fundamentals keeps the price chart mounted", async () => {
  const deferred = [];
  setup({ respond(url) {
    if (url.pathname.includes("SalesData")) return new Promise((resolve) => deferred.push(resolve));
  } });
  await mount("/dashboard?companyname=فولاد");
  const loadsBefore = globalThis.__chartLoads.length;
  assert.ok(loadsBefore > 0);
  await act(async () => { deferred.forEach((resolve) => resolve(Response.json([{ x: "2026-01-01", y: 1 }]))); });
  await flush();
  assert.equal(globalThis.__chartLoads.length, loadsBefore, "chart must not remount after profit and sales finish loading");
  await act(async () => sidebar().props.onDataCollected());
  assert.equal(globalThis.__chartLoads.length, loadsBefore + 1);
  await act(async () => { deferred.forEach((resolve) => resolve(Response.json([{ x: "2026-01-01", y: 1 }]))); });
  await flush();
  assert.equal(globalThis.__chartLoads.length, loadsBefore + 1, "manual refresh must request chart data only once");
});

test("portfolio requests market metrics only when the add form opens", async () => {
  setup({ respond(url) { if (url.pathname === "/api/portfolio") return Response.json({ holdings: [] }); } });
  await mountContent(Portfolio);
  assert.deepEqual(paths(), ["/api/portfolio"]);
  requests = [];
  await click("افزودن دارایی");
  assert.deepEqual(paths(), ["/api/companies"]);
});

test("editing a portfolio holding keeps its company label without loading all market metrics", async () => {
  setup({ respond(url) {
    if (url.pathname === "/api/portfolio") return Response.json({ holdings: [{
      company_id: "1", company_name: "فولاد", symbol: "فولاد", quantity: 10,
      buy_price: 100, market_value: 1000, gain: 0, gain_pct: 0, weight: 100,
    }] });
  } });
  await mountContent(Portfolio);
  requests = [];
  await act(async () => renderer.root.findByProps({ title: "ویرایش" }).props.onClick());
  const select = renderer.root.find((node) => node.type?.name === "Select");
  assert.equal(select.props.value.value, "1");
  assert.ok(select.props.value.label.includes("فولاد"));
  assert.deepEqual(paths(), []);
});

test("family cashflows and brokerage are fetched only in their tabs", async () => {
  setup({ respond(url) {
    if (url.pathname === "/api/family/assets") return Response.json({ today_datekey: "1405-08-16", assets: [], people: [], summary: {} });
  } });
  await mountContent(FamilyAssets);
  assert.deepEqual(paths(), ["/api/family/assets", "/api/family/history"]);
  requests = [];
  await click("آورده / برداشت");
  assert.deepEqual(paths(), ["/api/family/cashflows"]);
  requests = [];
  await click("کارگزاری آگاه");
  assert.deepEqual(paths(), ["/api/family/broker"]);
});

for (const view of ["paper", "archive"]) {
  test(`research ${view} tab skips contract, readiness and ledger downloads`, async () => {
    setup();
    await mountContent(ResearchHomePage, `/ranking?view=${view}`);
    assert.deepEqual(paths(), []);
  });
}
