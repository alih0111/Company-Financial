"""Refresh the chart database from dated, settled TSETMC daily bars."""
import datetime as dt
import gzip
import hashlib
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

import jdatetime
import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ranking_research.future_eval_v12_30.http_retry import open_readonly, ReadOnlyRateLimitedError

TEHRAN = ZoneInfo("Asia/Tehran")
SOURCE = "tsetmc_chart_daily"
INSERT = """
    INSERT INTO market.price_observations
    (security_id, trade_date, jalali_date_text, price_series, source, source_url,
     adjustment_method, observation_hash, open_price_rial, first_price_rial,
     high_price_rial, low_price_rial, closing_price_rial, last_price_rial, yesterday_price_rial,
     volume, trade_value_rial, trade_count, closing_change_percent)
    VALUES (%s,%s,%s,'adjusted',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    ON CONFLICT DO NOTHING
"""


def cached_receipts(cutoff):
    directory = ROOT / ".runtime/factormix-monthly-paper/market"
    for manifest in sorted(directory.glob(f"{cutoff}*/manifest.json"), reverse=True):
        doc = json.loads(manifest.read_bytes())
        if cutoff.isoformat() in doc["latest_quote_dates"]:
            return {r["security_id"]: r["sources"]["daily"] for r in doc["records"]
                    if r["status"] == "complete"}
    return {}


def daily_rows(code, receipt):
    url = f"https://cdn.tsetmc.com/api/ClosingPrice/GetClosingPriceDailyList/{code}/0"
    if receipt and receipt["url"] == url:
        with gzip.open(ROOT / receipt["raw_path"]) as file:
            body = file.read()
        if hashlib.sha256(body).hexdigest() != receipt["raw_sha256"]:
            raise ValueError("market receipt hash mismatch")
    else:
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://cdn.tsetmc.com/"})
        response, _, _ = open_readonly(request)
        with response:
            body = response.read()
    rows = json.loads(body)["closingPriceDaily"]
    if not rows or any(str(r["insCode"]) != code for r in rows):
        raise ValueError("missing or mismatched instrument history")
    return rows, url


def stale_row(stored_rows, day, close):
    """True when the currently-served adjusted close disagrees with the recomputed one.

    Corporate actions (capital increases, ...) reset the exchange reference price;
    rows stored before the event keep the old scale forever because the table is
    append-only. Recomputing the full back-adjusted chain and re-emitting only the
    disagreeing days lets the chart's DISTINCT ON (collected_at DESC) pick up the
    corrected versions without rewriting unrelated history on every run.
    """
    stored = stored_rows.get(day)
    return (stored is None
            or abs(close - float(stored["closing_price_rial"] or 0)) > 0.001 * close)


