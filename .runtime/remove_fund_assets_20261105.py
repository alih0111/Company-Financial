# One-off: remove all fund securities/companies except Mesghal & Ayar,
# and all index series except TEDPIX, from the canonical DB.
# Everything deleted is first copied into backup schema backup_fund_removal_20261105.
from __future__ import annotations

import re
import sys

import psycopg

BASE = r"D:/RFA/Company-Financial"
BACKUP_SCHEMA = "backup_fund_removal_20261105"
KEEP_SYMBOLS = {"مثقال", "عیار"}
KEEP_INDEX_CODES = {"TEDPIX"}
FUND_NAME_PATTERNS = ("%صندوق%", "%صندوق%", "%ص.س.%")

STEPS = [
    ("analytics.company_scores", "company_id IN {COMP} OR primary_security_id IN {SEC}"),
    ("market.price_observations", "security_id IN {SEC}"),
    # market.daily_prices is a view over price_observations — empties itself.
    ("core.security_aliases", "security_id IN {SEC}"),
    ("market.vendor_snapshots", "security_id IN {SEC} OR company_id IN {COMP}"),
    ("market.corporate_actions", "security_id IN {SEC}"),
    ("market.tsetmc_current_shares", "security_id IN {SEC}"),
    ("core.share_structure", "security_id IN {SEC}"),
    ("core.share_intervals", "security_id IN {SEC}"),
    ("core.share_events", "security_id IN {SEC} OR company_id IN {COMP}"),
    ("fundamentals.monthly_activities",
     "company_id IN {COMP} OR security_id IN {SEC} OR report_id IN {REPORT} "
     "OR report_version_id IN {VERSION} OR parse_run_id IN {RUN}"),
    ("fundamentals.financial_statements",
     "company_id IN {COMP} OR report_id IN {REPORT} "
     "OR report_version_id IN {VERSION} OR parse_run_id IN {RUN}"),
    ("raw.report_payloads", "report_version_id IN {VERSION}"),
    ("ingestion.parse_runs", "report_version_id IN {VERSION}"),
    ("ingestion.report_versions", "report_id IN {REPORT}"),
    ("ingestion.reports", "company_id IN {COMP} OR security_id IN {SEC}"),
    ("ingestion.tracked_securities", "security_id IN {SEC}"),
    ("auth.user_view_events", "security_id IN {SEC}"),
    ("portfolio.assets", "security_id IN {SEC}"),
    ("core.company_classification", "company_id IN {COMP} OR security_id IN {SEC}"),
    ("core.legacy_entity_map", "target_uuid IN {SEC} OR target_uuid IN {COMP}"),
    ("core.securities", "id IN {SEC}"),
    ("core.companies", "id IN {COMP}"),
]

# Append-only triggers that block DELETE. Disabled only inside this transaction
# (same one-time-backfill pattern as sql/121_analytics_run_identity.sql) and
# re-enabled before commit; rollback restores them automatically.
IMMUTABLE_TRIGGERS = [
    ("analytics.company_scores", "trg_company_scores_immutable"),
    ("market.price_observations", "trg_price_observations_immutable"),
    ("fundamentals.monthly_activities", "trg_monthly_activities_immutable"),
    ("fundamentals.financial_statements", "trg_financial_statements_immutable"),
    ("raw.report_payloads", "trg_report_payloads_immutable"),
    ("ingestion.report_versions", "trg_report_versions_immutable"),
]


