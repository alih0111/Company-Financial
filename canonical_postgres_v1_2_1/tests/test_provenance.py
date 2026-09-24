"""P01-P17: provenance / fetch-version / parse-run integrity."""

from helpers import (company, report, report_version, parse_run, monthly_activity,
                     financial_statement, metric, financial_fact, q, one, expect_error, uid)


def chain(conn, cname="C"):
    c = company(conn, cname)
    r = report(conn, c, cname + "-rep")
    rv = report_version(conn, r)
    pr = parse_run(conn, rv)
    return c, r, rv, pr


def test_P01_same_version_two_parsers_coexist(db):
    c = company(db, "C")
    r = report(db, c, "R")
    rv = report_version(db, r)
    parse_run(db, rv, "miansql", "v1", "completed")
    parse_run(db, rv, "miansql", "v2", "completed")
    n = one(db, "SELECT count(*) FROM ingestion.parse_runs WHERE report_version_id=%s", (rv,))[0]
    assert n == 2


def test_P02_duplicate_completed_parse_run_rejected(db):
    c = company(db, "C")
    r = report(db, c, "R")
    rv = report_version(db, r)
    parse_run(db, rv, "miansql", "v1", "completed")
    with expect_error(db, "uq_parse_runs_completed"):
        q(db, """INSERT INTO ingestion.parse_runs
                 (report_version_id, parser_name, parser_version, status, finished_at)
                 VALUES (%s,'miansql','v1','completed',now())""", (rv,))


def test_P03_duplicate_report_version_number_rejected(db):
    c = company(db, "C")
    r = report(db, c, "R")
    report_version(db, r, 1)
    with expect_error(db, "uq_report_versions_no"):
        q(db, """INSERT INTO ingestion.report_versions (report_id, version_no, content_hash)
                 VALUES (%s,1,%s)""", (r, uid()))


def test_P04_duplicate_content_hash_rejected(db):
    c = company(db, "C")
    r = report(db, c, "R")
    report_version(db, r, 1, content_hash="HASH-A")
    with expect_error(db, "uq_report_versions_hash"):
        q(db, """INSERT INTO ingestion.report_versions (report_id, version_no, content_hash)
                 VALUES (%s,2,'HASH-A')""", (r,))


def test_P05_report_version_mutation_rejected(db):
    c, r, rv, pr = chain(db)
    with expect_error(db, "append-only"):
        q(db, "UPDATE ingestion.report_versions SET content_hash='X' WHERE id=%s", (rv,))


def test_P06_parse_run_identity_mutation_rejected(db):
    c, r, rv, pr = chain(db)
    with expect_error(db, "identity is immutable"):
        q(db, "UPDATE ingestion.parse_runs SET parser_version='v9' WHERE id=%s", (pr,))


def test_P07_parse_run_running_to_completed_accepted(db):
    c = company(db, "C")
    r = report(db, c, "R")
    rv = report_version(db, r)
    pr = parse_run(db, rv, "miansql", "v1", status="running", finished=False)
    q(db, "UPDATE ingestion.parse_runs SET status='completed', finished_at=now() WHERE id=%s", (pr,))
    assert one(db, "SELECT status FROM ingestion.parse_runs WHERE id=%s", (pr,))[0] == "completed"


def test_P08_parse_run_belongs_to_other_version_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    r1 = report(db, c1, "R1")
    r2 = report(db, c2, "R2")
    rv1 = report_version(db, r1)
    rv2 = report_version(db, r2)
    pr2 = parse_run(db, rv2)
    with expect_error(db, "monthly_activities_parse_version_fk"):
        monthly_activity(db, c1, r1, rv1, pr2)


def test_P09_parse_run_version_mismatch_rejected(db):
    c1 = company(db, "C1")
    r1 = report(db, c1, "R1")
    rv1 = report_version(db, r1, 1)
    rv1b = report_version(db, r1, 2)
    pr1 = parse_run(db, rv1)
    # (parse_run_id=pr1 belongs to rv1) but report_version_id=rv1b -> chain FK violates
    with expect_error(db, "monthly_activities_parse_version_fk"):
        monthly_activity(db, c1, r1, rv1b, pr1)


def test_P10_statement_version_report_mismatch_rejected(db):
    c1 = company(db, "C1")
    r1 = report(db, c1, "R1")
    r2 = report(db, c1, "R2")
    rv2 = report_version(db, r2)
    pr2 = parse_run(db, rv2)
    with expect_error(db, "financial_statements_version_report_fk"):
        financial_statement(db, c1, r1, rv2, pr2)


def test_P11_monthly_activity_mutation_rejected(db):
    c, r, rv, pr = chain(db)
    mid = monthly_activity(db, c, r, rv, pr)
    with expect_error(db, "append-only"):
        q(db, "UPDATE fundamentals.monthly_activities SET sales_amount_rial=1 WHERE id=%s", (mid,))


def test_P12_financial_statement_mutation_rejected(db):
    c, r, rv, pr = chain(db)
    fs = financial_statement(db, c, r, rv, pr)
    with expect_error(db, "append-only"):
        q(db, "UPDATE fundamentals.financial_statements SET is_audited=true WHERE id=%s", (fs,))


def test_P13_financial_fact_mutation_rejected(db):
    c, r, rv, pr = chain(db)
    fs = financial_statement(db, c, r, rv, pr)
    metric(db, "revenue")
    ff = financial_fact(db, fs, "revenue")
    with expect_error(db, "append-only"):
        q(db, "UPDATE fundamentals.financial_facts SET canonical_value=0 WHERE id=%s", (ff,))


def test_P14_parse_run_running_to_completed_accepted(db):
    c = company(db, "C")
    r = report(db, c, "R")
    rv = report_version(db, r)
    pr = parse_run(db, rv, "miansql", "v1", status="running", finished=False)
    q(db, "UPDATE ingestion.parse_runs SET status='completed', finished_at=now() WHERE id=%s", (pr,))
    assert one(db, "SELECT status FROM ingestion.parse_runs WHERE id=%s", (pr,))[0] == "completed"


def test_P15_parse_run_completed_to_running_rejected(db):
    c, r, rv, pr = chain(db)
    with expect_error(db, "terminal"):
        q(db, "UPDATE ingestion.parse_runs SET status='running', finished_at=NULL WHERE id=%s", (pr,))


def test_P16_parse_run_completed_to_failed_rejected(db):
    c, r, rv, pr = chain(db)
    with expect_error(db, "terminal"):
        q(db, "UPDATE ingestion.parse_runs SET status='failed' WHERE id=%s", (pr,))


def test_P17_parse_run_failed_to_running_rejected(db):
    c = company(db, "C")
    r = report(db, c, "R")
    rv = report_version(db, r)
    pr = parse_run(db, rv, "miansql", "v1", status="failed", finished=True)
    with expect_error(db, "terminal"):
        q(db, "UPDATE ingestion.parse_runs SET status='running', finished_at=NULL WHERE id=%s", (pr,))
