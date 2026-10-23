"""Locked, atomic repository for the supported paper-account transitions."""
from __future__ import annotations

import json
import os
import threading
import math
import copy
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

_local_locks: dict[str, threading.RLock] = {}
_local_locks_guard = threading.Lock()
_lock_depth = threading.local()


def money(value) -> int:
    """Round a monetary amount expressed in toman to whole toman, HALF_UP."""
    if isinstance(value, bool):
        raise ValueError("PAPER_ACCOUNT_INVALID_MONEY")
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            raise ValueError("PAPER_ACCOUNT_INVALID_MONEY")
        return int(amount.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("PAPER_ACCOUNT_INVALID_MONEY") from None


def rial_to_toman(value) -> int:
    return money(Decimal(str(value)) / Decimal(10))


def _integer(value, code: str, *, nonnegative: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(code)
    if nonnegative and value < 0:
        raise ValueError(code)
    return value


def _number(value, code: str, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError(code)
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError(code) from None
    if not number.is_finite() or (positive and number <= 0) or (not positive and number < 0):
        raise ValueError(code)
    return number


def _validate_event(event: dict) -> None:
    if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not event["event_id"].strip():
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_ID")
    if not isinstance(event.get("type"), str) or not event["type"].strip():
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_TYPE")
    if not isinstance(event.get("at_utc"), str) or not event["at_utc"].strip():
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_TIME")
    if not isinstance(event.get("reason"), str):
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_FIELD:reason")
    if "details" not in event:
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_FIELD:details")


def validate_account(account: dict) -> None:
    if not isinstance(account, dict):
        raise ValueError("PAPER_ACCOUNT_INVALID_SCHEMA")
    required = ("account_id", "cash_toman", "initial_capital_toman", "holdings", "event_log", "accounting")
    if any(key not in account for key in required):
        raise ValueError("PAPER_ACCOUNT_REQUIRED_FIELD_MISSING")
    if not isinstance(account["account_id"], str) or not account["account_id"].strip():
        raise ValueError("PAPER_ACCOUNT_INVALID_ACCOUNT_ID")
    cash = _integer(account["cash_toman"], "PAPER_ACCOUNT_INVALID_CASH")
    if cash < 0:
        raise ValueError("PAPER_ACCOUNT_NEGATIVE_CASH")
    initial = _integer(account["initial_capital_toman"], "PAPER_ACCOUNT_INVALID_INITIAL_CAPITAL", nonnegative=True)
    holdings = account["holdings"]
    if not isinstance(holdings, list):
        raise ValueError("PAPER_ACCOUNT_INVALID_HOLDINGS")
    events = account["event_log"]
    if not isinstance(events, list):
        raise ValueError("PAPER_ACCOUNT_INVALID_EVENT_LOG")
    for event in events:
        _validate_event(event)
    ids = [event["event_id"] for event in events]
    if len(ids) != len(set(ids)):
        raise ValueError("PAPER_ACCOUNT_DUPLICATE_EVENT_ID")
    value = 0
    for holding in holdings:
        if not isinstance(holding, dict):
            raise ValueError("PAPER_ACCOUNT_INVALID_HOLDING")
        for key in ("symbol", "company_id", "purchase_at_utc", "last_price_date", "price_status"):
            if not isinstance(holding.get(key), str) or not holding[key].strip():
                raise ValueError("PAPER_ACCOUNT_HOLDING_REQUIRED_FIELD_MISSING:" + key)
        _integer(holding.get("shares"), "PAPER_ACCOUNT_INVALID_SHARE_COUNT", nonnegative=True)
        for key in ("cost_basis_toman", "fee_toman", "market_value_toman"):
            _integer(holding.get(key), "PAPER_ACCOUNT_INVALID_HOLDING_MONEY:" + key, nonnegative=True)
        _integer(holding.get("unrealized_pnl_toman"), "PAPER_ACCOUNT_INVALID_UNREALIZED_PNL")
        for key in ("purchase_price_rial", "purchase_price_toman", "last_price_rial"):
            _number(holding.get(key), "PAPER_ACCOUNT_INVALID_PRICE:" + key, positive=True)
        value += holding["market_value_toman"]
    accounting = account["accounting"]
    if not isinstance(accounting, dict):
        raise ValueError("PAPER_ACCOUNT_INVALID_ACCOUNTING")
    for key in ("holdings_value_toman", "total_value_toman", "profit_loss_toman"):
        if key not in accounting:
            raise ValueError("PAPER_ACCOUNT_ACCOUNTING_FIELD_MISSING:" + key)
    if "last_price_status" in accounting and not isinstance(accounting["last_price_status"], str):
        raise ValueError("PAPER_ACCOUNT_INVALID_ACCOUNTING_STATUS")
    holdings_value = _integer(accounting["holdings_value_toman"], "PAPER_ACCOUNT_INVALID_HOLDINGS_VALUE", nonnegative=True)
    nav = _integer(accounting["total_value_toman"], "PAPER_ACCOUNT_INVALID_NAV", nonnegative=True)
    reported_pnl = _integer(accounting["profit_loss_toman"], "PAPER_ACCOUNT_INVALID_REPORTED_PNL")
    realized = _integer(account.get("realized_pnl_toman", 0), "PAPER_ACCOUNT_INVALID_REALIZED_PNL")
    external = _integer(account.get("external_flows_toman", 0), "PAPER_ACCOUNT_INVALID_EXTERNAL_FLOWS")
    expected_pnl = cash + value - initial - external
    if holdings_value != value:
        raise ValueError("PAPER_ACCOUNT_HOLDINGS_VALUE_MISMATCH")
    if nav != cash + value:
        raise ValueError("PAPER_ACCOUNT_NAV_MISMATCH")
    if reported_pnl != expected_pnl or reported_pnl != realized + sum(h["unrealized_pnl_toman"] for h in holdings):
        raise ValueError("PAPER_ACCOUNT_PNL_MISMATCH")


@contextmanager
def account_write_lock(account_path: Path):
    """Cross-process lock; Windows mutex is released by the OS on process death."""
    key = str(account_path.resolve()).casefold()
    with _local_locks_guard:
        local_lock = _local_locks.setdefault(key, threading.RLock())
    if not local_lock.acquire(blocking=False):
        raise SystemExit("PAPER_ACCOUNT_LOCKED; no account event was written")
    try:
        depths = getattr(_lock_depth, "depths", {})
        depth = depths.get(key, 0)
        depths[key] = depth + 1
        _lock_depth.depths = depths
        if depth == 0:
            with _platform_account_lock(account_path):
                yield
        else:
            yield
    finally:
        depths = getattr(_lock_depth, "depths", {})
        if depths.get(key, 0) <= 1:
            depths.pop(key, None)
        else:
            depths[key] -= 1
        local_lock.release()


@contextmanager
def _platform_account_lock(account_path: Path):
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        kernel.WaitForSingleObject.restype = ctypes.c_uint32
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, False, "Local\\CompanyFinancialPaperAccount")
        if not handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        try:
            result = kernel.WaitForSingleObject(handle, 0)
            if result not in (0, 0x80):
                raise SystemExit("PAPER_ACCOUNT_LOCKED; no account event was written")
            yield
        finally:
            kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)
    else:
        import fcntl
        lock_path = account_path.with_suffix(account_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def write_account_atomic(account_path: Path, account: dict) -> None:
    with account_write_lock(account_path):
        validate_account(account)
        if account_path.exists():
            previous = json.loads(account_path.read_text(encoding="utf-8"))
            validate_account(previous)
            _validate_event_history(previous.get("event_log", []), account.get("event_log", []))
        _atomic_replace(account_path, account)


def _atomic_replace(account_path: Path, account: dict) -> None:
    account_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = account_path.with_suffix(account_path.suffix + ".tmp")
    payload = json.dumps(account, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, account_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_event_history(previous: list, current: list) -> None:
    snapshot = copy.deepcopy(previous)
    if not isinstance(current, list) or len(current) < len(snapshot):
        raise ValueError("PAPER_ACCOUNT_EVENT_HISTORY_REWRITE_FORBIDDEN")
    if not _json_typed_equal(current[:len(snapshot)], snapshot):
        raise ValueError("PAPER_ACCOUNT_EVENT_HISTORY_REWRITE_FORBIDDEN")
    for event in current[len(snapshot):]:
        _validate_event(event)


def _json_typed_equal(left, right) -> bool:
    """JSON equality: object key order is irrelevant; scalar types and array order matter.

    Integer and floating-point JSON numbers are kept distinct (1 != 1.0), as are
    booleans and numbers (true != 1).
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(_json_typed_equal(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(_json_typed_equal(a, b) for a, b in zip(left, right))
    return left == right


def read_modify_write(account_path: Path, mutation: Callable[[dict], object]):
    with account_write_lock(account_path):
        account = json.loads(account_path.read_text(encoding="utf-8"))
        original_events = copy.deepcopy(account.get("event_log", []))
        result = mutation(account)
        validate_account(account)
        _validate_event_history(original_events, account.get("event_log", []))
        write_account_atomic(account_path, account)
        return result
