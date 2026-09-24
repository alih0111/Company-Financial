import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import _db  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture
def db():
    """One connection per test, implicit transaction, rolled back at teardown."""
    conn = _db.connect_test(autocommit=False)
    try:
        yield conn
    finally:
        conn.rollback()
        conn.close()
