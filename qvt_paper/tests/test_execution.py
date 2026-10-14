import datetime as dt
from pathlib import Path
import sys
import pytest
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from execution_journal import SimulationJournal
from portfolio_engine import choose

NOW = "2026-10-13T10:00:00Z"


def test_wal_backup_restores_partial_fills_stop_and_idempotency(tmp_path):
    journal = SimulationJournal(tmp_path / "live.sqlite", 1000, 200)
    journal.submit("order", intent(), NOW)
    journal.fill("fill1", "order", 4, 10, ".005", NOW, NOW)
    journal.stop()
    before = journal.snapshot()
    backup = journal.backup(tmp_path / "backup.sqlite")
    restored = SimulationJournal(backup, 1000, 200)
    assert restored.snapshot() == before
    restored.fill("fill1", "order", 4, 10, ".005", NOW, "2026-10-13T10:05:00Z")
    assert restored.snapshot() == before
    with pytest.raises(ValueError, match="stopped"):
        restored.fill("fill2", "order", 6, 10, ".005", NOW, NOW)
    with pytest.raises(FileExistsError):
        journal.backup(backup)
    restored.close()
    journal.close()


def test_concurrent_duplicate_callbacks_use_independent_connections_once(tmp_path):
    path = tmp_path / "concurrent.sqlite"
    journal = SimulationJournal(path, 1000, 200)
    journal.submit("order", intent(), NOW)
    journal.close()

    def callback(received_at):
        worker = SimulationJournal(path, 1000, 200)
        try:
            worker.fill("same-fill", "order", 4, 10, ".005", NOW, received_at)
        finally:
            worker.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(callback, [NOW, "2026-10-13T10:05:00Z"]))
    journal = SimulationJournal(path, 1000, 200)
    snapshot = journal.snapshot()
    assert snapshot["cash"] == "959.800" and snapshot["holdings"] == {"A": "4"}
    assert snapshot["orders"][0]["filled"] == "4"
    journal.close()


def intent(**extra):
    return {"mode": "simulation", "security": "A", "strategy_version": "test-v1", "side": "BUY",
            "quantity": "10", "limit_price": "10", "signal_at": "2026-10-13T09:00:00Z",
            "expires_at": "2026-10-13T11:00:00Z", **extra}


def test_partial_fill_restart_and_duplicate_do_not_spend_twice(tmp_path):
    path = tmp_path / "journal.sqlite"
    journal = SimulationJournal(path, 1000, 200)
    journal.submit("order", intent(), NOW)
    journal.fill("fill1", "order", 4, 10, ".005", NOW, NOW)
    before = journal.snapshot()
    journal.close()
    journal = SimulationJournal(path, 1000, 200)
    journal.submit("order", intent(), NOW)
    journal.fill("fill1", "order", 4, 10, ".005", NOW, "2026-10-13T10:05:00Z")
    assert journal.snapshot() == before
    assert before["cash"] == "959.800"
    assert before["orders"][0]["status"] == "partial"
    with pytest.raises(ValueError, match="conflicting"):
        journal.fill("fill1", "order", 5, 10, ".005", NOW, NOW)
    journal.fill("fill2", "order", 6, 10, ".005", NOW, NOW)
    assert journal.snapshot()["cash"] == "899.500"
    assert journal.order("order")["status"] == "filled"
    assert journal.reconcile("899.500", {"A": "10"})["matched"]
    assert not journal.reconcile("899.500", {"A": "9"})["matched"]
    assert journal.snapshot()["stopped"]
    journal.close()


def test_cash_holding_stale_future_and_limits_rollback(tmp_path):
    journal = SimulationJournal(tmp_path / "journal.sqlite", 50, 200)
    journal.submit("order", intent(), NOW)
    before = journal.snapshot()
    for kwargs, message in [({"quantity": 10}, "insufficient"),
                            ({"price": 11}, "limit"),
                            ({"quote_at": "2026-10-13T09:30:00Z"}, "stale"),
                            ({"quote_at": "2026-10-13T10:01:00Z"}, "future")]:
        args = dict(quantity=1, price=10, fee_rate=".005", quote_at=NOW, now=NOW)
        args.update(kwargs)
        with pytest.raises(ValueError, match=message):
            journal.fill("bad", "order", **args)
        assert journal.snapshot() == before
    journal.submit("sell", intent(side="SELL"), NOW)
    with pytest.raises(ValueError, match="holding"):
        journal.fill("sell1", "sell", 1, 10, ".005", NOW, NOW)
    journal.stop()
    with pytest.raises(ValueError, match="stopped"):
        journal.fill("later", "order", 1, 10, ".005", NOW, NOW)
    journal.cancel("order")
    journal.stop(False)
    with pytest.raises(ValueError, match="inactive"):
        journal.fill("cancelled", "order", 1, 10, ".005", NOW, NOW)
    journal.close()


def test_live_mode_and_conflicting_intent_refused(tmp_path):
    with pytest.raises(ValueError, match="simulation"):
        SimulationJournal(tmp_path / "live.sqlite", 100, 100, mode="live")
    journal = SimulationJournal(tmp_path / "journal.sqlite", 1000, 200)
    journal.submit("one", intent(), NOW)
    with pytest.raises(ValueError, match="conflicting"):
        journal.submit("one", intent(quantity="9"), NOW)
    journal.close()


def test_missing_industry_does_not_escape_concentration_control():
    row = {"company_id": "1", "symbol": "A", "rank": 1, "score": 90, "status": "buy_review", "full_coverage": True,
           "q": {"scored_factors": ["Q"]}, "v": {"scored_factors": ["V"]}, "t": {"scored_factors": ["T"]}}
    selected, skipped = choose([row], {"max_positions": 10, "position_weight": .1, "max_industry_weight": .3})
    assert selected == [] and "صنعت" in skipped[0]["reason"]
