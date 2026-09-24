"""S01-S04: supersede self-check and cycle detection."""

from helpers import company, report, q, one, expect_error, uid


def test_S01_self_supersede_rejected(db):
    c = company(db, "C")
    rid = uid()
    with expect_error(db, "supersede"):
        q(db, """INSERT INTO ingestion.reports
                 (id, company_id, source, source_report_id, supersedes_report_id)
                 VALUES (%s,%s,'codal','R',%s)""", (rid, c, rid))


def test_S02_two_node_cycle_rejected(db):
    c = company(db, "C")
    a = report(db, c, "A")
    b = report(db, c, "B", supersedes=a)
    with expect_error(db, "cycle"):
        q(db, "UPDATE ingestion.reports SET supersedes_report_id=%s WHERE id=%s", (b, a))


def test_S03_three_node_cycle_rejected(db):
    c = company(db, "C")
    a = report(db, c, "A")
    b = report(db, c, "B", supersedes=a)
    cc = report(db, c, "C", supersedes=b)
    with expect_error(db, "cycle"):
        q(db, "UPDATE ingestion.reports SET supersedes_report_id=%s WHERE id=%s", (cc, a))


def test_S04_valid_supersede_accepted(db):
    c = company(db, "C")
    a = report(db, c, "A")
    b = report(db, c, "B", supersedes=a)
    assert str(one(db, "SELECT supersedes_report_id FROM ingestion.reports WHERE id=%s", (b,))[0]) == a
    assert one(db, "SELECT count(*) FROM ingestion.reports WHERE id=%s", (a,))[0] == 1
