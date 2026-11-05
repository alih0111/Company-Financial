import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/utils/qvtRatio.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const mod = { exports: {} };
vm.runInNewContext(compiled, { exports: mod.exports, module: mod });
const { formatQvtRatio } = mod.exports;

test("comparison tolerates missing ratios and preserves available values", () => {
  assert.equal(formatQvtRatio(undefined), "—");
  assert.equal(formatQvtRatio({ raw_value: null }), "—");
  assert.equal(formatQvtRatio({ raw_value: 3.26, peer_rank: 2, n_peers: 10 }), "3.3 (#2/10)");
});
