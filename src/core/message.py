"""Turn a wind reading + optional forecast into a human-readable Alert."""
from __future__ import annotations

import logging
import tempfile
from typing import Optional, Sequence

from .chart import generate_wind_chart
from .config import ChartConfig, ForecastConfig, LocationConfig, WindConfig
from .models import Alert, ForecastPoint, WindReading, deg_to_compass

log = logging.getLogger(__name__)


def _forecast_summary(forecast: list[ForecastPoint], wind_cfg: WindConfig) -> Optional[str]:
    """Describe how long the forecast expects wind to stay in the usable band."""
    if not forecast:
        return None

    in_band = [
        p for p in forecast
        if p.speed_ms is not None and wind_cfg.min_speed_ms <= p.speed_ms <= wind_cfg.max_speed_ms
    ]
    if not in_band:
        return "Ennusteen mukaan tuuli ei pysy sopivissa lukemissa lähituntien aikana."

    # Find the last consecutive-ish point still in band, starting from now.
    last_good = in_band[-1]
    until_str = last_good.timestamp.strftime("%H:%M")
    return f"Ennusteen mukaan tuuli pysyy sopivana ainakin klo {until_str} asti."


def _build_chart_image(
    observations: Optional[Sequence[WindReading]],
    forecast: list[ForecastPoint],
    wind_cfg: WindConfig,
    chart_cfg: Optional[ChartConfig],
    title: str,
) -> Optional[str]:
    """Shared chart rendering for every alert type: past observations +
    forecast (mean wind + gusts), same as the original wind_start chart."""
    if chart_cfg is None or not chart_cfg.enabled or not observations:
        return None
    try:
        tmp_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        return generate_wind_chart(observations, forecast, tmp_path, wind_cfg=wind_cfg, title=title)
    except Exception as e:  # noqa: BLE001 - a chart failure must not block the alert
        log.warning("Chart generation failed, sending alert without image: %s", e)
        return None


def build_start_alert(
    reading: WindReading,
    forecast: list[ForecastPoint],
    location: LocationConfig,
    wind_cfg: WindConfig,
    forecast_cfg: ForecastConfig,
    observations: Optional[Sequence[WindReading]] = None,
    chart_cfg: Optional[ChartConfig] = None,
) -> Alert:
    compass = deg_to_compass(reading.direction_deg)
    gust_part = f", puuskat {reading.gust_ms:.1f} m/s" if reading.gust_ms else ""

    lines = [
        f"🏄 Tuulee ajokelpoisesti - {location.name}!",
        f"Tuuli: {reading.speed_ms:.1f} m/s{gust_part}, suunta {compass}.",
    ]

    if forecast_cfg.enabled and forecast:
        summary = _forecast_summary(forecast, wind_cfg)
        if summary:
            lines.append(summary)

    image_path = _build_chart_image(observations, forecast, wind_cfg, chart_cfg, location.name)

    return Alert(
        title=f"Tuulihälytys - {location.name}",
        body="\n".join(lines),
        severity="wind_start",
        image_path=image_path,
    )


def build_still_alert(
    reading: WindReading,
    location: LocationConfig,
    wind_cfg: WindConfig,
    forecast: Optional[list[ForecastPoint]] = None,
    observations: Optional[Sequence[WindReading]] = None,
    chart_cfg: Optional[ChartConfig] = None,
) -> Alert:
    compass = deg_to_compass(reading.direction_deg)
    gust_part = f", puuskat {reading.gust_ms:.1f} m/s" if reading.gust_ms else ""
    forecast = forecast or []

    image_path = _build_chart_image(observations, forecast, wind_cfg, chart_cfg, location.name)

    return Alert(
        title=f"Yhä ajokelpoista - {location.name}",
        body=(
            f"🏄 Tuuli on edelleen ajokelpoista - {location.name}.\n"
            f"Tuuli: {reading.speed_ms:.1f} m/s{gust_part}, suunta {compass}."
        ),
        severity="wind_still",
        image_path=image_path,
    )


def build_stop_alert(
    reading: WindReading,
    location: LocationConfig,
    wind_cfg: Optional[WindConfig] = None,
    forecast: Optional[list[ForecastPoint]] = None,
    observations: Optional[Sequence[WindReading]] = None,
    chart_cfg: Optional[ChartConfig] = None,
) -> Alert:
    speed_part = f" ({reading.speed_ms:.1f} m/s)" if reading.speed_ms is not None else ""
    forecast = forecast or []

    image_path = None
    if wind_cfg is not None:
        image_path = _build_chart_image(observations, forecast, wind_cfg, chart_cfg, location.name)

    return Alert(
        title=f"Tuuli laantui - {location.name}",
        body=f"🌬️ Tuuli laski alle asetetun rajan{speed_part}.",
        severity="wind_stop",
        image_path=image_path,
    )
