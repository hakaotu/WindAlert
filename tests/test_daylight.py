import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import daylight  # noqa: E402

TAMPERE = (61.5177, 23.7538)
UTSJOKI = (69.9, 27.0)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def is_open(now, window) -> bool:
    return window is not None and window[0] <= now < window[1]


def tampere_window(day, hours=(6, 22), daylight_only=True, margin=120):
    return daylight.alert_window(day, *TAMPERE, hours, daylight_only, margin)


def tampere_current(now, hours=(6, 22), daylight_only=True, margin=120):
    return daylight.current_window(now, *TAMPERE, hours, daylight_only, margin)


# Published values from https://api.sunrise-sunset.org/json?lat=61.5177&lng=23.7538
# &date=<D>&formatted=0 (fetched 2026-10-26), -0.833 deg horizon, not computed
# by the code under test. Measured differences (computed minus published):
#   2026-10-25  sunrise -74 s,  sunset +62 s
#   2026-06-21  sunrise  +2 s,  sunset -17 s
#   2026-12-21  sunrise +13 s,  sunset -26 s
@pytest.mark.parametrize("day, sunrise, sunset", [
    (date(2026, 10, 25), utc(2026, 10, 25, 5, 34, 53), utc(2026, 10, 25, 14, 43, 14)),
    (date(2026, 6, 21), utc(2026, 6, 21, 0, 41, 17), utc(2026, 6, 21, 20, 12, 18)),
    (date(2026, 12, 21), utc(2026, 12, 21, 7, 42, 35), utc(2026, 12, 21, 13, 3, 26)),
])
def test_sun_times_match_reference(day, sunrise, sunset):
    got_rise, got_set = daylight.sun_times(day, *TAMPERE)
    assert abs(got_rise - sunrise) <= timedelta(minutes=3)
    assert abs(got_set - sunset) <= timedelta(minutes=3)


def test_polar_day_is_the_whole_local_day():
    rise, set_ = daylight.sun_times(date(2026, 6, 21), *UTSJOKI)
    assert rise == utc(2026, 6, 20, 21, 0)  # local midnight, EEST
    assert set_ == utc(2026, 6, 21, 21, 0)


def test_polar_night_has_no_window():
    day = date(2026, 12, 21)
    assert daylight.sun_times(day, *UTSJOKI) is None
    assert daylight.alert_window(day, *UTSJOKI, (6, 22), True, 120) is None
    for hour in (0, 6, 9, 12, 18):
        window, _ = daylight.current_window(utc(2026, 12, 21, hour), *UTSJOKI, (6, 22), True, 120)
        assert not is_open(utc(2026, 12, 21, hour), window)


def test_active_hours_are_helsinki_time():
    # Winter (EET, UTC+2): 06:30 local in, 22:30 local out.
    assert is_open(utc(2026, 11, 15, 4, 30), tampere_window(date(2026, 11, 15), daylight_only=False))
    assert not is_open(utc(2026, 11, 15, 20, 30), tampere_window(date(2026, 11, 15), daylight_only=False))
    # Summer (EEST, UTC+3): 06:30 local in, 22:30 local out.
    assert is_open(utc(2026, 7, 15, 3, 30), tampere_window(date(2026, 7, 15), daylight_only=False))
    assert not is_open(utc(2026, 7, 15, 19, 30), tampere_window(date(2026, 7, 15), daylight_only=False))


def test_six_am_cap_in_summer_tampere():
    # 05:30 EEST: the sun has been up since 03:41 local, so only the cap blocks.
    now = utc(2026, 6, 21, 2, 30)
    window, _ = tampere_current(now)
    assert not is_open(now, window)
    assert is_open(utc(2026, 6, 21, 3, 30), window)  # 06:30 EEST


def test_22_cap_on_polar_day():
    day = date(2026, 6, 21)
    window = daylight.alert_window(day, *UTSJOKI, (6, 22), True, 120)
    assert is_open(utc(2026, 6, 21, 18, 30), window)  # 21:30 EEST
    assert not is_open(utc(2026, 6, 21, 19, 30), window)  # 22:30 EEST


def test_window_ends_two_hours_before_sunset():
    # 2026-10-25: 07:35-14:43 local (sunset 14:43Z-ish, minus 2 h = 12:43Z).
    window = tampere_window(date(2026, 10, 25))
    local = [t.astimezone(daylight.LOCAL_TZ) for t in window]
    assert (local[0].hour, local[1].hour) == (7, 14)
    assert abs(window[0] - utc(2026, 10, 25, 5, 34, 53)) <= timedelta(minutes=3)
    assert abs(window[1] - utc(2026, 10, 25, 12, 43, 14)) <= timedelta(minutes=3)
    assert not is_open(utc(2026, 10, 25, 5, 0), window)  # 07:00 local, before sunrise
    assert is_open(utc(2026, 10, 25, 10, 0), window)  # 12:00 local
    for hour, minute in ((17, 15), (19, 45), (22, 5)):
        assert not is_open(utc(2026, 10, 25, hour, minute), window)


def test_window_open_inclusive_close_exclusive():
    window = tampere_window(date(2026, 10, 25))
    assert is_open(window[0], window)
    assert not is_open(window[0] - timedelta(seconds=1), window)
    assert is_open(window[1] - timedelta(seconds=1), window)
    assert not is_open(window[1], window)


def test_dst_switch_day():
    # Clocks went back on 2026-10-25: 06:00-22:00 local is 04:00Z-20:00Z that
    # day, and 03:00Z-19:00Z the day before (still EEST).
    assert tampere_window(date(2026, 10, 25), daylight_only=False) == (
        utc(2026, 10, 25, 4), utc(2026, 10, 25, 20))
    assert tampere_window(date(2026, 10, 24), daylight_only=False) == (
        utc(2026, 10, 24, 3), utc(2026, 10, 24, 19))


def test_hour_24_is_next_local_midnight():
    assert tampere_window(date(2026, 11, 15), hours=(0, 24), daylight_only=False) == (
        utc(2026, 11, 14, 22), utc(2026, 11, 15, 22))


def test_current_window_uses_helsinki_date():
    # 22:05Z on 2026-10-25 is 00:05 on 10-26 local: the window is the 26th's.
    window, _ = tampere_current(utc(2026, 10, 25, 22, 5))
    assert window[0].astimezone(daylight.LOCAL_TZ).date() == date(2026, 10, 26)


def test_follows_gap():
    _, gap = tampere_current(utc(2026, 10, 26, 7, 0))
    assert gap is True
    _, gap = tampere_current(utc(2026, 10, 26, 7, 0), hours=(0, 24), daylight_only=False)
    assert gap is False
