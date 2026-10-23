import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import vm from "node:vm";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const source = readFileSync(new URL("../src/utils/safeCsv.ts", import.meta.url), "utf8");
const compiled = ts.transpileModule(source, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const mod = { exports: {} };
vm.runInNewContext(compiled, { exports: mod.exports, module: mod, require });
const { safeCsvCell, serializeCsv } = mod.exports;

test("CSV starts with UTF-8 BOM and quotes Persian text", () => {
  const csv = serializeCsv([{ ticker: "غگیلا" }], [["نماد", "ticker"]]);
  assert.equal(csv.charCodeAt(0), 0xfeff);
  assert.match(csv, /"نماد"\r\n"غگیلا"/);
});

test("formula-like text is prefixed safely", () => {
  assert.equal(safeCsvCell("=SUM(A1:A2)"), `"'=SUM(A1:A2)"`);
  assert.equal(safeCsvCell("  @cmd"), `"'  @cmd"`);
  assert.equal(safeCsvCell("-cmd|'/C calc"), `"'-cmd|'/C calc"`);
});

test("negative numeric values remain numeric and unchanged", () => {
  assert.equal(safeCsvCell(-123.5), `"-123.5"`);
  assert.equal(safeCsvCell("-123.5"), `"-123.5"`);
  assert.equal(safeCsvCell("-1+2"), `"'-1+2"`);
});
