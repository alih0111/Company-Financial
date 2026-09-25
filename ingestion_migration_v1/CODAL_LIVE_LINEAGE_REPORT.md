# CODAL LIVE LINEAGE REPORT — Phase 3

## 1. Wiring

`canonical_hook.dual_write_codal_letter(letter)`:
- `source_report_id = str(letter["TracingNo"])` (Codal TracingNo)
- resolves Company/Security via `canonical_ingest.identity` (no name-hash)
- fetches the real report URL body and stores it in `raw.report_payloads`
  (`payload_type=html`, source/URL/hash/bytes/`collected_at`)
- writes `ingestion.reports` → `ingestion.report_versions` → `ingestion.parse_runs`
- unresolved identity → `quarantined` + DQ row; no fabrication.

## 2. Live letters observed (search API reachable)

| TracingNo | Company | Symbol | Resolved |
| --- | --- | --- | --- |
| 1603147 | تولیدی حسنانو | زشک | no |
| 1602429 | کیمیا پلی استر قم | شکیمیا | no |
| 1602865 | سازه پوشش ماموت | فساپ | no |
| 1602820 | صندوق … توسعه بازار تمدن | توسعه تمدن بازار | no |
| 1602848 | مختص اوراق دولتی کاردان | کاردان دولتی | no |

All sampled letters correctly **quarantine**: they are outside the canonical
migrated universe or require alias mapping (`شکیمیا` is a known legacy-only
scope exclusion; funds are out of scope). This is correct identity behavior, not
a lineage defect.

## 3. Controlled lineage proofs (resolvable identity `آردینه`)

`output/codal_lineage_probe.json`:

| Case | Result |
| --- | --- |
| identical content re-fetch (same TracingNo) | `inserted=0` → no new report_version |
| changed source content | new `version_no=2` |
| parser rerun (same content, new parser_version) | new `parse_run`, `versions` stays 2 |
| raw payload dedup | 2 raw payloads for 2 versions (identical content stored once) |

Totals after proofs: `versions=2`, `max_version_no=2`, `raw_payloads=2`,
`parse_runs=3`, `parser_rerun_new_parse_run=true`.

## 4. Version semantics contract (verified)

- same TracingNo + identical content → **no** new report_version.
- same report + changed content → **new** report_version (version_no increment).
- parser rerun → new parse_run, no fake source version.
- official corrected reports (distinct TracingNo) use `supersedes_report_id`
  (canonical supersession); no fabrication.

## 5. Raw payload validation

For controlled fetches: `content_hash` stable and deduplicated per
`(report_version_id, payload_type, content_hash)`; byte size and mime recorded;
no secrets/session material persisted (only report body/metadata). Historical
raw payloads were **not** fabricated.

## 6. Status

Live lineage is **wired**; live letters quarantine by identity as designed;
version/raw/parser semantics are proven. This is explicitly **non-blocking** for
market/monthly/financial soak, and no Codal scope blocked Phase 3.
