"""Turn a wind reading + optional forecast into a human-readable Alert."""
from __future__ import annotations

import logging
import tempfile
from typing import Optional, Sequence

from .chart import LOCAL_TZ, generate_wind_chart
from .config import ChartConfig, ForecastConfig, LocationConfig, SpotsConfig, WindConfig, WindyConfig
from .models import Alert, ForecastPoint, WindReading, deg_to_compass
from .spots import spots_summary

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
    until_str = last_good.timestamp.astimezone(LOCAL_TZ).strftime("%H:%M")
    return f"Ennusteen mukaan tuuli pysyy sopivana ainakin klo {until_str} asti."


def _build_chart_image(
    observations: Optional[Sequence[WindReading]],
    forecast: list[ForecastPoint],
    wind_cfg: WindConfig,
    chart_cfg: Optional[ChartConfig],
    title: str,
    model_forecasts: Optional[dict[str, list[ForecastPoint]]] = None,
) -> Optional[str]:
    """Shared chart rendering for every alert type: past observations +
    forecast (mean wind + gusts), same as the original wind_start chart."""
    if chart_cfg is None or not chart_cfg.enabled or not observations:
        return None
    try:
        tmp_path = tempfile.NamedTemporaryFile(suffix=".png", delete=False).name
        return generate_wind_chart(
            observations, forecast, tmp_path, wind_cfg=wind_cfg, title=title,
            table_hours=chart_cfg.forecast_table_hours, model_forecasts=model_forecasts,
        )
    except Exception as e:  # noqa: BLE001 - a chart failure must not block the alert
        log.warning("Chart generation failed, sending alert without image: %s", e)
        return None


def _spots_section(reading: WindReading, spots_cfg: Optional[SpotsConfig]) -> Optional[str]:
    if spots_cfg is None or not spots_cfg.enabled:
        return None
    return spots_summary(
        spots_cfg.spots, reading.direction_deg,
        max_listed=spots_cfg.max_listed, favorites_only=spots_cfg.favorites_only,
    )


def windy_url(location: LocationConfig, zoom: int = 10) -> str:
    """Windy.com point forecast for the location, wind overlay on the map."""
    lat, lon = f"{location.latitude:.3f}", f"{location.longitude:.3f}"
    return f"https://www.windy.com/{lat}/{lon}?wind,{lat},{lon},{zoom}"


def _windy_line(location: LocationConfig, windy_cfg: Optional[WindyConfig]) -> Optional[str]:
    if windy_cfg is None or not windy_cfg.enabled:
        return None
    return f"🗺️ Tuulikartta ja mallivertailu: {windy_url(location, windy_cfg.zoom)}"


def build_start_alert(
    reading: WindReading,
    forecast: list[ForecastPoint],
    location: LocationConfig,
    wind_cfg: WindConfig,
    forecast_cfg: ForecastConfig,
    observations: Optional[Sequence[WindReading]] = None,
    chart_cfg: Optional[ChartConfig] = None,
    spots_cfg: Optional[SpotsConfig] = None,
    windy_cfg: Optional[WindyConfig] = None,
    model_forecasts: Optional[dict[str, list[ForecastPoint]]] = None,
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

    spots_part = _spots_section(reading, spots_cfg)
    if spots_part:
        lines.append(spots_part)
    windy_part = _windy_line(location, windy_cfg)
    if windy_part:
        lines.append(windy_part)

    image_path = _build_chart_image(
        observations, forecast, wind_cfg, chart_cfg, location.name, model_forecasts,
    )

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
    spots_cfg: Optional[SpotsConfig] = None,
    windy_cfg: Optional[WindyConfig] = None,
    model_forecasts: Optional[dict[str, list[ForecastPoint]]] = None,
) -> Alert:
    compass = deg_to_compass(reading.direction_deg)
    gust_part = f", puuskat {reading.gust_ms:.1f} m/s" if reading.gust_ms else ""
    forecast = forecast or []

    lines = [
        f"🏄 Tuuli on edelleen ajokelpoista - {location.name}.",
        f"Tuuli: {reading.speed_ms:.1f} m/s{gust_part}, suunta {compass}.",
    ]
    spots_part = _spots_section(reading, spots_cfg)
    if spots_part:
        lines.append(spots_part)
    windy_part = _windy_line(location, windy_cfg)
    if windy_part:
        lines.append(windy_part)

    image_path = _build_chart_image(
        observations, forecast, wind_cfg, chart_cfg, location.name, model_forecasts,
    )

    return Alert(
        title=f"Yhä ajokelpoista - {location.name}",
        body="\n".join(lines),
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
    model_forecasts: Optional[dict[str, list[ForecastPoint]]] = None,
) -> Alert:
    speed_part = f" ({reading.speed_ms:.1f} m/s)" if reading.speed_ms is not None else ""
    forecast = forecast or []

    image_path = None
    if wind_cfg is not None:
        image_path = _build_chart_image(
        observations, forecast, wind_cfg, chart_cfg, location.name, model_forecasts,
    )

    return Alert(
        title=f"Tuuli laantui - {location.name}",
        body=f"🌬️ Tuuli laski alle asetetun rajan{speed_part}.",
        severity="wind_stop",
        image_path=image_path,
    )
