import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core import open_meteo  # noqa: E402
from core.chart import generate_wind_chart  # noqa: E402
from core.config import HysteresisConfig, WindConfig  # noqa: E402
from core.models import ForecastPoint  # noqa: E402

MULTI = {
    "hourly": {
        "time": ["2026-10-25T12:00", "2026-10-25T13:00"],
        "wind_speed_10m_ecmwf_ifs025": [7.1, 8.4],
        "wind_gusts_10m_ecmwf_ifs025": [10.0, 12.2],
        "wind_direction_10m_ecmwf_ifs025": [135, 140],
        "wind_speed_10m_icon_seamless": [None, None],
        "wind_gusts_10m_icon_seamless": [None, None],
        "wind_direction_10m_icon_seamless": [None, None],
    }
}


def test_parse_multi_model_response_drops_empty_models():
    result = open_meteo.parse_model_forecasts(MULTI, ["ecmwf_ifs025", "icon_seamless"])
    assert list(result) == ["ecmwf_ifs025"]
    first = result["ecmwf_ifs025"][0]
    assert first.timestamp == datetime(2026, 10, 25, 12, tzinfo=timezone.utc)
    assert (first.speed_ms, first.gust_ms, first.direction_deg) == (7.1, 10.0, 135)


def test_parse_single_model_uses_unsuffixed_keys():
    data = {"hourly": {
        "time": ["2026-10-25T12:00"],
        "wind_speed_10m": [5.0], "wind_gusts_10m": [7.0], "wind_direction_10m": [200],
    }}
    result = open_meteo.parse_model_forecasts(data, ["gfs_seamless"])
    assert result["gfs_seamless"][0].speed_ms == 5.0


def test_failed_fetch_raises_open_meteo_error(monkeypatch):
    class Resp:
        status_code = 429

    monkeypatch.setattr(open_meteo.requests, "get", lambda *a, **k: Resp())
    monkeypatch.setattr(open_meteo.time, "sleep", lambda s: None)
    try:
        open_meteo.fetch_model_forecasts(61.5, 23.7, 6, ["ecmwf_ifs025"])
    except open_meteo.OpenMeteoError:
        return
    raise AssertionError("expected OpenMeteoError")


def test_chart_with_model_rows_renders():
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    fmi = [ForecastPoint(now + timedelta(hours=i), 8.0, 11.0, 135.0) for i in range(6)]
    ecmwf = [ForecastPoint(now + timedelta(hours=i), 7.0, 10.0, 140.0) for i in range(6)]
    path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
    generate_wind_chart(
        [], fmi, path, wind_cfg=WindConfig(hysteresis=HysteresisConfig()),
        table_hours=6, model_forecasts={"ecmwf_ifs025": ecmwf},
    )
    assert os.path.getsize(path) > 1000
