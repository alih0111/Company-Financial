"""Read-only export of existing dated share evidence, never nominal-capital guesses."""
import datetime as dt
import json
from collections import Counter
import run as R
import psycopg

OUT = R.HERE / "output/financial_history"

def main():
    with psycopg.connect(R.V.DSN, options="-c default_transaction_read_only=on") as con, con.cursor() as cur:
        cur.execute("""SELECT s.codal_symbol, si.security_id::text, si.company_id::text,
                       si.valid_from, si.valid_to, si.shares_outstanding, si.status,
                       si.knowledge_from, si.basis, si.evidence
                       FROM core.share_intervals si JOIN core.securities s ON s.id=si.security_id
                       WHERE s.is_primary ORDER BY s.codal_symbol, si.valid_from""")
        names = [d.name for d in cur.description]
        rows = [dict(zip(names, row)) for row in cur.fetchall()]
    for r in rows:
        if r["shares_outstanding"] is not None:
            r["shares_outstanding"] = float(r["shares_outstanding"])
    R.write(OUT / "share_intervals.json", {"exported_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": "existing_core.share_intervals_read_only", "intervals": rows})
    print(json.dumps({"intervals": len(rows), "status": dict(Counter(r["status"] for r in rows)),
                      "symbols": len({r["codal_symbol"] for r in rows})}))

if __name__ == "__main__":
    main()
