"""Alert window: when alerts may be sent, in daylight and inside active hours.

Why this exists: alerts are only useful while there is light to be on the
water, so the window is [max(sunrise, start hour), min(sunset - margin, end
hour)) in Europe/Helsinki time. Sunrise and sunset are computed locally with
the standard sunrise equation (NOAA/Meeus simplified form) so the gate can
never fail on a network error. Everything here is pure: callers pass the
date or the clock in, nothing reads the system time.

The window includes its opening instant and excludes its closing instant.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

# FMI only covers Finland, so "local time" is always Helsinki.
LOCAL_TZ = ZoneInfo("Europe/Helsinki")

Window = tuple[datetime, datetime]


def _sin(deg: float) -> float:
    return math.sin(math.radians(deg))


def _cos(deg: float) -> float:
    return math.cos(math.radians(deg))


def _local_midnight_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ).astimezone(timezone.utc)


def _julian_to_utc(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - 2440587.5) * 86400, tz=timezone.utc)


def sun_times(day: date, latitude: float, longitude: float) -> Optional[Window]:
    """(sunrise_utc, sunset_utc) for a Helsinki local date; longitude is east-positive.

    Polar day returns the whole local day (the sun never sets), polar night
    returns None.
    """
    n = day.toordinal() - date(2000, 1, 1).toordinal()  # integer day count
    j_star = n - longitude / 360
    m = (357.5291 + 0.98560028 * j_star) % 360
    c = 1.9148 * _sin(m) + 0.0200 * _sin(2 * m) + 0.0003 * _sin(3 * m)
    lam = (m + c + 180 + 102.9372) % 360
    j_transit = 2451545.0 + j_star + 0.0053 * _sin(m) - 0.0069 * _sin(2 * lam)
    sin_d = _sin(lam) * _sin(23.4397)
    cos_d = math.sqrt(1 - sin_d ** 2)
    cos_w0 = (_sin(-0.833) - _sin(latitude) * sin_d) / (_cos(latitude) * cos_d)
    if cos_w0 < -1:
        return _local_midnight_utc(day), _local_midnight_utc(day + timedelta(days=1))
    if cos_w0 > 1:
        return None
    w0 = math.degrees(math.acos(cos_w0))
    return _julian_to_utc(j_transit - w0 / 360), _julian_to_utc(j_transit + w0 / 360)


def alert_window(
    day: date,
    latitude: float,
    longitude: float,
    active_hours: tuple[int, int],
    daylight_only: bool,
    sunset_margin_minutes: int,
) -> Optional[Window]:
    """The [open, close) alert window (UTC) for a Helsinki local date, or None if empty."""
    start_h, end_h = active_hours
    midnight = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    # Wall-clock arithmetic on a zoned datetime, so DST shifts apply and hour
    # 24 lands on the next local midnight.
    open_at = (midnight + timedelta(hours=start_h)).astimezone(timezone.utc)
    close_at = (midnight + timedelta(hours=end_h)).astimezone(timezone.utc)

    if daylight_only:
        sun = sun_times(day, latitude, longitude)
        if sun is None:
            return None
        open_at = max(open_at, sun[0])
        close_at = min(close_at, sun[1] - timedelta(minutes=sunset_margin_minutes))

    if open_at >= close_at:
        return None
    return open_at, close_at


def current_window(
    now_utc: datetime,
    latitude: float,
    longitude: float,
    active_hours: tuple[int, int],
    daylight_only: bool,
    sunset_margin_minutes: int,
) -> tuple[Optional[Window], bool]:
    """(window for now's Helsinki date, follows_gap).

    follows_gap is True when the previous day's window closed before this
    one opened (or one of them does not exist), i.e. there was a closed
    period in between. The caller checks window[0] <= now_utc < window[1].
    """
    day = now_utc.astimezone(LOCAL_TZ).date()
    args = (latitude, longitude, active_hours, daylight_only, sunset_margin_minutes)
    window = alert_window(day, *args)
    prev = alert_window(day - timedelta(days=1), *args)
    follows_gap = prev is None or window is None or prev[1] < window[0]
    return window, follows_gap
