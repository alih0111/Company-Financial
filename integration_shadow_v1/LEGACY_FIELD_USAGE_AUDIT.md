# LEGACY FIELD USAGE AUDIT

Scope: the legacy-only `SalesData` (income statement) and `SalesData2` (monthly
activity) API payloads versus the actual React client in `client/src`.
Method: exhaustive text search of `client/src` for each JSON field name and its
consumers, then tracing the two response arrays (`data1`, `data2`) through
`useCompanyData.ts` → `App.tsx` → `ChartComponent`.

Endpoint contracts (Go `models.SalesData` / `models.SalesData2`):

```
SalesData  : companyName, companyID, reportDate, Product1, Product2, Product3, percentage, wow
SalesData2 : companyName, companyID, reportDate, value1, value2, value3, percentage, wow
```

## Classification

| Field | Endpoint | Classification | Evidence |
| --- | --- | --- | --- |
| `Product1` | SalesData | **CLIENT_UNUSED** | zero references in `client/src` |
| `Product2` | SalesData | **CLIENT_UNUSED** | zero references in `client/src` |
| `Product3` | SalesData | **CLIENT_UNUSED** | zero references in `client/src` |
| `companyID` | SalesData | **CLIENT_UNUSED** | not read from `data1` |
| `companyName` | SalesData | **REQUIRED_BY_ACTIVE_UI** | `useCompanyData.ts:256,258,261` (`data1[0].companyName` → `openModalForScript`/`GetUrl`) |
| `reportDate` | SalesData | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx:152` (`dataKey="reportDate"`, `CustomTooltip`) |
| `percentage` | SalesData | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx:32,47,79,92,103,196,212` |
| `wow` | SalesData | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx:73-80,208-214` (bar colour) |
| `value1` | SalesData2 | **CLIENT_UNUSED** | not read from `data2` |
| `value2` | SalesData2 | **CLIENT_UNUSED** | not read from `data2` |
| `value3` | SalesData2 | **CLIENT_UNUSED** | not read from `data2` |
| `companyID` | SalesData2 | **CLIENT_UNUSED** | not read from `data2` |
| `companyName` | SalesData2 | **CLIENT_UNUSED** | `data2` is passed only to `ChartComponent` |
| `reportDate` | SalesData2 | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx:152` |
| `percentage` | SalesData2 | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx` bar values |
| `wow` | SalesData2 | **REQUIRED_BY_ACTIVE_UI** | `ChartComponent.tsx` bar colour |

No field is `REQUIRED_BY_ACTIVE_CALCULATION` in the client: all arithmetic is done
server-side in Go.

## Key finding

`Product1/2/3` are **CLIENT_UNUSED**. They are legacy derived mixed-scale
heuristics (`Product1 = EPS_current × Capital`, `Product2 = EPS_prior_year ×
Capital`, `Product3 = EPS_prior_fiscal × Capital`) with **no canonical factual
equivalent**. The client only consumes the server-derived presentation fields:

- `percentage` (SalesData: `Product1 / 1_000_000`; SalesData2: `Value3` scaled),
- `wow` (sign relationship between the three legacy values).

Therefore the future canonical contract may **omit `Product1/2/3`** (and
`value1/2/3`) while preserving `percentage`, `wow` and `reportDate` at the API
boundary. Those two derived presentation fields are the only true compatibility
requirement; they must be produced from canonical data without reintroducing the
banned heuristics into canonical storage.

## Consequences

- `LEGACY_ONLY_FIELD`: `Product1`, `Product2`, `Product3` (and `SalesData2`
  `value1/2/3`) may be dropped once the derived `percentage`/`wow` are defined at
  the canonical boundary.
- Do **not** recreate `Product1/2/3` in canonical tables or analytics.
- The shadow comparison intentionally does not compare `Product1/2/3`
  (`integration` guard test `TestGuardNoLegacyHeuristics`).
- A compatibility decision on how to derive `percentage`/`wow` canonically is
  required before a `SalesData`/`SalesData2` canonical cutover; until then the
  legacy response remains authoritative (LEGACY/SHADOW).
