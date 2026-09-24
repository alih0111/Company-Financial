"""A01-A11: analytics output immutability, lifecycles, security consistency, cutoff."""

from helpers import (company, security, score_run, company_score, factor_score,
                     metric_snapshot, price_observation, q, one, expect_error)


def test_A01_company_score_security_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s2 = security(db, c2, ins=222, symbol="S2")
    run = score_run(db)
    with expect_error(db, "company_scores_security_company_fk"):
        company_score(db, run, c1, primary_security_id=s2)


def test_A02_company_score_mutation_rejected(db):
    c1 = company(db, "C1")
    run = score_run(db)
    cid = company_score(db, run, c1)
    with expect_error(db, "append-only"):
        q(db, "UPDATE analytics.company_scores SET quant_score=1 WHERE id=%s", (cid,))


def test_A03_factor_score_mutation_rejected(db):
    c1 = company(db, "C1")
    run = score_run(db)
    fid = factor_score(db, run, c1)
    with expect_error(db, "append-only"):
        q(db, "UPDATE analytics.factor_scores SET percentile=1 WHERE id=%s", (fid,))


def test_A04_metric_snapshot_mutation_rejected(db):
    c1 = company(db, "C1")
    mid = metric_snapshot(db, c1)
    with expect_error(db, "append-only"):
        q(db, "UPDATE analytics.metric_snapshots SET value=1 WHERE id=%s", (mid,))


def test_A05_score_run_running_to_completed_accepted(db):
    run = score_run(db)
    q(db, "UPDATE analytics.score_runs SET status='completed', completed_at=now() WHERE id=%s", (run,))
    assert one(db, "SELECT status FROM analytics.score_runs WHERE id=%s", (run,))[0] == "completed"


def test_A06_score_run_identity_mutation_rejected(db):
    run = score_run(db)
    with expect_error(db, "identity is immutable"):
        q(db, "UPDATE analytics.score_runs SET score_version='v9' WHERE id=%s", (run,))


def test_A07_metric_snapshot_respects_cutoff(db):
    c = company(db, "C")
    s = security(db, c, ins=111, symbol="S1")
    cutoff = "2026-01-20T00:00:00Z"
    run = score_run(db, cutoff=cutoff)
    price_observation(db, s, "2026-01-10", 100, "2026-01-11T10:00:00Z")
    price_observation(db, s, "2026-01-10", 80, "2026-02-01T10:00:00Z")
    val = one(db, """
        SELECT po.closing_price_rial
        FROM analytics.score_runs r
        JOIN market.price_observations po
          ON po.security_id=%s AND po.trade_date='2026-01-10'
         AND po.collected_at <= r.source_cutoff_at
        WHERE r.id=%s
        ORDER BY po.collected_at DESC, po.id DESC LIMIT 1
    """, (s, run))[0]
    assert val == 100


def test_A08_score_run_running_to_completed_accepted(db):
    run = score_run(db)
    q(db, "UPDATE analytics.score_runs SET status='completed', completed_at=now() WHERE id=%s", (run,))
    assert one(db, "SELECT status FROM analytics.score_runs WHERE id=%s", (run,))[0] == "completed"


def test_A09_score_run_completed_to_running_rejected(db):
    run = score_run(db, status="completed", completed=True)
    with expect_error(db, "terminal"):
        q(db, "UPDATE analytics.score_runs SET status='running', completed_at=NULL WHERE id=%s", (run,))


def test_A10_score_run_completed_to_failed_rejected(db):
    run = score_run(db, status="completed", completed=True)
    with expect_error(db, "terminal"):
        q(db, "UPDATE analytics.score_runs SET status='failed' WHERE id=%s", (run,))


def test_A11_score_run_failed_to_running_rejected(db):
    run = score_run(db, status="failed", completed=True)
    with expect_error(db, "terminal"):
        q(db, "UPDATE analytics.score_runs SET status='running', completed_at=NULL WHERE id=%s", (run,))
