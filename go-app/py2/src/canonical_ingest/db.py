from __future__ import annotations

import contextlib
from typing import Iterator

import psycopg

from .config import canonical_dsn


@contextlib.contextmanager
def connect() -> Iterator[psycopg.Connection]:
    """Open a canonical PostgreSQL connection. Caller manages commit/rollback."""
    conn = psycopg.connect(canonical_dsn())
    try:
        yield conn
    finally:
        conn.close()


@contextlib.contextmanager
def transaction() -> Iterator[psycopg.Connection]:
    """Open a connection in an explicit transaction; commit on success, rollback on error."""
    conn = psycopg.connect(canonical_dsn())
    try:
        with conn.transaction():
            yield conn
    finally:
        conn.close()
