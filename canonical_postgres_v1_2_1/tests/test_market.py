"""M01-M09: market price revisioning, dedup scope, view and point-in-time."""

from helpers import company, security, price_observation, q, one, expect_error, uid

D = "2026-01-10"
T1 = "2026-01-11T10:00:00Z"
T2 = "2026-02-01T10:00:00Z"


def sec(conn):
    c = company(conn, "C")
    return security(conn, c, ins=111, symbol="S1")


def pit(conn, sid, cutoff):
    return one(conn, """
        SELECT closing_price_rial FROM market.price_observations
        WHERE security_id=%s AND trade_date=%s AND price_series='adjusted'
          AND collected_at <= %s
        ORDER BY collected_at DESC, id DESC LIMIT 1
    """, (sid, D, cutoff))[0]


def test_M01_two_versions_coexist(db):
    s = sec(db)
    price_observation(db, s, D, 100, T1, adjustment_version="v1")
    price_observation(db, s, D, 80, T2, adjustment_version="v2")
    assert one(db, "SELECT count(*) FROM market.price_observations WHERE security_id=%s", (s,))[0] == 2


def test_M02_duplicate_observation_rejected(db):
    s = sec(db)
    h = "SAME-HASH"
    price_observation(db, s, D, 100, T1, obs_hash=h)
    with expect_error(db, "uq_price_observations_identity"):
        price_observation(db, s, D, 100, T1, obs_hash=h)


def test_M03_price_observation_mutation_rejected(db):
    s = sec(db)
    price_observation(db, s, D, 100, T1)
    oid = one(db, "SELECT id FROM market.price_observations WHERE security_id=%s", (s,))[0]
    with expect_error(db, "append-only"):
        q(db, "UPDATE market.price_observations SET closing_price_rial=1 WHERE id=%s", (oid,))


def test_M04_daily_prices_view_returns_latest(db):
    s = sec(db)
    price_observation(db, s, D, 100, T1, adjustment_version="v1")
    price_observation(db, s, D, 80, T2, adjustment_version="v2")
    assert one(db, "SELECT closing_price_rial FROM market.daily_prices WHERE security_id=%s AND trade_date=%s", (s, D))[0] == 80


def test_M05_point_in_time_before_second_version(db):
    s = sec(db)
    price_observation(db, s, D, 100, T1, adjustment_version="v1")
    price_observation(db, s, D, 80, T2, adjustment_version="v2")
    assert pit(db, s, "2026-01-20T00:00:00Z") == 100
    assert pit(db, s, "2026-02-10T00:00:00Z") == 80


def test_M06_trade_date_not_null_rejected(db):
    s = sec(db)
    with expect_error(db, "trade_date"):
        q(db, """INSERT INTO market.price_observations
                 (security_id, trade_date, closing_price_rial, observation_hash)
                 VALUES (%s, NULL, 100, %s)""", (s, uid()))


def test_M07_vendor_security_company_mismatch_rejected(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s1 = security(db, c1, ins=111, symbol="S1")
    with expect_error(db, "vendor_snapshots_security_company_fk"):
        q(db, """INSERT INTO market.vendor_snapshots
                 (security_id, company_id, captured_at, vendor, metric_code)
                 VALUES (%s,%s,now(),'tsetmc','pe')""", (s1, c2))


def test_M08_vendor_security_without_company_rejected(db):
    c1 = company(db, "C1")
    s1 = security(db, c1, ins=111, symbol="S1")
    with expect_error(db, "vendor_snapshots_security_implies_company"):
        q(db, """INSERT INTO market.vendor_snapshots
                 (security_id, company_id, captured_at, vendor, metric_code)
                 VALUES (%s,NULL,now(),'tsetmc','pe')""", (s1,))


def test_M09_scoped_hash_allows_same_values_two_securities(db):
    c1 = company(db, "C1")
    c2 = company(db, "C2")
    s1 = security(db, c1, ins=111, symbol="S1")
    s2 = security(db, c2, ins=222, symbol="S2")
    h = "IDENTICAL-VALUES"
    price_observation(db, s1, D, 100, T1, obs_hash=h)
    price_observation(db, s2, D, 100, T1, obs_hash=h)
    assert one(db, "SELECT count(*) FROM market.price_observations WHERE observation_hash=%s", (h,))[0] == 2
