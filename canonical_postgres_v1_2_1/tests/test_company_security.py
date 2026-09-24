"""C01-C09: company / security / report consistency."""

from helpers import (company, security, report, report_version, parse_run,
                     monthly_activity, financial_statement, q, one, expect_error)


def chain(conn, cname, company_id):
    r = report(conn, company_id, cname + "-rep")
    rv = report_version(conn, r)
    pr = parse_run(conn, rv)
    return r, rv, pr


def test_C01_report_security_company_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s2 = security(db, c2, ins=222, symbol="S2")
    with expect_error(db, "reports_security_company_fk"):
        report(db, c1, "R", security_id=s2)


def test_C02_monthly_security_company_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s2 = security(db, c2, ins=222, symbol="S2")
    r, rv, pr = chain(db, "C1", c1)
    with expect_error(db, "monthly_activities_security_company_fk"):
        monthly_activity(db, c1, r, rv, pr, security_id=s2)


def test_C03_two_primary_securities_rejected(db):
    c1 = company(db, "C1")
    security(db, c1, ins=111, symbol="S1", is_primary=True)
    with expect_error(db, "uq_securities_one_primary_per_company"):
        security(db, c1, ins=112, symbol="S1b", is_primary=True)


def test_C04_duplicate_ins_code_rejected(db):
    c1 = company(db, "C1")
    security(db, c1, ins=111, symbol="S1")
    c2 = company(db, "C2")
    with expect_error(db, "uq_securities_tsetmc_ins_code"):
        security(db, c2, ins=111, symbol="S1dup")


def test_C05_invalid_security_validity_rejected(db):
    c1 = company(db, "C1")
    with expect_error(db, "securities_validity_chk"):
        security(db, c1, ins=113, symbol="S1", valid_from="2026-05-01", valid_to="2026-01-01")


def test_C06_change_referenced_security_company_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s1 = security(db, c1, ins=111, symbol="S1")
    report(db, c1, "R", security_id=s1)
    with expect_error(db, "reports_security_company_fk"):
        q(db, "UPDATE core.securities SET company_id=%s WHERE id=%s", (c2, s1))


def test_C07_report_source_identity_change_rejected(db):
    c1 = company(db, "C1")
    r = report(db, c1, "R")
    with expect_error(db, "identity is immutable"):
        q(db, "UPDATE ingestion.reports SET source_report_id='R2' WHERE id=%s", (r,))


def test_C08_monthly_report_company_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    r1, rv1, pr1 = chain(db, "C1", c1)
    with expect_error(db, "monthly_activities_report_company_fk"):
        monthly_activity(db, c2, r1, rv1, pr1)


def test_C09_statement_report_company_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    r1, rv1, pr1 = chain(db, "C1", c1)
    with expect_error(db, "financial_statements_report_company_fk"):
        financial_statement(db, c2, r1, rv1, pr1)
