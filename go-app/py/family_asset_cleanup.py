# -*- coding: utf-8 -*-
"""family_asset_cleanup.py — یکسان‌سازی نام/نماد دارایی‌های خانوادگی با نماد کوتاه بازار.

مشکل: سینک کارگزاری آگاه برای برخی نمادها دارایی تکراری با «نام کامل شرکت» و
«ISIN» ساخته بود (مثلاً «داروسازی کاسپین تامین» در کنار «کاسپین»)، و چون نماد
آن‌ها ISIN بود، «ثبت/سینک قیمت روزانه» آن‌ها را پیدا نمی‌کرد.

این اسکریپت idempotent است و:
  ۱) نگاشت «نام کامل → نماد کوتاه» را از snapshotهای آگاه و فهرست کانونی می‌سازد؛
  ۲) هر دارایی را به نماد کوتاه تغییرنام می‌دهد؛
  ۳) اگر نماد کوتاه از قبل دارایی دارد، رکورد تکراری در آن ادغام (holdings/prices
     منتقل) و غیرفعال می‌شود.

اجرا (پیش‌فرض فقط نمایش برنامه است):
    .venv\\Scripts\\python.exe go-app\\py\\family_asset_cleanup.py           # dry-run
    .venv\\Scripts\\python.exe go-app\\py\\family_asset_cleanup.py --apply   # اعمال
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
GO_APP = SCRIPT_DIR.parent
REPO = GO_APP.parent

# هم‌راستا با config.canonical_dsn (خواندن .env و نام دیتابیس کانونی)
sys.path.insert(0, str(GO_APP / "py2" / "src"))

import psycopg  # noqa: E402
from canonical_ingest.config import canonical_dsn  # noqa: E402

ISIN_RE = re.compile(r"^IR[A-Z0-9]{10}$")


def normalize(name: str | None) -> str:
    """همان normalizePersian در Go، به‌علاوه trim."""
    if not name:
        return ""
    return name.strip().replace("ي", "ی").replace("ك", "ک")


def is_isin(value: str | None) -> bool:
    return bool(value) and bool(ISIN_RE.match(value.strip().upper()))


def build_name_to_symbol(cur) -> dict[str, str]:
    """نگاشت نام کامل/ISIN → نماد کوتاه از snapshotهای آگاه + فهرست کانونی."""
    mapping: dict[str, str] = {}

    # canonical: brs_name/display_name/codal_symbol → codal_symbol
    cur.execute(
        """
        SELECT s.codal_symbol, s.brs_name, c.display_name
        FROM core.securities s
        LEFT JOIN core.companies c ON c.id = s.company_id
        WHERE s.is_active = true
        """
    )
    for codal, brs, display in cur.fetchall():
        for key in (normalize(brs), normalize(display), normalize(codal)):
            if key:
                mapping.setdefault(key, codal)
        mapping[normalize(codal)] = codal

    # broker snapshots (آگاه): namename/isin → securityTitle (نماد کوتاه)
    cur.execute(
        """
        SELECT payload
        FROM family.broker_snapshots
        WHERE ok = true AND payload IS NOT NULL
        ORDER BY id
        """
    )
    for (payload,) in cur.fetchall():
        holdings = (payload or {}).get("holdings") or []
        for h in holdings:
            sym = normalize(h.get("symbol"))
            if not sym or is_isin(sym):
                continue
            for key in (normalize(h.get("name")), normalize(h.get("isin"))):
                if key:
                    mapping[key] = sym
    return mapping


def load_assets(cur):
    cur.execute(
        """
        SELECT asset_id, name, COALESCE(symbol, ''), is_active
        FROM family.assets
        ORDER BY asset_id
        """
    )
    return [
        {"id": r[0], "name": normalize(r[1]), "symbol": normalize(r[2]), "active": r[3]}
        for r in cur.fetchall()
    ]


def desired_symbol(asset, mapping: dict[str, str]) -> str:
    for key in (asset["name"], asset["symbol"]):
        if key and mapping.get(key):
            return mapping[key]
    if asset["symbol"] and not is_isin(asset["symbol"]):
        return asset["symbol"]
    if asset["name"] and not is_isin(asset["name"]):
        return asset["name"]
    return ""


def plan_actions(assets, mapping):
    """برای هر دارایی فعال اقدام (rename/merge/skip) تعیین می‌کند."""
    by_key: dict[str, list[dict]] = {}
    for a in assets:
        if a["active"]:
            for k in {a["name"], a["symbol"]} - {""}:
                by_key.setdefault(k, []).append(a)

    actions = []
    planned_targets: set[int] = set()
    for a in assets:
        if not a["active"]:
            continue
        want = desired_symbol(a, mapping)
        if not want:
            actions.append(("skip", a, None, ""))
            continue

        # دارایی دیگری که از قبل این نماد کوتاه را دارد؟
        target = None
        for cand in by_key.get(want, []):
            if cand["id"] != a["id"] and cand["active"]:
                target = cand
                break

        if target is not None and target["id"] not in planned_targets:
            actions.append(("merge", a, target, want))
            planned_targets.add(target["id"])
        elif a["name"] == want and a["symbol"] == want:
            actions.append(("skip", a, None, want))
        else:
            actions.append(("rename", a, None, want))
    return actions


def move_holdings(cur, src_id: int, dst_id: int) -> int:
    """holdings منبع را در مقصد ادغام (جمع تعداد/بهای) و منبع را پاک می‌کند."""
    cur.execute("SELECT person_id, quantity, cost_basis FROM family.holdings WHERE asset_id = %s", (src_id,))
    rows = cur.fetchall()
    for person_id, qty, cost in rows:
        cur.execute(
            """
            INSERT INTO family.holdings (person_id, asset_id, quantity, cost_basis)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (person_id, asset_id) DO UPDATE SET
                quantity = family.holdings.quantity + EXCLUDED.quantity,
                cost_basis = family.holdings.cost_basis + EXCLUDED.cost_basis
            """,
            (person_id, dst_id, qty, cost),
        )
    cur.execute("DELETE FROM family.holdings WHERE asset_id = %s", (src_id,))
    return len(rows)


def move_prices(cur, src_id: int, dst_id: int) -> int:
    """قیمت‌های منبع را به مقصد منتقل می‌کند (بدون بازنویسی قیمت موجود)."""
    cur.execute(
        """
        INSERT INTO family.prices (date_key, asset_id, price)
        SELECT date_key, %s, price FROM family.prices WHERE asset_id = %s
        ON CONFLICT (date_key, asset_id) DO UPDATE
            SET price = EXCLUDED.price
            WHERE family.prices.price IS NULL
        """,
        (dst_id, src_id),
    )
    moved = cur.rowcount
    cur.execute("DELETE FROM family.prices WHERE asset_id = %s", (src_id,))
    return moved


def apply_actions(conn, actions):
    cur = conn.cursor()
    for kind, a, target, want in actions:
        if kind == "skip":
            continue
        if kind == "rename":
            cur.execute(
                "UPDATE family.assets SET name = %s, symbol = %s WHERE asset_id = %s",
                (want, want, a["id"]),
            )
            print(f"rename  #{a['id']:<3} {a['name']!r} -> {want!r}")
        elif kind == "merge":
            h = move_holdings(cur, a["id"], target["id"])
            p = move_prices(cur, a["id"], target["id"])
            cur.execute(
                "UPDATE family.assets SET name = %s, symbol = %s, is_active = false WHERE asset_id = %s",
                (want, want, a["id"]),
            )
            print(
                f"merge   #{a['id']:<3} {a['name']!r} -> #{target['id']} {want!r} "
                f"(holdings={h}, prices={p})"
            )
    conn.commit()
    cur.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="اعمال تغییرات (پیش‌فرض dry-run)")
    args = parser.parse_args()

    dsn = canonical_dsn()
    db_name = dsn.rstrip("/").rsplit("/", 1)[-1]
    print(f"database: {db_name}")
    print(f"mode: {'APPLY' if args.apply else 'DRY-RUN'}")

    with psycopg.connect(dsn) as conn:
        cur = conn.cursor()
        mapping = build_name_to_symbol(cur)
        assets = load_assets(cur)
        actions = plan_actions(assets, mapping)

        print(f"\nactive assets: {sum(1 for a in assets if a['active'])}")
        print("plan:")
        for kind, a, target, want in actions:
            if kind == "skip":
                continue
            arrow = f" -> #{target['id']} {want!r}" if target else f" -> {want!r}"
            print(f"  {kind:<6} #{a['id']:<3} name={a['name']!r} symbol={a['symbol']!r}{arrow}")

        if args.apply:
            apply_actions(conn, actions)
            print("\napplied.")
        else:
            print("\ndry-run only (pass --apply to write).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
