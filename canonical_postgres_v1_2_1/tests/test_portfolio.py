"""L01-L24: portfolio referential integrity, ledger semantics, reversal, derived."""

from helpers import (portfolio, participant, account, asset, txn, q, one, expect_error, uid)


def setup_portfolio(conn):
    p1 = portfolio(conn, "p1")
    pa1 = participant(conn, p1, "pa1")
    ac1 = account(conn, p1, pa1, "cash")
    a1 = asset(conn, "asset1", None, "stock")
    p2 = portfolio(conn, "p2")
    pa2 = participant(conn, p2, "pa2")
    ac2 = account(conn, p2, pa2, "cash")
    return p1, pa1, ac1, a1, p2, pa2, ac2


def test_L01_account_from_other_portfolio_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "transactions_account_portfolio_fk"):
        txn(db, p1, ac2, "opening_cash", quantity_delta=0, cash_delta=1)


def test_L02_participant_from_other_portfolio_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "transactions_participant_portfolio_fk"):
        txn(db, p1, ac1, "opening_cash", cash_delta=1, participant_id=pa2)


def test_L03_account_participant_other_portfolio_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "accounts_participant_portfolio_fk"):
        account(db, p1, pa2, "cash")


def test_L04_transaction_without_account_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "account_id"):
        q(db, """INSERT INTO portfolio.transactions
                 (portfolio_id, account_id, transaction_type, effective_date, cash_delta_rial)
                 VALUES (%s, NULL, 'opening_cash', '2026-06-21', 100)""", (p1,))


def test_L05_buy_wrong_sign_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "transactions_sign_chk"):
        txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=100,
            trade_date="2026-06-21", asset_id=a1)


def test_L06_buy_without_trade_date_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "transactions_trade_date_chk"):
        txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
            trade_date=None, asset_id=a1)


def test_L07_opening_position_without_cost_basis_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "transactions_opening_cost_chk"):
        txn(db, p1, ac1, "opening_position", quantity_delta=500, cash_delta=0,
            effective_date="2026-06-21", asset_id=a1, cost_basis=None)


def test_L08_opening_position_with_effective_date_accepted(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    t = txn(db, p1, ac1, "opening_position", quantity_delta=500, cash_delta=0,
            effective_date="2026-06-21", trade_date=None, asset_id=a1, cost_basis=25000000)
    assert one(db, "SELECT trade_date FROM portfolio.transactions WHERE id=%s", (t,))[0] is None


def test_L09_cash_balance_from_ledger(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    txn(db, p1, ac1, "opening_cash", cash_delta=100000000)
    txn(db, p1, ac1, "buy", quantity_delta=1000, cash_delta=-20000000,
        trade_date="2026-06-21", asset_id=a1)
    cash = one(db, "SELECT SUM(cash_delta_rial) FROM portfolio.transactions WHERE portfolio_id=%s", (p1,))[0]
    assert cash == 80000000


def test_L10_position_quantity_from_ledger(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    txn(db, p1, ac1, "opening_cash", cash_delta=100000000)
    txn(db, p1, ac1, "buy", quantity_delta=1000, cash_delta=-20000000,
        trade_date="2026-06-21", asset_id=a1)
    qty = one(db, "SELECT SUM(quantity_delta) FROM portfolio.transactions WHERE portfolio_id=%s AND asset_id=%s", (p1, a1))[0]
    assert qty == 1000


def test_L11_opening_cost_basis_rebuild(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    txn(db, p1, ac1, "opening_position", quantity_delta=500, cash_delta=0,
        asset_id=a1, cost_basis=25000000)
    row = one(db, """SELECT SUM(quantity_delta), SUM(COALESCE(cost_basis_rial,0))
                     FROM portfolio.effective_transactions
                     WHERE portfolio_id=%s AND asset_id=%s""", (p1, a1))
    assert row[0] == 500 and row[1] == 25000000


def test_L12_self_reversal_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    tid = uid()
    with expect_error(db, "does not exist"):
        txn(db, p1, ac1, "reversal", reverses=tid, tx_id=tid)


def test_L13_duplicate_reversal_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    buy = txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
              trade_date="2026-06-21", asset_id=a1)
    txn(db, p1, ac1, "reversal", reverses=buy)
    with expect_error(db, "uq_transactions_reverses"):
        txn(db, p1, ac1, "reversal", reverses=buy)


def test_L14_reversal_wrong_portfolio_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    buy = txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
              trade_date="2026-06-21", asset_id=a1)
    with expect_error(db, "mismatch"):
        txn(db, p2, ac2, "reversal", reverses=buy)


def test_L15_reversal_of_reversal_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    buy = txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
              trade_date="2026-06-21", asset_id=a1)
    r1 = txn(db, p1, ac1, "reversal", reverses=buy)
    with expect_error(db, "cannot reverse a reversal"):
        txn(db, p1, ac1, "reversal", reverses=r1)


def test_L16_reversal_nonexistent_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "does not exist"):
        txn(db, p1, ac1, "reversal", reverses=uid())


