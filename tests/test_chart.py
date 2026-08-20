import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.chart import generate_wind_chart  # noqa: E402
from core.config import WindConfig, HysteresisConfig  # noqa: E402
from core.models import ForecastPoint, WindReading  # noqa: E402


def make_observations(n=6):
    now = datetime.now(timezone.utc)
    return [
        WindReading(
            timestamp=now - timedelta(minutes=10 * (n - i)),
            speed_ms=5.0 + i * 0.5,
            gust_ms=7.0 + i * 0.5,
            direction_deg=225.0,
        )
        for i in range(n)
    ]


def make_forecast(n=6):
    now = datetime.now(timezone.utc)
    return [
        ForecastPoint(
            timestamp=now + timedelta(hours=i),
            speed_ms=8.0,
            gust_ms=10.0,
            direction_deg=225.0,
        )
        for i in range(n)
    ]


def test_chart_generates_a_nonempty_png():
    wind_cfg = WindConfig(
        min_speed_ms=6.0, max_speed_ms=15.0, direction_filter=[],
        hysteresis=HysteresisConfig(),
    )
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "chart.png")
        result = generate_wind_chart(
            make_observations(), make_forecast(), out_path, wind_cfg=wind_cfg, title="Testi"
        )
        assert result == out_path
        assert os.path.exists(out_path)
        assert os.path.getsize(out_path) > 0


def test_chart_handles_empty_data_without_crashing():
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "chart_empty.png")
        generate_wind_chart([], [], out_path)
        assert os.path.exists(out_path)


def test_chart_handles_missing_values_without_crashing():
    obs = make_observations()
    obs[2] = WindReading(timestamp=obs[2].timestamp, speed_ms=None, gust_ms=None, direction_deg=None)
    with tempfile.TemporaryDirectory() as tmp:
        out_path = os.path.join(tmp, "chart_gap.png")
        generate_wind_chart(obs, [], out_path)
        assert os.path.exists(out_path)
