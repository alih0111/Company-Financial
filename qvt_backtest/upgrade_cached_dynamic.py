"""Apply v2's explicit parent-sheet/page-unit evidence to saved v1 sources."""
import hashlib
import json
import collect_financial_history as H
import dynamic_financial as D


def main():
    recovered, rejected = [], []
    catalog = H.C.read(H.OUT / "catalog_versions.json")
    for row in catalog:
        path = H.OUT / "reports" / f"{row['company_id']}_{row['letter']['TracingNo']}.json"
        if not path.exists():
            continue
        rec = H.load_archived_report(path)
        if rec.get("parser_version") != "codal-dynamic-source-v1":
            continue
        new = {**rec, "parser_version": D.VERSION, "original_record_sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        facts = D.own_facts(D.verified_parsed(new))
        old_values = {(f["statement_type"], f["metric_code"]): f["value"] for f in rec["facts"]}
        new_values = {(f["statement_type"], f["metric_code"]): f["value"] for f in facts}
        if any(new_values.get(k) != v for k, v in old_values.items()):
            rejected.append(rec["tracing_no"])
            continue
        if len(facts) > len(rec["facts"]):
            new["facts"] = facts
            H.C.write(H.OUT / "recovered_reports" / path.name, new)
            recovered.append({"symbol": rec["symbol"], "tracing_no": rec["tracing_no"], "added_facts": len(facts) - len(rec["facts"])})
    H.C.write(D.STORE / "v2_upgrade.json", {"upgraded": recovered, "conflicts": rejected, "originals_changed": False})
    print(json.dumps({"upgraded": recovered, "conflicts": rejected}, ensure_ascii=False))


if __name__ == "__main__":
    main()
