"""Durable, idempotent account opening; never infers trades from a backtest.

No execution adapter is enabled. A forward account can only contain its actual
recorded events, not reconstructed historical purchases. SQLite owns the state;
the public JSON is a replaceable view, never the ledger.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def tracker(db_path: Path, policy_hash: str, *, open_account=False):
    if not db_path.exists() and not open_account:
        return dict(status='NOT_STARTED', started_at_utc=None, cash_toman=None,
                    nav_toman=None, initial_toman=None, holdings=[], trades=[], events=[],
                    execution_enabled=False, automatic_updates_enabled=False)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=30) as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('PRAGMA synchronous=FULL')
        db.execute('CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, at_utc TEXT NOT NULL, '
                   'kind TEXT NOT NULL, payload TEXT NOT NULL, sha256 TEXT NOT NULL)')
        db.execute('BEGIN IMMEDIATE')
        row = db.execute("SELECT at_utc,payload,sha256 FROM events WHERE id='account-opened-v1'").fetchone()
        if row is None:
            if not open_account:
                raise RuntimeError('Existing journal has no opening event; manual recovery required')
            payload = json.dumps(dict(initial_toman=100_000_000, policy_sha256=policy_hash,
                                      inherited_historical_holdings=False), sort_keys=True)
            digest = hashlib.sha256(payload.encode()).hexdigest()
            at = utc_now()
            db.execute('INSERT INTO events VALUES (?,?,?,?,?)',
                       ('account-opened-v1', at, 'ACCOUNT_OPENED', payload, digest))
            row = (at, payload, digest)
        if hashlib.sha256(row[1].encode()).hexdigest() != row[2]:
            raise RuntimeError('Account opening checksum mismatch')
        opened = json.loads(row[1])
        if opened['policy_sha256'] != policy_hash:
            raise RuntimeError('Tracker belongs to a different policy; cannot silently switch versions')
        events = [dict(id=r[0], at_utc=r[1], kind=r[2], details=json.loads(r[3]))
                  for r in db.execute('SELECT id,at_utc,kind,payload FROM events ORDER BY rowid')]
        # Fail closed if a future writer adds events this version cannot account for.
        if len(events) != 1 or events[0]['kind'] != 'ACCOUNT_OPENED':
            raise RuntimeError('Journal has unsupported events; upgrade accounting before displaying')
        db.commit()
        backup_path = db_path.with_suffix('.backup.sqlite3')
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
    return dict(status='WAITING_FRESH_MODEL_INPUTS', started_at_utc=row[0],
                initial_toman=opened['initial_toman'], cash_toman=opened['initial_toman'],
                nav_toman=opened['initial_toman'], holdings=[], trades=[], events=events,
                execution_enabled=False, automatic_updates_enabled=False)
