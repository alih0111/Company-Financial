# -*- coding: utf-8 -*-
"""گام ۲-ک-۵ P0 — تست‌های مرزی timezone/PIT روی resolver اصلاح‌شده.

حالت‌های مرزی: روزهای گذار DST (زمانِ محلی ناموجود در بهار، زمانِ محلی
مبهم در پاییز)، انتشار نزدیک cutoff، و رفتار تلورانس ۱ دقیقه‌ای
_same_instant روی همین مرزها. همهٔ تست‌ها خالص‌اند (بدون DB).
"""
import sys
import os
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from codal_publish_resolver import (  # noqa: E402
    TEHRAN, TEHRAN_TZ_MODE, _same_instant, parse_publish_datetime)

UTC = timezone.utc
HAS_TZDATA = TEHRAN_TZ_MODE == "iana_historical"


# ── روز گذار بهاری: ساعت ۰۰:۰۰–۰۰:۵۹ روز ۱۴۰۱/۰۱/۰۲ (2022-03-22) وجود ندارد ──
def test_spring_gap_nonexistent_local_time_is_deterministic():
    """زمان محلی ناموجود (gap): zoneinfo با fold=0 آفست «قبل از گذار» را
    می‌دهد؛ پارس باید deterministic و مطابق معناشناسی IANA باشد — هرگز خطا
    نمی‌دهد و هرگز +03:30 ثابت قبلی را بازتولید نمی‌کند."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۱/۰۱/۰۲ ۰۰:۳۰:۰۰")
    assert dt is not None
    u = dt.astimezone(UTC)
    # fold=0 → آفست پیش از گذار (+03:30) → 2022-03-21T21:00:00Z
    assert u == datetime(2022, 3, 21, 21, 0, 0, tzinfo=UTC)
    assert dt.utcoffset() == timedelta(hours=3, minutes=30)
    # اولین ساعت موجود پس از gap (۰۱:۰۰) با آفست تابستانی +04:30 است؛
    # ۰۱:۳۰ هم → UTC یکسان با ۰۰:۳۰ gap (معکوس‌شدن UTC، امضای کلاسیک gap)
    dt2 = parse_publish_datetime("۱۴۰۱/۰۱/۰۲ ۰۱:۳۰:۰۰")
    assert dt2.astimezone(UTC) == datetime(2022, 3, 21, 21, 0, 0, tzinfo=UTC)
    assert dt2.utcoffset() == timedelta(hours=4, minutes=30)


def test_gap_first_existing_instant_is_summer_offset():
    """یک ثانیه/یک دقیقه بعد از gap (۰۱:۰۰:۰۰): آفست +04:30 → 20:30Z."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۱/۰۱/۰۲ ۰۱:۰۰:۰۰")
    assert dt.astimezone(UTC) == datetime(2022, 3, 21, 20, 30, 0, tzinfo=UTC)
    assert dt.utcoffset() == timedelta(hours=4, minutes=30)


