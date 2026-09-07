import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.config import ChartConfig, HysteresisConfig, LocationConfig, WindConfig  # noqa: E402
from core.models import ForecastPoint, WindReading  # noqa: E402
from core import message  # noqa: E402


def make_wind_cfg() -> WindConfig:
    return WindConfig(min_speed_ms=6.0, max_speed_ms=15.0, hysteresis=HysteresisConfig())


def make_observations(n=6):
    now = datetime.now(timezone.utc)
    return [
        WindReading(timestamp=now - timedelta(minutes=10 * (n - i)), speed_ms=7.0, gust_ms=9.0, direction_deg=225.0)
        for i in range(n)
    ]


def make_forecast(n=3):
    now = datetime.now(timezone.utc)
    return [
        ForecastPoint(timestamp=now + timedelta(hours=i), speed_ms=7.0, gust_ms=9.0, direction_deg=225.0)
        for i in range(1, n + 1)
    ]


def test_still_alert_attaches_chart_when_enabled():
    loc = LocationConfig(name="Testi", latitude=60.0, longitude=25.0)
    observations = make_observations()
    alert = message.build_still_alert(
        observations[-1], loc, make_wind_cfg(),
        forecast=make_forecast(), observations=observations, chart_cfg=ChartConfig(enabled=True),
    )
    assert alert.image_path is not None
    assert os.path.exists(alert.image_path)


def test_stop_alert_attaches_chart_when_enabled():
    loc = LocationConfig(name="Testi", latitude=60.0, longitude=25.0)
    observations = make_observations()
    alert = message.build_stop_alert(
        observations[-1], loc, make_wind_cfg(),
        forecast=make_forecast(), observations=observations, chart_cfg=ChartConfig(enabled=True),
    )
    assert alert.image_path is not None
    assert os.path.exists(alert.image_path)


def test_still_alert_has_no_chart_when_disabled():
    loc = LocationConfig(name="Testi", latitude=60.0, longitude=25.0)
    observations = make_observations()
    alert = message.build_still_alert(
        observations[-1], loc, make_wind_cfg(),
        forecast=make_forecast(), observations=observations, chart_cfg=ChartConfig(enabled=False),
    )
    assert alert.image_path is None


def test_stop_alert_has_no_chart_when_chart_cfg_missing():
    loc = LocationConfig(name="Testi", latitude=60.0, longitude=25.0)
    alert = message.build_stop_alert(make_observations()[-1], loc)
    assert alert.image_path is None
