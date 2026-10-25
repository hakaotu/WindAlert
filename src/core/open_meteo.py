"""Client for Open-Meteo's free forecast API (https://open-meteo.com).

Used only to compare FMI's HARMONIE forecast against other weather models
(ECMWF, ICON, GFS - the same ones Windy shows). No API key needed; the free
tier is for non-commercial use under 10 000 calls/day, and the data is
CC BY 4.0, so the chart credits Open-Meteo.

Robustness: this is a "nice to have" on top of the alert. Any failure
raises OpenMeteoError, which the caller logs and ignores - the alert must
go out with or without the comparison.
"""
from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from .models import ForecastPoint

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
ATTRIBUTION = "Mallivertailu: Open-Meteo.com (CC BY 4.0)"

# Short labels for the chart; unknown model ids are shown as-is.
MODEL_LABELS = {
    "ecmwf_ifs025": "ECMWF",
    "icon_seamless": "ICON",
    "gfs_seamless": "GFS",
}

_VARIABLES = ("wind_speed_10m", "wind_gusts_10m", "wind_direction_10m")
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}


class OpenMeteoError(RuntimeError):
    """Raised when Open-Meteo data cannot be fetched or parsed after retries."""


def model_label(model: str) -> str:
    return MODEL_LABELS.get(model, model)


def _get_with_retry(params: dict, attempts: int = 2, base_delay: float = 5.0) -> dict:
    last_exc: Optional[Exception] = None
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(OPEN_METEO_URL, params=params, timeout=20)
            if resp.status_code in _RETRYABLE_STATUSES:
                raise OpenMeteoError(f"Open-Meteo returned HTTP {resp.status_code}")
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError, OpenMeteoError) as e:
            last_exc = e
            log.warning("Open-Meteo request failed (attempt %d/%d): %s", attempt, attempts, e)
            if attempt < attempts:
                time.sleep(base_delay * (2 ** (attempt - 1)))
    raise OpenMeteoError(f"Open-Meteo request failed after {attempts} attempts: {last_exc}")


def parse_model_forecasts(data: dict, models: list[str]) -> dict[str, list[ForecastPoint]]:
    """Open-Meteo suffixes each hourly variable with the model id when
    several models are requested (wind_speed_10m_ecmwf_ifs025), and leaves
    it unsuffixed when only one is."""
    hourly = data.get("hourly") or {}
    times = [
        datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        for t in hourly.get("time", [])
    ]
    result: dict[str, list[ForecastPoint]] = {}
    for model in models:
        def column(var: str) -> list:
            key = f"{var}_{model}" if len(models) > 1 else var
            return hourly.get(key) or [None] * len(times)

        speeds, gusts, dirs = (column(v) for v in _VARIABLES)
        points = [
            ForecastPoint(timestamp=ts, speed_ms=s, gust_ms=g, direction_deg=d)
            for ts, s, g, d in zip(times, speeds, gusts, dirs)
        ]
        if any(p.speed_ms is not None for p in points):
            result[model] = points
    return result


def fetch_model_forecasts(
    latitude: float, longitude: float, hours_ahead: int, models: list[str]
) -> dict[str, list[ForecastPoint]]:
    """Hourly wind forecast per model, keyed by Open-Meteo model id."""
    if not models:
        return {}
    data = _get_with_retry(
        {
            "latitude": latitude,
            "longitude": longitude,
            "hourly": ",".join(_VARIABLES),
            "models": ",".join(models),
            "wind_speed_unit": "ms",
            "timezone": "UTC",
            "forecast_hours": hours_ahead + 1,
        }
    )
    try:
        return parse_model_forecasts(data, models)
    except (TypeError, ValueError) as e:
        raise OpenMeteoError(f"Unexpected Open-Meteo response: {e}") from e
