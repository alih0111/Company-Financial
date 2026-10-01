"""
Market assets collector — exchange indices + gold/commodity funds.
======================================================================
Adds two things the stock-only pipeline never carried:

  1. **Funds** (نمادهای طلا/کالا مثل مثقال و عیار): registered in the registry
     file as real canonical securities (issuer company + security + aliases),
     so they flow through the SAME read path as stocks — `/api/CompanyNames`,
     `/api/price-history`, the stock page and the price chart all work unchanged.
     Full adjusted history comes from BRS `Candlestick.php?type=3`.

  2. **Indices** (شاخص کل، شاخص کل (هم‌وزن)، …): stored in
     `market.index_observations`, NOT as securities. An index is neither a
     Company nor a tradable instrument (no ISIN, no shares), and its value is a
     level, not an IRR price. BRS exposes only the *current* snapshot
     (`Index.php?type=3`), so the series accumulates one row per trading day.

Registry: `py/market_assets.json` (refresh candidates with `discover`).

Usage:
    python py/market_assets.py ensure                 # create company/security/alias rows
    python py/market_assets.py backfill [--symbol S]  # full adjusted price history for funds
    python py/market_assets.py daily                  # today's fund prices + index snapshot
    python py/market_assets.py status                 # coverage report
    python py/market_assets.py discover               # print BRS fund candidates for the registry

Env (go-app/.env): BRS_API_KEY, DATABASE_URL, CDF_CANONICAL_DB, CDF_INGESTION_MODE.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GO_APP = SCRIPT_DIR.parent
REPO = GO_APP.parent

sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(GO_APP / "py2" / "src"))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# Reuse the proven BRS transport + Jalali/number helpers from the price collector.
from urllib import error as urlerror  # noqa: E402

from brs_prices import (  # noqa: E402
    API_BASE,
    API_KEY,
    fetch_all_symbols,
    fetch_candlestick,
    fetch_history,
    http_get_json,
    normalize_persian,
    parse_brs_date,
    to_int,
    today_jalali,
)

from canonical_ingest import CanonicalWriter, transaction  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("market_assets")

REGISTRY_PATH = SCRIPT_DIR / "market_assets.json"
FUND_SOURCE = "brs"
# Daily AllSymbols snapshot is a distinct provenance from the Candlestick history
# series: keeping separate source tags means the same-day snapshot is appended
# (not deduped away) and therefore wins the latest-observation read, while a
# history row is never mistaken for a fresh quote.
FUND_DAILY_SOURCE = "brs_daily"
HISTORY_FALLBACK_SOURCE = "brs_history"
INDEX_SOURCE = "brs_index"

# security_type for registered funds, keyed by registry "kind".
_KIND_TO_TYPE = {"gold": "gold", "commodity": "commodity", "fund": "fund", "etf": "etf"}

# A newly listed fund reports a placeholder price of 1 rial until it first trades.
# Real fund NAVs are hundreds-to-hundreds-of-thousands of rials, so anything below
# this is not a price and must never be written as an observation.
MIN_VALID_PRICE_RIAL = 100


# --------------------- registry ---------------------
def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise SystemExit(f"registry not found: {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _normalized_name(name: str) -> str:
    """Comparison key: Persian-normalized, Arabic digits folded, whitespace collapsed."""
    text = normalize_persian(name)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _scalar(cur, sql: str, params: tuple):
    cur.execute(sql, params)
    row = cur.fetchone()
    return str(row[0]) if row and row[0] is not None else None


# --------------------- identity (funds) ---------------------
def ensure_fund(cur, fund: dict) -> tuple[str, bool]:
    """Idempotently ensure issuer company + security + aliases exist.

    Returns (security_id, created). Identity is the TSETMC ins_code, then the
    exact symbol — never the display name, which is deliberately NOT used as a
    lookup key: a fund's second trading series (e.g. ناب / ناب2) shares the same
    legal name, so a name match would silently merge two distinct securities.
    """
    symbol = (fund.get("symbol") or "").strip()
    name = (fund.get("name") or symbol).strip()
    ins_code = str(fund.get("ins_code") or "").strip()
    sec_type = _KIND_TO_TYPE.get(fund.get("kind", "fund"), "fund")
    if not symbol:
        raise ValueError(f"registry fund without symbol: {fund!r}")

    sec_id = None
    if ins_code:
        sec_id = _scalar(
            cur, "SELECT id FROM core.securities WHERE tsetmc_ins_code=%s LIMIT 1", (int(ins_code),)
        )
    if not sec_id:
        sec_id = _scalar(cur, "SELECT id FROM core.securities WHERE codal_symbol=%s LIMIT 1", (symbol,))

    created = False
    if sec_id:
        # Repair/annotate an existing row (e.g. مثقال was fuzzy-matched as a stock).
        cur.execute(
            """UPDATE core.securities
               SET tsetmc_ins_code = COALESCE(tsetmc_ins_code, %s),
                   codal_symbol    = COALESCE(NULLIF(BTRIM(codal_symbol), ''), %s),
                   brs_name        = COALESCE(NULLIF(BTRIM(brs_name), ''), %s),
                   security_type   = %s,
                   is_active       = true,
                   updated_at      = now()
               WHERE id = %s""",
            (int(ins_code) if ins_code else None, symbol, name, sec_type, sec_id),
        )
    else:
        # Reuse the issuer when the same fund already has a security (multi-series);
        # otherwise create it. At most one primary security per company.
        company_id = _scalar(
            cur, "SELECT id FROM core.companies WHERE normalized_name=%s ORDER BY created_at LIMIT 1",
            (_normalized_name(name),),
        )
        has_primary = False
        if company_id:
            has_primary = bool(_scalar(
                cur, "SELECT id FROM core.securities WHERE company_id=%s AND is_primary LIMIT 1",
                (company_id,)))
        else:
            company_id = _scalar(
                cur,
                """INSERT INTO core.companies (legal_name, display_name, normalized_name)
                   VALUES (%s, %s, %s) RETURNING id""",
                (name, name, _normalized_name(name)),
            )
        sec_id = _scalar(
            cur,
            """INSERT INTO core.securities
                   (company_id, tsetmc_ins_code, codal_symbol, brs_name,
                    security_type, is_primary, is_active)
               VALUES (%s, %s, %s, %s, %s, %s, true)
               RETURNING id""",
            (company_id, int(ins_code) if ins_code else None, symbol, name, sec_type, not has_primary),
        )
        created = True

    for alias_type, alias_value in (("symbol", symbol), ("company_name", name), ("brs_name", name)):
        if not alias_value:
            continue
        cur.execute(
            """INSERT INTO core.security_aliases (security_id, alias_type, alias_value, source)
               VALUES (%s, %s, %s, 'brs')
               ON CONFLICT DO NOTHING""",
            (sec_id, alias_type, alias_value),
        )
    return sec_id, created


# --------------------- price rows ---------------------
def _fund_price_values(item: dict, gdate: str, jdate: str) -> dict:
    """Canonical price_observations values from one BRS AllSymbols item (daily)."""
    pc = to_int(item.get("pc") or item.get("Price"))
    pl = to_int(item.get("pl") or item.get("LastPrice"))
    pf = to_int(item.get("pf") or item.get("FirstPrice"))
    pmin = to_int(item.get("pmin") or item.get("LowPrice"))
    pmax = to_int(item.get("pmax") or item.get("HighPrice"))
    py = to_int(item.get("py") or item.get("YesterdayPrice"))

    closing_change = (pc - py) if (pc is not None and py is not None) else None
    closing_change_percent = (
        ((pc - py) / py * 100.0) if (pc is not None and py not in (None, 0)) else None
    )
    last_change = (pl - py) if (pl is not None and py is not None) else None
    last_change_percent = (
        ((pl - py) / py * 100.0) if (pl is not None and py not in (None, 0)) else None
    )
    return {
        "trade_date": gdate,
        "jalali_date_text": jdate,
        "price_series": "adjusted",
        "is_adjusted": True,
        "first_price_rial": pf,
        "open_price_rial": pf,
        "high_price_rial": pmax,
        "low_price_rial": pmin,
        "closing_price_rial": pc,
        "last_price_rial": pl,
        "yesterday_price_rial": py,
        "closing_change_rial": closing_change,
        "closing_change_percent": closing_change_percent,
        "last_change_rial": last_change,
        "last_change_percent": last_change_percent,
        "volume": to_int(item.get("tvol")),
        "trade_value_rial": to_int(item.get("tval")),
        "trade_count": to_int(item.get("tno")),
    }


def _candle_values(candle: dict) -> dict | None:
    """Canonical values from one Candlestick.php adjusted daily candle."""
    gdate, jdate = parse_brs_date(candle.get("date"))
    if gdate is None:
        return None
    close = to_int(candle.get("close"))
    openp = to_int(candle.get("open"))
    high = to_int(candle.get("high"))
    low = to_int(candle.get("low"))
    return {
        "trade_date": gdate,
        "jalali_date_text": jdate,
        "price_series": "adjusted",
        "is_adjusted": True,
        "adjustment_method": "candle_daily_adjusted",
        "first_price_rial": openp,
        "open_price_rial": openp,
        "high_price_rial": high,
        "low_price_rial": low,
        "closing_price_rial": close,
        "last_price_rial": close,
        "volume": to_int(candle.get("volume")),
        "trade_value_rial": None,
        "trade_count": None,
    }


def _history_row_values(row: dict) -> dict | None:
    """Canonical values from one History.php type=0 daily row (vendor, unadjusted).

    The free BRS plan caps Candlestick.php at ~10 requests/day; when that budget
    is spent this unadjusted daily series keeps fund charts populated. Rows are
    written to the canonical 'adjusted' series slot (so the standard read path
    serves them) but flagged is_adjusted=false with adjustment_method='none', and
    a later Candlestick backfill supersedes them (greater collected_at wins).
    """
    gdate, jdate = parse_brs_date(row.get("date"))
    if gdate is None:
        return None
    close = to_int(row.get("pc"))
    last = to_int(row.get("pl"))
    first = to_int(row.get("pf"))
    high = to_int(row.get("pmax"))
    low = to_int(row.get("pmin"))
    yday = to_int(row.get("py"))
    return {
        "trade_date": gdate,
        "jalali_date_text": jdate,
        "price_series": "adjusted",
        "is_adjusted": False,
        "adjustment_method": "none",
        "first_price_rial": first,
        "open_price_rial": first,
        "high_price_rial": high,
        "low_price_rial": low,
        "closing_price_rial": close,
        "last_price_rial": last,
        "yesterday_price_rial": yday,
        "closing_change_percent": to_int(row.get("pcc")),
        "last_change_percent": to_int(row.get("plp")),
        "volume": to_int(row.get("tvol")),
        "trade_value_rial": to_int(row.get("tval")),
        "trade_count": to_int(row.get("tno")),
    }


class QuotaExhausted(RuntimeError):
    """Raised when the BRS free-tier request budget for the day is spent."""


def _is_quota_error(exc: Exception) -> bool:
    return isinstance(exc, urlerror.HTTPError) and exc.code == 402


def fetch_fund_history(symbol: str) -> tuple[list[dict], str, str]:
    """Fetch fund history, preferring adjusted Candlestick.

    Returns (values, source, mode) where source is the price_observations source
    tag and mode is 'adjusted' | 'unadjusted'. Raises QuotaExhausted when both
    endpoints are out of budget.
    """
    try:
        payload = fetch_candlestick(symbol, ctype=3)
        candles = (payload or {}).get("candle_daily_adjusted") or []
        values = [v for v in (_candle_values(c) for c in candles) if v]
        values = [v for v in values if (v.get("closing_price_rial") or 0) >= MIN_VALID_PRICE_RIAL]
        if values:
            return values, FUND_SOURCE, "adjusted"
    except Exception as exc:  # noqa: BLE001
        if not _is_quota_error(exc):
            log.warning("⚠️ Candlestick failed for %s: %s", symbol, exc)
        else:
            log.info("ℹ️ Candlestick budget spent — falling back to History.php for %s", symbol)

    try:
        rows = fetch_history(symbol, 0) or []
    except Exception as exc:  # noqa: BLE001
        if _is_quota_error(exc):
            raise QuotaExhausted(symbol) from exc
        raise
        values = [v for v in (_history_row_values(r) for r in rows) if v]
    # Drop placeholder (untraded) days so a not-yet-listed series never records a 1-rial price.
    values = [v for v in values if (v.get("closing_price_rial") or 0) >= MIN_VALID_PRICE_RIAL]
    return values, HISTORY_FALLBACK_SOURCE, "unadjusted"



# --------------------- commands ---------------------
def cmd_ensure(registry: dict) -> int:
    created_total = 0
    with transaction() as conn:
        cur = conn.cursor()
        for fund in registry["funds"]:
            _, created = ensure_fund(cur, fund)
            created_total += int(created)
    log.info("✅ ensure: %d funds registered (%d newly created)", len(registry["funds"]), created_total)
    print(f"RESULT|mode=ensure|funds={len(registry['funds'])}|created={created_total}")
    return 0


def _fund_observation_count(cur, ins_code: str | None) -> int:
    if not ins_code:
        return 0
    cur.execute(
        """SELECT count(*) FROM market.price_observations p
           JOIN core.securities s ON s.id = p.security_id
           WHERE s.tsetmc_ins_code = %s""",
        (int(ins_code),),
    )
    row = cur.fetchone()
    return int(row[0]) if row else 0


def cmd_backfill(registry: dict, symbol: str | None, limit: int,
                 only_missing: bool, min_rows: int) -> int:
    """Backfill fund history. Resumable: the free BRS plan allows only ~10
    Candlestick requests/day, so this processes a bounded batch (gold first)
    and the remainder can be filled on subsequent runs."""
    funds = [f for f in registry["funds"] if not symbol or f["symbol"] == symbol]
    if symbol and not funds:
        log.error("❌ symbol %r is not in the registry", symbol)
        print(f"RESULT|mode=backfill|error=not-registered|symbol={symbol}")
        return 1

    from canonical_ingest import connect

    # Verified against the canonical DB before spending any API budget.
    pending = []
    with connect() as conn:
        cur = conn.cursor()
        for fund in funds:
            if only_missing and not symbol and _fund_observation_count(cur, fund.get("ins_code")) >= min_rows:
                continue
            pending.append(fund)
    if limit > 0:
        pending = pending[:limit]

    total_new = total_seen = failed = 0
    unadjusted = 0
    processed = 0
    quota_hit = False
    for fund in pending:
        sym = fund["symbol"]
        try:
            values, source, mode = fetch_fund_history(sym)
        except QuotaExhausted:
            quota_hit = True
            log.warning("⛔ BRS daily request budget exhausted — stopping after %d symbols", processed)
            break
        except Exception as exc:  # noqa: BLE001
            log.warning("⚠️ history fetch failed for %s: %s", sym, exc)
            failed += 1
            continue
        if not values:
            log.warning("⚠️ no candles for %s", sym)
            failed += 1
            continue

        new = 0
        with transaction() as conn:
            cur = conn.cursor()
            sec_id, _ = ensure_fund(cur, fund)
            w = CanonicalWriter(conn)
            for values_row in values:
                _id, inserted = w.insert_price_observation(
                    security_id=sec_id,
                    trade_date=values_row["trade_date"],
                    source=source,
                    values=values_row,
                    jalali_date_text=values_row["jalali_date_text"],
                    provenance={"script": "market_assets", "vendor": "brs",
                                "kind": fund.get("kind"), "mode": mode},
                )
                new += int(inserted)
        total_new += new
        total_seen += len(values)
        processed += 1
        unadjusted += int(mode == "unadjusted")
        log.info("✅ %s (%s): %d rows [%s], %d new", sym, fund["name"], len(values), mode, new)

    log.info("backfill done: processed=%d seen=%d new=%d failed=%d unadjusted_fallback=%d quota_hit=%s",
             processed, total_seen, total_new, failed, unadjusted, quota_hit)
    print(f"RESULT|mode=backfill|symbols={processed}|candles={total_seen}|inserted={total_new}"
          f"|failed={failed}|unadjusted={unadjusted}|quota_hit={int(quota_hit)}")
    return 0 if failed == 0 else 1



def _write_index_rows(rows: list[dict]) -> int:
    if not rows:
        return 0
    cols = ("index_code", "index_name", "trade_date", "jalali_date_text", "value",
            "change_value", "change_percent", "min_value", "max_value",
            "market_value_rial", "trade_count", "trade_value_rial", "trade_volume", "source")
    placeholders = ",".join(["%s"] * len(cols))
    sql = (
        f"INSERT INTO market.index_observations ({','.join(cols)}) VALUES ({placeholders}) "
        "ON CONFLICT (index_code, trade_date) DO UPDATE SET "
        "index_name=EXCLUDED.index_name, jalali_date_text=EXCLUDED.jalali_date_text, "
        "value=EXCLUDED.value, change_value=EXCLUDED.change_value, "
        "change_percent=EXCLUDED.change_percent, min_value=EXCLUDED.min_value, "
        "max_value=EXCLUDED.max_value, market_value_rial=EXCLUDED.market_value_rial, "
        "trade_count=EXCLUDED.trade_count, trade_value_rial=EXCLUDED.trade_value_rial, "
        "trade_volume=EXCLUDED.trade_volume, collected_at=now()"
    )
    with transaction() as conn:
        cur = conn.cursor()
        for r in rows:
            cur.execute(sql, tuple(r.get(c) for c in cols))
    return len(rows)


def collect_indices(registry: dict) -> int:
    by_name = {i["name"]: i["code"] for i in registry["indices"]}

    try:
        # type=3 → current level, change and intraday min/max for every index.
        snapshots = http_get_json(f"{API_BASE}/Index.php", {"key": API_KEY, "type": 3}) or []
        # type=1 → TEDPIX + equal-weight plus market-wide value/trades/volume.
        market = http_get_json(f"{API_BASE}/Index.php", {"key": API_KEY, "type": 1}) or {}
    except Exception as exc:  # noqa: BLE001
        log.error("❌ index snapshot failed: %s", exc)
        return 0

    if not isinstance(snapshots, list):
        log.error("❌ unexpected index payload: %r", type(snapshots))
        return 0

    gdate, jdate = parse_brs_date(market.get("date"))
    if gdate is None:
        gdate, jdate = today_jalali()

    rows = []
    for snap in snapshots:
        name = normalize_persian(snap.get("name"))
        code = by_name.get(name)
        if not code:
            continue
        row = {
            "index_code": code,
            "index_name": name,
            "trade_date": gdate,
            "jalali_date_text": jdate,
            "value": snap.get("index"),
            "change_value": snap.get("index_change"),
            "change_percent": snap.get("index_change_percent"),
            "min_value": snap.get("min"),
            "max_value": snap.get("max"),
            "market_value_rial": None,
            "trade_count": None,
            "trade_value_rial": None,
            "trade_volume": None,
            "source": INDEX_SOURCE,
        }
        # Market-wide turnover belongs to the headline index only.
        if code == "TEDPIX":
            row["market_value_rial"] = market.get("mv")
            row["trade_count"] = to_int(market.get("tno"))
            row["trade_value_rial"] = to_int(market.get("tval"))
            row["trade_volume"] = to_int(market.get("tvol"))
        rows.append(row)
    return _write_index_rows(rows)


def cmd_daily(registry: dict) -> int:
    # 1) indices snapshot
    n_idx = collect_indices(registry)
    log.info("✅ indices: %d rows upserted for %s", n_idx, today_jalali()[1])

    # 2) fund prices for today (one AllSymbols request for the whole market)
    symbols = {f["symbol"]: f for f in registry["funds"]}
    ins_ids = {str(f["ins_code"]): f for f in registry["funds"] if f.get("ins_code")}
    try:
        items = fetch_all_symbols()
    except Exception as exc:  # noqa: BLE001
        log.error("❌ AllSymbols fetch failed: %s", exc)
        print(f"RESULT|mode=daily|indices={n_idx}|funds=0|error=allsymbols")
        return 1

    gdate, jdate = today_jalali()
    matched = []
    for item in items:
        f = symbols.get(normalize_persian(item.get("l18"))) or ins_ids.get(str(item.get("id")))
        if f:
            matched.append((f, item))

    inserted = 0
    skipped_placeholder = 0
    with transaction() as conn:
        cur = conn.cursor()
        w = CanonicalWriter(conn)
        for fund, item in matched:
            sec_id, _ = ensure_fund(cur, fund)
            values = _fund_price_values(item, gdate, jdate)
            if values["closing_price_rial"] is None or values["closing_price_rial"] < MIN_VALID_PRICE_RIAL:
                skipped_placeholder += 1
                continue
            _id, ins = w.insert_price_observation(
                security_id=sec_id,
                trade_date=gdate,
                source=FUND_DAILY_SOURCE,
                values=values,
                jalali_date_text=jdate,
                provenance={"script": "market_assets", "vendor": "brs", "kind": fund.get("kind")},
            )
            inserted += int(ins)

    log.info("✅ funds: %d matched, %d new observations, %d untraded skipped",
             len(matched), inserted, skipped_placeholder)
    print(f"RESULT|mode=daily|indices={n_idx}|funds_matched={len(matched)}"
          f"|funds_inserted={inserted}|untraded={skipped_placeholder}")
    return 0


def cmd_status(registry: dict) -> int:
    from canonical_ingest import connect

    with connect() as conn:
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM market.index_observations")
        idx_rows = cur.fetchone()[0]
        cur.execute("SELECT count(DISTINCT index_code) FROM market.index_observations")
        idx_codes = cur.fetchone()[0]

        funds_ok = funds_empty = 0
        for fund in registry["funds"]:
            sec_id = None
            if fund.get("ins_code"):
                cur.execute("SELECT id FROM core.securities WHERE tsetmc_ins_code=%s LIMIT 1",
                            (int(fund["ins_code"]),))
                row = cur.fetchone()
                sec_id = row[0] if row else None
            if not sec_id:
                funds_empty += 1
                continue
            cur.execute("""SELECT count(*), max(trade_date) FROM market.price_observations
                           WHERE security_id=%s""", (sec_id,))
            n, last = cur.fetchone()
            if n:
                funds_ok += 1
            else:
                funds_empty += 1
        print(f"index rows: {idx_rows} across {idx_codes}/{len(registry['indices'])} codes")
        print(f"funds with price history: {funds_ok}/{len(registry['funds'])} (missing: {funds_empty})")
    print(f"RESULT|mode=status|index_rows={idx_rows}|funds_ok={funds_ok}|funds_missing={funds_empty}")
    return 0


def cmd_discover() -> int:
    """Print BRS ETF fund candidates (طلا/کالا/نقره/گلد) to refresh the registry."""
    items = fetch_all_symbols()
    etf = "صندوق سرمایه‌گذاری قابل معامله"
    out = []
    for item in items:
        name = normalize_persian(item.get("l30"))
        if normalize_persian(item.get("cs")) != etf:
            continue
        if not any(k in name for k in ("طلا", "کالا", "نقره", "گلد")):
            continue
        out.append({"symbol": normalize_persian(item.get("l18")), "name": name,
                    "ins_code": str(item.get("id")), "kind": "gold" if "طلا" in name else "commodity"})
    out.sort(key=lambda x: (x["kind"] != "gold", x["name"], x["symbol"]))
    print(json.dumps(out, ensure_ascii=False, indent=2))
    print(f"RESULT|mode=discover|candidates={len(out)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Indices + gold/commodity fund collector")
    ap.add_argument("command", choices=["ensure", "backfill", "daily", "status", "discover"])
    ap.add_argument("--symbol", help="backfill: only this registry symbol")
    ap.add_argument("--limit", type=int, default=8,
                    help="backfill: max symbols per run (free BRS plan allows ~10 history requests/day)")
    ap.add_argument("--min-rows", type=int, default=200,
                    help="backfill: treat a fund with at least this many rows as already covered")
    ap.add_argument("--all", action="store_true",
                    help="backfill: also re-fetch funds that already have history")
    args = ap.parse_args()

    if args.command == "discover":
        return cmd_discover()

    registry = load_registry()
    if not API_KEY and args.command in ("backfill", "daily"):
        log.error("❌ BRS_API_KEY is not set")
        return 2
    if args.command == "ensure":
        return cmd_ensure(registry)
    if args.command == "backfill":
        return cmd_backfill(registry, args.symbol, args.limit,
                            only_missing=not args.all, min_rows=args.min_rows)
    if args.command == "daily":
        return cmd_daily(registry)
    if args.command == "status":
        return cmd_status(registry)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