def test_L17_reversal_inverse_effects(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    buy = txn(db, p1, ac1, "buy", quantity_delta=1000, cash_delta=-20000000,
              trade_date="2026-06-21", asset_id=a1)
    r = txn(db, p1, ac1, "reversal", reverses=buy)
    qd, cd = one(db, "SELECT quantity_delta, cash_delta_rial FROM portfolio.transactions WHERE id=%s", (r,))
    assert qd == -1000 and cd == 20000000


def test_L18_reversal_inherits_fields(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    buy = txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
              trade_date="2026-06-21", asset_id=a1, participant_id=pa1)
    r = txn(db, p1, ac1, "reversal", reverses=buy)
    row = one(db, "SELECT account_id, participant_id, asset_id, portfolio_id FROM portfolio.transactions WHERE id=%s", (r,))
    assert (str(row[0]), str(row[1]), str(row[2]), str(row[3])) == (ac1, pa1, a1, p1)


def test_L19_transaction_mutation_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    t = txn(db, p1, ac1, "opening_cash", cash_delta=100)
    with expect_error(db, "immutable ledger"):
        q(db, "UPDATE portfolio.transactions SET cash_delta_rial=1 WHERE id=%s", (t,))


def test_L20_duplicate_asset_price_rejected(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    q(db, "INSERT INTO portfolio.asset_price_snapshots (asset_id, price_date, price_rial) VALUES (%s,'2026-06-21',100)", (a1,))
    with expect_error(db, "asset_price_unique"):
        q(db, "INSERT INTO portfolio.asset_price_snapshots (asset_id, price_date, price_rial) VALUES (%s,'2026-06-21',200)", (a1,))


def test_L21_opening_position_reversal_quantity_zero(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    op = txn(db, p1, ac1, "opening_position", quantity_delta=500, cash_delta=0,
             asset_id=a1, cost_basis=25000000)
    txn(db, p1, ac1, "reversal", reverses=op)
    qty = one(db, "SELECT COALESCE(SUM(quantity_delta),0) FROM portfolio.effective_transactions WHERE portfolio_id=%s AND asset_id=%s", (p1, a1))[0]
    assert qty == 0


def test_L22_opening_position_reversal_cost_zero(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    op = txn(db, p1, ac1, "opening_position", quantity_delta=500, cash_delta=0,
             asset_id=a1, cost_basis=25000000)
    txn(db, p1, ac1, "reversal", reverses=op)
    cb = one(db, "SELECT COALESCE(SUM(COALESCE(cost_basis_rial,0)),0) FROM portfolio.effective_transactions WHERE portfolio_id=%s AND asset_id=%s", (p1, a1))[0]
    assert cb == 0


def test_L23_buy_reversal_economic_state(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    txn(db, p1, ac1, "opening_cash", cash_delta=100000000)
    buy = txn(db, p1, ac1, "buy", quantity_delta=1000, cash_delta=-20000000,
              trade_date="2026-06-21", asset_id=a1)
    txn(db, p1, ac1, "reversal", reverses=buy)
    n = one(db, "SELECT count(*) FROM portfolio.effective_transactions WHERE portfolio_id=%s AND asset_id=%s", (p1, a1))[0]
    qty = one(db, "SELECT COALESCE(SUM(quantity_delta),0) FROM portfolio.effective_transactions WHERE portfolio_id=%s AND asset_id=%s", (p1, a1))[0]
    assert n == 0 and qty == 0


def test_L24_quantity_is_derived(db):
    p1, pa1, ac1, a1, p2, pa2, ac2 = setup_portfolio(db)
    with expect_error(db, "quantity"):
        q(db, """INSERT INTO portfolio.transactions
                 (portfolio_id, account_id, transaction_type, effective_date, trade_date,
                  quantity, quantity_delta, cash_delta_rial, asset_id)
                 VALUES (%s,%s,'buy','2026-06-21','2026-06-21',999,10,-100,%s)""",
          (p1, ac1, a1))
    # derived value equals abs(quantity_delta)
    t = txn(db, p1, ac1, "buy", quantity_delta=10, cash_delta=-100,
            trade_date="2026-06-21", asset_id=a1)
    assert one(db, "SELECT quantity FROM portfolio.transactions WHERE id=%s", (t,))[0] == 10