# ── روز گذار پاییزی: ۲۳:۰۰–۲۳:۵۹ روز ۱۴۰۱/۰۶/۳۰ (2022-09-21) دوبار رخ می‌دهد ──
def test_fall_overlap_ambiguous_local_time_uses_first_occurrence():
    """زمان محلی مبهم (overlap): fold=0 = رخ‌داد اول (+04:30 تابستانی).
    نامهٔ کدال در آن لحظه منتشر شده را رخ‌داد اول تفسیر می‌کنیم — تصمیم
    صریح و مستند، نه سکوت."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۱/۰۶/۳۰ ۲۳:۳۰:۰۰")
    assert dt is not None
    # رخ‌داد اول: 23:30 +04:30 → 19:00Z (نه 20:00Z رخ‌داد دوم)
    assert dt.astimezone(UTC) == datetime(2022, 9, 21, 19, 0, 0, tzinfo=UTC)
    assert dt.utcoffset() == timedelta(hours=4, minutes=30)


def test_fall_overlap_minute_before_is_also_summer():
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۱/۰۶/۳۰ ۲۲:۵۹:۵۹")
    assert dt.astimezone(UTC) == datetime(2022, 9, 21, 18, 29, 59, tzinfo=UTC)


def test_post_transition_winter_start_2023():
    """اولین زمستان بدون DST: ۱۴۰۱/۱۲/۲۹ ۲۴:۰۰ مرز حذف DST — از ۱۴۰۲/۰۱/۰۱
    همه‌جا +03:30."""
    if not HAS_TZDATA:
        print("skip: tzdata unavailable")
        return
    dt = parse_publish_datetime("۱۴۰۲/۰۱/۰۱ ۱۰:۰۰:۰۰")
    assert dt.utcoffset() == timedelta(hours=3, minutes=30)
    assert dt.astimezone(UTC) == datetime(2023, 3, 21, 6, 30, 0, tzinfo=UTC)


# ── انتشار نزدیک cutoff: مرز <= دقیق ─────────────────────────────────────────
def _eligibility(publish_iso: str, cutoff: datetime) -> bool:
    """همان قرارداد eligible موتور/طرح: publish_at <= cutoff (تساوی مجاز)."""
    return datetime.fromisoformat(publish_iso) <= cutoff


def test_publish_exactly_at_cutoff_is_eligible():
    cutoff = datetime(2026, 10, 8, 23, 59, 0, tzinfo=UTC)
    assert _eligibility("2026-10-08T23:59:00+00:00", cutoff) is True


def test_publish_one_second_after_cutoff_is_not_eligible():
    cutoff = datetime(2026, 10, 8, 23, 59, 0, tzinfo=UTC)
    assert _eligibility("2026-10-08T23:59:01+00:00", cutoff) is False


def test_cutoff_comparison_is_instant_not_wall_clock():
    """برابری wall-clock با آفست متفاوت ≠ برابری لحظه: 03:29+03:30 همان
    23:59Z روز قبل است و باید eligible باشد؛ این دقیقاً خطای ۲-ک-۳ بود."""
    cutoff = datetime(2026, 10, 8, 23, 59, 0, tzinfo=UTC)
    assert _eligibility("2026-10-09T03:29:00+03:30", cutoff) is True
    assert _eligibility("2026-10-09T03:30:00+03:30", cutoff) is False


# ── تلورانس ۱ دقیقه‌ای _same_instant روی مرزها ───────────────────────────────
def test_same_instant_tolerance_at_exact_and_off_by_one_minute():
    a = datetime(2022, 9, 21, 19, 0, 0, tzinfo=UTC)
    # تلورانس ۱ دقیقه «شامل مرز» است (abs(diff) <= 1min) — قرارداد فعلی موتور
    assert _same_instant(a, a + timedelta(seconds=59)) is True
    assert _same_instant(a, a + timedelta(minutes=1)) is True
    assert _same_instant(a, a + timedelta(minutes=1, seconds=1)) is False
    # جابه‌جایی ۶۰ دقیقه‌ای باگ قدیمی هرگز «یکسان» تلقی نمی‌شود
    assert _same_instant(a, a - timedelta(minutes=60)) is False


def test_same_instant_compares_instants_not_wall_clocks():
    """دو نمایش با wall-clock برابر ولی لحظهٔ متفاوت باید متفاوت باشند —
    گارد صریح علیه خطای ۲-ک-۳."""
    tehran_fixed = timezone(timedelta(hours=3, minutes=30))
    wall = datetime(2022, 6, 1, 12, 0, 0)
    as_summer = wall.replace(tzinfo=timezone(timedelta(hours=4, minutes=30)))
    as_fixed = wall.replace(tzinfo=tehran_fixed)
    assert as_summer.astimezone(UTC) != as_fixed.astimezone(UTC)
    assert _same_instant(as_summer, as_fixed) is False


def test_parser_never_returns_naive():
    for raw in ("۱۴۰۰/۰۶/۲۱ ۱۴:۲۳:۰۹", "۱۴۰۲/۰۵/۱۵ ۰۸:۰۰:۰۰",
                "2021/09/12 14:23:09", "2026/01/02 03:04:05"):
        dt = parse_publish_datetime(raw)
        if dt is not None:
            assert dt.tzinfo is not None, f"naive datetime for {raw!r}"