def gap_rows(sid, url, stored_rows, chain, factors):
    """Rescale stored-only days into the settled chain's scale.

    Halt days carry no settled bar in the TSETMC chain, but the broker collector
    still stores a candle for them. Such a day keeps whatever scale was current
    when it was stored, so after a capital increase it surfaces as a fake cliff
    between two chain days. Rescale its prices by the chain factor whose result
    sits closest to the next trading day and require continuity. A degenerate
    stored row (halt day, canceled session or broken candle far off its own
    reference price) has no usable scale at all: fill it with the previous
    close once both chain neighbours agree, otherwise leave the day untouched.
    """
    chain_days = sorted(chain)
    for day in sorted(stored_rows):
        if day in chain or not chain_days or not chain_days[0] < day < chain_days[-1]:
            continue
        stored = stored_rows[day]
        base = stored["closing_price_rial"]
        if not base or base <= 0:
            continue
        newer = next(d for d in chain_days if d > day)
        older = max((d for d in chain_days if d < day), default=None)
        target = float(chain[newer])
        reference = stored["yesterday_price_rial"]
        # A close far off its own reference marks a canceled or broken session:
        # within exchange bands no settled bar can move that far in a day, and
        # rescaling such a candle would only preserve its garbage prices.
        broken = (reference is None
                  or abs(float(base) - float(reference)) > 0.2 * float(reference))
        if broken:
            # Degenerate stored rows (halt day, canceled session or broken
            # candle) hold no usable scale. On such a day the traded price
            # equals the previous close, so fill it from the chain once both
            # neighbours agree on the scale; otherwise leave it alone.
            if older is None or abs(float(chain[older]) - target) > 0.15 * target:
                continue
            value = float(chain[older])
            fields = (value, value, value, value, value, value,
                      value, stored["volume"], stored["trade_value_rial"],
                      stored["trade_count"], 0.0)
        else:
            factor = min(factors, key=lambda f: abs(float(base) * f - target))
            if abs(float(base) * factor - target) > 0.15 * target:
                continue
            def rescaled(value):
                return round(float(value) * factor, 4) if value and value > 0 else None
            fields = (rescaled(stored["open_price_rial"]), rescaled(stored["first_price_rial"]),
                      rescaled(stored["high_price_rial"]), rescaled(stored["low_price_rial"]),
                      rescaled(base), rescaled(stored["last_price_rial"]),
                      rescaled(reference), stored["volume"],
                      stored["trade_value_rial"], stored["trade_count"],
                      stored["closing_change_percent"])
        # default=str keeps Decimal pass-through fields deterministic for the hash.
        digest = hashlib.sha256(json.dumps(fields, default=str).encode()).hexdigest()
        yield (sid, day, stored["jalali_date_text"]
               or jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d"),
               SOURCE, url, "local_heuristic", digest, *fields)


def chart_rows(sid, raw, url, cutoff, watermark, stored_rows):
    bars = sorted((r for r in raw if str(r["dEven"]) <= cutoff.strftime("%Y%m%d")
                   and r["pClosing"] > 0 and r["zTotTran"] > 0), key=lambda r: r["dEven"])
    if not bars:
        raise ValueError("no settled trade in source")
    factor = 1.0
    chain = {}
    factors = set()
    for i in range(len(bars) - 1, -1, -1):
        bar = bars[i]
        day = dt.date.fromisoformat(str(bar["dEven"]))
        def adjusted(key):
            value = bar[key]
            return round(value * factor, 4) if value > 0 else None
        opening = adjusted("priceFirst")
        yesterday = adjusted("priceYesterday")
        # The exchange reference price is already corporate-action adjusted, so it
        # is the honest denominator for the event day's change percent too.
        change = round(100 * (bar["pClosing"] / bar["priceYesterday"] - 1), 4) if bar["priceYesterday"] > 0 else None
        close = adjusted("pClosing")
        chain[day] = close
        factors.add(factor)
        if watermark is None or day >= watermark or stale_row(stored_rows, day, close):
            fields = (opening, opening, adjusted("priceMax"), adjusted("priceMin"), close,
                      adjusted("pDrCotVal"), yesterday, int(bar["qTotTran5J"]),
                      bar["qTotCap"], int(bar["zTotTran"]), change)
            digest = hashlib.sha256(json.dumps(fields).encode()).hexdigest()
            yield (sid, day, jdatetime.date.fromgregorian(date=day).strftime("%Y/%m/%d"),
                   SOURCE, url, "local_heuristic", digest, *fields)
        if i and bar["priceYesterday"] > 0 and bar["priceYesterday"] != bars[i-1]["pClosing"]:
            # Back-adjust earlier prices across the exchange's reference-price reset.
            factor *= bar["priceYesterday"] / bars[i-1]["pClosing"]
    yield from gap_rows(sid, url, stored_rows, chain, factors)


