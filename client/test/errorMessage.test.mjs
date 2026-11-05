import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/utils/errorMessage.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const mod = { exports: {} };
vm.runInNewContext(compiled, { exports: mod.exports, module: mod });
const { errorMessage } = mod.exports;

test("error messages preserve string messages and use fallback for other values", () => {
  assert.equal(errorMessage(new Error("network"), "fallback"), "network");
  assert.equal(errorMessage({ message: "detail" }, "fallback"), "detail");
  assert.equal(errorMessage({ message: "" }, "fallback"), "fallback");
  assert.equal(errorMessage({ message: 42 }, "fallback"), "fallback");
  assert.equal(errorMessage(null, "fallback"), "fallback");
});