def db_url() -> str:
    url = None
    with open(BASE + "/go-app/.env", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("DATABASE_URL="):
                url = line.split("=", 1)[1]
    if not url:
        raise SystemExit("DATABASE_URL not found in go-app/.env")
    url = re.sub(r"^postgresql\+psycopg://", "postgresql://", url)
    url = re.sub(r"/postgres(\?|$)", "/company_financial_analytics_shadow_v121\\1", url)
    return url


def main() -> None:
    url = db_url()
    with psycopg.connect(url) as conn:
        conn.autocommit = False
        with conn.cursor() as cur:
            # 1. Resolve deletion sets straight from the DB (single source of truth).
            cur.execute(
                "SELECT s.id, s.codal_symbol, c.id FROM core.securities s "
                "JOIN core.companies c ON c.id = s.company_id "
                "WHERE c.display_name LIKE %s OR c.legal_name LIKE %s OR c.display_name LIKE %s",
                FUND_NAME_PATTERNS,
            )
            rows = cur.fetchall()
            sec_ids = [str(r[0]) for r in rows if r[1] not in KEEP_SYMBOLS]
            comp_ids = sorted({str(r[2]) for r in rows if r[1] not in KEEP_SYMBOLS})
            if len(sec_ids) != 58 or len(comp_ids) != 50:
                raise SystemExit(
                    f"unexpected deletion set: {len(sec_ids)} securities / {len(comp_ids)} companies (expected 58/50)"
                )
            sec_in = "(" + ",".join("'" + x + "'" for x in sec_ids) + ")"
            comp_in = "(" + ",".join("'" + x + "'" for x in comp_ids) + ")"

            # 2. Backup schema.
            cur.execute("SELECT 1 FROM pg_namespace WHERE nspname = %s", (BACKUP_SCHEMA,))
            if cur.fetchone():
                raise SystemExit(f"backup schema {BACKUP_SCHEMA} already exists; refusing to overwrite")
            cur.execute(f"CREATE SCHEMA {BACKUP_SCHEMA}")

            kept = sorted(r[1] for r in rows if r[1] in KEEP_SYMBOLS)
            print(f"deleting {len(sec_ids)} securities / {len(comp_ids)} companies; keeping funds: {kept}")

            # 3. Temporarily lift append-only guards (restored before commit).
            for table, trig in IMMUTABLE_TRIGGERS:
                cur.execute(f"ALTER TABLE {table} DISABLE TRIGGER {trig}")

            # 4. Backup + delete, child tables first.
            report_sub = (
                f"(SELECT id FROM ingestion.reports WHERE company_id IN {comp_in} "
                f"OR security_id IN {sec_in})"
            )
            version_sub = f"(SELECT id FROM ingestion.report_versions WHERE report_id IN {report_sub})"
            run_sub = f"(SELECT id FROM ingestion.parse_runs WHERE report_version_id IN {version_sub})"
            ctx = {
                "SEC": sec_in,
                "COMP": comp_in,
                "REPORT": report_sub,
                "VERSION": version_sub,
                "RUN": run_sub,
            }
            total = 0
            for table, cond in STEPS:
                where = cond.format(**ctx)
                schema, name = table.split(".")
                bk = f"{BACKUP_SCHEMA}.{schema}__{name}"
                cur.execute(f"CREATE TABLE {bk} AS SELECT * FROM {table} WHERE {where}")
                cur.execute(f"SELECT count(*) FROM {bk}")
                n_backup = cur.fetchone()[0]
                cur.execute(f"DELETE FROM {table} WHERE {where}")
                n_del = cur.rowcount
                if n_backup != n_del:
                    raise SystemExit(f"count mismatch for {table}: backed up {n_backup}, deleted {n_del}")
                total += n_del
                print(f"  {table:38} -{n_del}")

            # 4. Index observations: drop every series except TEDPIX.
            cur.execute("SELECT DISTINCT index_code FROM market.index_observations")
            codes = [r[0] for r in cur.fetchall()]
            drop_codes = [c for c in codes if c not in KEEP_INDEX_CODES]
            if drop_codes:
                code_in = "(" + ",".join("'" + c + "'" for c in drop_codes) + ")"
                cur.execute(
                    f"CREATE TABLE {BACKUP_SCHEMA}.market__index_observations AS "
                    f"SELECT * FROM market.index_observations WHERE index_code IN {code_in}"
                )
                cur.execute(f"SELECT count(*) FROM {BACKUP_SCHEMA}.market__index_observations")
                n_backup = cur.fetchone()[0]
                cur.execute(f"DELETE FROM market.index_observations WHERE index_code IN {code_in}")
                print(f"  market.index_observations          -{cur.rowcount} (codes: {','.join(drop_codes)})")
                if n_backup != cur.rowcount:
                    raise SystemExit("count mismatch for index_observations")
                total += cur.rowcount

            # 5. Restore append-only guards.
            for table, trig in IMMUTABLE_TRIGGERS:
                cur.execute(f"ALTER TABLE {table} ENABLE TRIGGER {trig}")

            # 6. Post-state sanity checks before commit.
            cur.execute("SELECT security_type, count(*) FROM core.securities GROUP BY 1 ORDER BY 1")
            print("  securities now:", cur.fetchall())
            cur.execute("SELECT count(*) FROM core.companies")
            print("  companies now:", cur.fetchone()[0])
            cur.execute(
                "SELECT count(*) FROM core.securities s JOIN core.companies c ON c.id = s.company_id "
                "WHERE c.display_name LIKE %s OR c.legal_name LIKE %s OR c.display_name LIKE %s",
                FUND_NAME_PATTERNS,
            )
            remaining_funds = cur.fetchone()[0]
            cur.execute("SELECT DISTINCT index_code FROM market.index_observations ORDER BY 1")
            remaining_idx = [r[0] for r in cur.fetchall()]
            if remaining_funds != 2 or set(remaining_idx) != KEEP_INDEX_CODES:
                raise SystemExit(f"post-state check failed: funds={remaining_funds} indexes={remaining_idx}")
            print(f"  remaining fund securities: {remaining_funds}; index codes: {remaining_idx}")
            print(f"  total rows deleted: {total}; backup schema: {BACKUP_SCHEMA}")

        conn.commit()
        print("COMMIT ok")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as exc:
        print("ABORTED:", exc)
        sys.exit(1)