def vendor_rows(sid, symbol, cutoff, watermark, stored_rows):
    sys.path.insert(0, str(ROOT / "go-app/py"))
    import brs_prices as brs
    payload = brs.fetch_candlestick(symbol, 3)
    if (brs.normalize_persian(payload.get("l18")) != brs.normalize_persian(symbol)
            or str(payload.get("type")) != "3" or not payload.get("candle_daily_adjusted")):
        raise ValueError("missing adjusted candles for the requested symbol")
    previous = None
    for bar in sorted(payload["candle_daily_adjusted"], key=lambda item: item["date"]):
        gregorian, jalali = brs.parse_brs_date(bar["date"])
        day = dt.date.fromisoformat(gregorian)
        close = brs.to_int(bar["close"])
        if day > cutoff or not close or close <= 0:
            continue
        if watermark is None or day >= watermark or stale_row(stored_rows, day, close):
            opening, high, low, volume = (brs.to_int(bar[key]) for key in ("open", "high", "low", "volume"))
            if not low or not high or not low <= close <= high or volume is None or volume < 0:
                raise ValueError("invalid adjusted candle")
            change = round(100 * (close / previous - 1), 4) if previous else None
            fields = (opening, opening, high, low, close, close, previous, volume, None, None, change)
            digest = hashlib.sha256(json.dumps(fields).encode()).hexdigest()
            yield (sid, day, jalali, "brs_chart_candles", brs.API_BASE + "/Candlestick.php",
                   "candle_daily_adjusted", digest, *fields)
        previous = close


def stored_rows(conn, sid):
    """Latest currently-served adjusted row per day, across every source."""
    rows = conn.execute("""
        SELECT DISTINCT ON (po.trade_date) po.trade_date, po.jalali_date_text,
               po.open_price_rial, po.first_price_rial, po.high_price_rial,
               po.low_price_rial, po.closing_price_rial, po.last_price_rial,
               po.yesterday_price_rial, po.volume, po.trade_value_rial,
               po.trade_count, po.closing_change_percent
        FROM market.price_observations po
        WHERE po.security_id=%s AND po.price_series='adjusted'
        ORDER BY po.trade_date, po.collected_at DESC, po.id DESC
    """, (sid,)).fetchall()
    names = ("trade_date", "jalali_date_text", "open_price_rial", "first_price_rial",
             "high_price_rial", "low_price_rial", "closing_price_rial", "last_price_rial",
             "yesterday_price_rial", "volume", "trade_value_rial", "trade_count",
             "closing_change_percent")
    return {row[0]: dict(zip(names, row)) for row in rows}


def main():
    load_dotenv(ROOT / "go-app/.env")
    local = dt.datetime.now(TEHRAN)
    cutoff = local.date() if local.hour >= 17 else local.date() - dt.timedelta(days=1)
    cache = cached_receipts(cutoff)
    failures = inserted = 0
    with psycopg.connect(os.environ["DATABASE_URL"].replace("postgresql+psycopg:", "postgresql:"),
                         dbname=os.environ["CDF_CANONICAL_DB"], autocommit=True) as conn:
        targets = conn.execute("""
            SELECT s.id, s.codal_symbol, s.tsetmc_ins_code
            FROM core.securities s WHERE s.is_active ORDER BY s.codal_symbol
        """).fetchall()
        if not targets:
            raise RuntimeError("empty chart universe")
        for sid, symbol, code in targets:
            try:
                marks = stored_rows(conn, sid)
                watermark = max(marks, default=None)
                if not str(code).isdigit():
                    raise ValueError("missing instrument code")
                try:
                    raw, url = daily_rows(str(code), cache.get(str(sid)))
                    records = chart_rows(sid, raw, url, cutoff, watermark, marks)
                except urllib.error.HTTPError as exc:
                    if exc.code not in (404, 500, 502, 503, 504):
                        raise
                    records = vendor_rows(sid, symbol, cutoff, watermark, marks)
                with conn.transaction(), conn.cursor() as cursor:
                    cursor.executemany(INSERT, records)
                    inserted += cursor.rowcount
            except ReadOnlyRateLimitedError:
                raise
            except Exception as exc:
                failures += 1
                print(symbol, type(exc).__name__, flush=True)
        print(f"targets={len(targets)} inserted={inserted} failed={failures} cutoff={cutoff}", flush=True)
    return int(failures > 0)


if __name__ == "__main__":
    sys.exit(main())

