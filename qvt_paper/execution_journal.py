"""Transactional simulation journal. This module has no real-order transport.

Decimal accounting, immutable intents, fill idempotency, cash/quantity guards,
stale-price checks and a persisted stop switch prepare the execution contract.
"""
from __future__ import annotations
from contextlib import contextmanager
import datetime as dt
from decimal import Decimal
import json
import sqlite3
from pathlib import Path


def amount(value):
    result = Decimal(str(value))
    if not result.is_finite():
        raise ValueError("nonfinite amount")
    return result


def instant(value):
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone required")
    return result


class SimulationJournal:
    def __init__(self, path, initial_cash, max_order_notional, mode="simulation"):
        if mode != "simulation":
            raise ValueError("Only simulation mode is implemented; no live transport")
        capital, limit = amount(initial_cash), amount(max_order_notional)
        if capital <= 0 or limit <= 0:
            raise ValueError("positive capital and order limit required")
        self.db = sqlite3.connect(str(path), isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS holdings (security TEXT PRIMARY KEY, quantity TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders (key TEXT PRIMARY KEY, payload TEXT NOT NULL, status TEXT NOT NULL, filled TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS fills (key TEXT PRIMARY KEY, order_key TEXT NOT NULL, payload TEXT NOT NULL);
        """)
        with self.transaction():
            for key, val in [("initial_cash", str(capital)), ("cash", str(capital)),
                             ("max_order_notional", str(limit)), ("stopped", "false")]:
                self.db.execute("INSERT OR IGNORE INTO config VALUES (?,?)", (key, val))
            if amount(self.config("initial_cash")) != capital or amount(self.config("max_order_notional")) != limit:
                raise ValueError("existing journal configuration mismatch")

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except Exception:
            self.db.execute("ROLLBACK")
            raise

    def config(self, key):
        return self.db.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()[0]

    def active(self):
        if self.config("stopped") == "true":
            raise ValueError("simulation stopped")

    def stop(self, stopped=True):
        with self.transaction():
            self.db.execute("UPDATE config SET value=? WHERE key='stopped'", ("true" if stopped else "false",))

    def submit(self, key, intent, now):
        payload = json.dumps(intent, sort_keys=True, separators=(",", ":"), allow_nan=False)
        quantity, price = amount(intent["quantity"]), amount(intent["limit_price"])
        signal, expiry = instant(intent["signal_at"]), instant(intent["expires_at"])
        current = instant(now)
        if (intent.get("mode") != "simulation" or intent["side"] not in ("BUY", "SELL") or
                not intent.get("security") or not intent.get("strategy_version") or quantity <= 0 or price <= 0):
            raise ValueError("invalid simulation intent")
        if not signal <= current < expiry or quantity * price > amount(self.config("max_order_notional")):
            raise ValueError("intent expired, future or over order limit")
        with self.transaction():
            old = self.db.execute("SELECT * FROM orders WHERE key=?", (key,)).fetchone()
            if old:
                if old["payload"] != payload:
                    raise ValueError("conflicting duplicate intent")
                return dict(old)
            self.active()
            self.db.execute("INSERT INTO orders VALUES (?,?,'accepted','0')", (key, payload))
        return self.order(key)

    def order(self, key):
        row = self.db.execute("SELECT * FROM orders WHERE key=?", (key,)).fetchone()
        if not row:
            raise ValueError("unknown intent")
        return dict(row)

    def fill(self, key, order_key, quantity, price, fee_rate, quote_at, now):
        qty, px, fee = amount(quantity), amount(price), amount(fee_rate)
        current, quote = instant(now), instant(quote_at)
        if qty <= 0 or px <= 0 or not Decimal(0) <= fee <= Decimal("0.1"):
            raise ValueError("invalid fill")
        doc = {"order_key": order_key, "quantity": str(qty), "price": str(px),
               "fee_rate": str(fee), "quote_at": quote_at, "now": now}
        payload = json.dumps(doc, sort_keys=True, separators=(",", ":"))
        with self.transaction():
            old = self.db.execute("SELECT * FROM fills WHERE key=?", (key,)).fetchone()
            if old:
                old_doc = json.loads(old["payload"])
                # A retry can arrive later; receiving time is not fill identity.
                if {k: v for k, v in old_doc.items() if k != "now"} != {k: v for k, v in doc.items() if k != "now"}:
                    raise ValueError("conflicting duplicate fill")
                return self.order(order_key)
            self.active()
            order = self.order(order_key)
            intent = json.loads(order["payload"])
            signal, expiry = instant(intent["signal_at"]), instant(intent["expires_at"])
            if (order["status"] not in ("accepted", "partial") or not signal <= quote <= current < expiry or
                    (current - quote).total_seconds() > 900):
                raise ValueError("order inactive, expired or quote stale/future")
            filled = amount(order["filled"])
            if filled + qty > amount(intent["quantity"]):
                raise ValueError("overfill")
            side, limit = intent["side"], amount(intent["limit_price"])
            if (side == "BUY" and px > limit) or (side == "SELL" and px < limit):
                raise ValueError("limit price violated")
            notional = qty * px
            previous_notional = sum((amount(item["quantity"]) * amount(item["price"]) for item in
                (json.loads(row[0]) for row in self.db.execute("SELECT payload FROM fills WHERE order_key=?", (order_key,)))), Decimal(0))
            if notional + previous_notional > amount(self.config("max_order_notional")):
                raise ValueError("fill over order notional limit")
            held = self.db.execute("SELECT quantity FROM holdings WHERE security=?", (intent["security"],)).fetchone()
            old_qty = amount(held[0]) if held else Decimal(0)
            cash = amount(self.config("cash"))
            if side == "BUY":
                cash -= notional * (1 + fee)
                new_qty = old_qty + qty
            else:
                cash += notional * (1 - fee)
                new_qty = old_qty - qty
            if cash < 0 or new_qty < 0:
                raise ValueError("insufficient cash or holding")
            status = "filled" if filled + qty == amount(intent["quantity"]) else "partial"
            self.db.execute("UPDATE config SET value=? WHERE key='cash'", (str(cash),))
            self.db.execute("INSERT INTO holdings VALUES (?,?) ON CONFLICT(security) DO UPDATE SET quantity=excluded.quantity", (intent["security"], str(new_qty)))
            self.db.execute("UPDATE orders SET filled=?, status=? WHERE key=?", (str(filled + qty), status, order_key))
            self.db.execute("INSERT INTO fills VALUES (?,?,?)", (key, order_key, payload))
        return self.order(order_key)

    def cancel(self, key):
        with self.transaction():
            order = self.order(key)
            if order["status"] in ("accepted", "partial"):
                self.db.execute("UPDATE orders SET status='cancelled' WHERE key=?", (key,))
        return self.order(key)

    def snapshot(self):
        # The four reads must describe one committed account state, even if
        # another process is writing fills to the same simulation journal.
        with self.transaction():
            return {"mode": "simulation", "real_orders": 0, "cash": self.config("cash"),
                    "stopped": self.config("stopped") == "true",
                    "holdings": {r[0]: r[1] for r in self.db.execute("SELECT security,quantity FROM holdings ORDER BY security")},
                    "orders": [dict(r) for r in self.db.execute("SELECT * FROM orders ORDER BY key")]}

    def reconcile(self, cash, holdings):
        """Compare a simulation adapter snapshot; any mismatch stops new actions."""
        expected = {k: amount(v) for k, v in holdings.items() if amount(v) != 0}
        if amount(cash) < 0 or any(v < 0 for v in expected.values()):
            raise ValueError("invalid reconciliation snapshot")
        with self.transaction():
            actual = {r[0]: amount(r[1]) for r in self.db.execute("SELECT security,quantity FROM holdings") if amount(r[1]) != 0}
            matches = amount(self.config("cash")) == amount(cash) and actual == expected
            if not matches:
                self.db.execute("UPDATE config SET value='true' WHERE key='stopped'")
        return {"matched": matches, "stopped": self.config("stopped") == "true", "real_orders": 0}

    def close(self):
        self.db.close()

    def backup(self, destination):
        """Consistent SQLite snapshot including committed WAL data; no overwrite."""
        path = Path(destination)
        if self.db.in_transaction:
            raise ValueError("backup requires a committed journal")
        path.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive reservation prevents overwriting either an existing backup
        # or the live database. Copying only the main WAL file is unsafe.
        with path.open("xb"):
            pass
        target = sqlite3.connect(str(path))
        try:
            self.db.backup(target)
            if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("backup integrity check failed")
        finally:
            target.close()
        return path
