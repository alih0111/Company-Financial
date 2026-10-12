# -*- coding: utf-8 -*-
"""گام ۲-ک-۴ P0 — تست پارس timezone تاریخی resolver.

شواهد مبنای اصلاح (audit ۲-ک-۴، فقط-خواندنی):
  برای هر ۸۳۹ نامهٔ متعارض، لحظهٔ ذخیره‌شدهٔ DB == wall خام کدال − آفست
  تاریخی IANA (DST تابستان ۲۰۲۱–۲۰۲۲) و پارسِ قبلی (+03:30 ثابت) دقیقاً
  ۶۰ دقیقه دیرتر بود.
"""
import sys
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codal_publish_resolver import (  # noqa: E402
    TEHRAN, TEHRAN_TZ_MODE, _same_instant, parse_publish_datetime)

UTC = timezone.utc
UTC_UTC = datetime(2026, 1, 1, tzinfo=UTC).utcoffset()  # sanity
TRUE_TEHRAN = ZoneInfo("Asia/Tehran")

HAS_TZDATA = TEHRAN_TZ_MODE == "iana_historical"


def test_tz_mode_is_historical_when_tzdata_available():
    # محیط این پروژه tzdata دارد؛ اگر نداشت باید صریح fallback اعلام شود
    assert TEHRAN_TZ_MODE in ("iana_historical", "fixed_0330_fallback")


def test_dst_era_letter_parses_to_true_instant():
    """نامهٔ 789108: raw «۱۴۰۰/۰۶/۲۱ ۱۴:۲۳:۰۹» → UTC 09:53:09 (DST +04:30)."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۰/۰۶/۲۱ ۱۴:۲۳:۰۹")
    assert dt is not None
    assert dt.astimezone(UTC) == datetime(2021, 9, 12, 9, 53, 9, tzinfo=UTC)
    # مقدار غلطِ قبلی (+03:30 ثابت) دقیقاً یک ساعت دیرتر بود
    assert dt.astimezone(UTC) != datetime(2021, 9, 12, 10, 53, 9, tzinfo=UTC)


def test_summer_2022_letter_also_dst():
    """نامهٔ 939705: «۱۴۰۱/۰۶/۳۰ ۱۱:۵۱:۵۶» → UTC 07:21:56 (آخرین تابستان DST)."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۱/۰۶/۳۰ ۱۱:۵۱:۵۶")
    assert dt is not None
    assert dt.astimezone(UTC) == datetime(2022, 9, 21, 7, 21, 56, tzinfo=UTC)


def test_winter_letter_unchanged():
    """زمستان: ۱۴۰۰/۱۰/۲۵ ۱۰:۰۰:۰۰ → 2022-01-15 10:00 +03:30 → 06:30Z."""
    dt = parse_publish_datetime("۱۴۰۰/۱۰/۲۵ ۱۰:۰۰:۰۰")
    assert dt is not None
    assert dt.astimezone(UTC) == datetime(2022, 1, 15, 6, 30, 0, tzinfo=UTC)


def test_post_dst_summer_2026_is_0330():
    """از ۱۴۰۲ (2023) تابستان هم +03:30 است — نامهٔ 2026 نباید DST بگیرد."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۵/۰۴/۱۹ ۱۶:۰۰:۰۰")
    assert dt is not None
    assert dt.utcoffset() == timedelta(hours=3, minutes=30)
    assert dt.astimezone(UTC) == datetime(2026, 7, 10, 12, 30, 0, tzinfo=UTC)


def test_gregorian_branch_dst_aware():
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("2021/09/12 14:23:09")
    assert dt is not None
    assert dt.astimezone(UTC) == datetime(2021, 9, 12, 9, 53, 9, tzinfo=UTC)


def test_same_instant_matches_db_for_dst_era():
    """DB لحظهٔ true را دارد؛ پارس اصلاح‌شده باید همان را تأیید کند."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    db_utc = datetime(2021, 9, 12, 9, 53, 9, tzinfo=UTC)
    fixed = datetime(2021, 9, 12, 14, 23, 9,
                     tzinfo=timezone(timedelta(hours=3, minutes=30)))
    assert _same_instant(db_utc, fixed) is False  # وضعیت ۲-ک-۳: تعارض
    parsed = parse_publish_datetime("۱۴۰۰/۰۶/۲۱ ۱۴:۲۳:۰۹")
    assert _same_instant(db_utc, parsed) is True   # بعد از اصلاح: تأیید


def test_environment_tzdata_rules_match_iana():
    """محافظ محیط: آفست Asia/Tehran روی تاریخ‌های کلیدی مطابق IANA باشد."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    assert TRUE_TEHRAN.utcoffset(datetime(2021, 9, 12, 12, tzinfo=UTC)) == \
        timedelta(hours=4, minutes=30)
    assert TRUE_TEHRAN.utcoffset(datetime(2022, 9, 23, 12, tzinfo=UTC)) == \
        timedelta(hours=3, minutes=30)
    assert TRUE_TEHRAN.utcoffset(datetime(2026, 8, 10, 12, tzinfo=UTC)) == \
        timedelta(hours=3, minutes=30)  # از ۲۰۲۳ بدون DST


def test_existing_verifications_unaffected_post_2022():
    """نامه‌های بعد از 2022-09-22: پارس جدید == پارس قدیم (بدون جابه‌جایی)."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    for raw in ("۱۴۰۴/۰۴/۲۹ ۲۱:۵۶:۵۲", "۱۴۰۵/۰۶/۲۹ ۰۹:۳۰:۰۰"):
        dt = parse_publish_datetime(raw)
        fixed = dt.astimezone(timezone(timedelta(hours=3, minutes=30)))
        assert dt.utcoffset() == fixed.utcoffset()
