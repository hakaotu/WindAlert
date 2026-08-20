"""Load and validate config.yaml.

Design choices worth noting:
- Secrets (tokens, phone numbers) are referenced as ${ENV_VAR} inside the
  YAML and resolved from the environment at load time. This means
  config.yaml itself is always safe to commit to a public repo.
- We fail loudly and immediately if something required is missing, rather
  than limping along and failing silently three hours later on a cron run
  nobody is watching.
"""
from __future__ import annotations

import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ConfigError(RuntimeError):
    """Raised for any problem with the user's configuration."""


def _resolve_env_vars(value: Any) -> Any:
    """Recursively replace ${VAR_NAME} with the environment variable value."""
    if isinstance(value, str):
        def replace(match: "re.Match[str]") -> str:
            var_name = match.group(1)
            resolved = os.environ.get(var_name)
            if resolved is None:
                raise ConfigError(
                    f"Config references ${{{var_name}}} but that environment "
                    f"variable is not set. Set it as a secret / in your .env file."
                )
            return resolved
        return _ENV_VAR_PATTERN.sub(replace, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


@dataclass
class HysteresisConfig:
    trigger_margin_ms: float = 0.5
    release_margin_ms: float = 1.0
    min_minutes_above: int = 10


@dataclass
class WindConfig:
    min_speed_ms: float = 6.0
    max_speed_ms: float = 25.0
    direction_filter: list[str] = field(default_factory=list)
    hysteresis: HysteresisConfig = field(default_factory=HysteresisConfig)


@dataclass
class LocationConfig:
    name: str
    latitude: float
    longitude: float
    fmi_station_id: Optional[int] = None


@dataclass
class ForecastConfig:
    enabled: bool = True
    hours_ahead: int = 6


@dataclass
class ChartConfig:
    enabled: bool = False
    lookback_hours: int = 8


@dataclass
class ScheduleConfig:
    active_hours: str = "0-23"
    poll_interval_minutes: int = 10

    def active_hours_range(self) -> tuple[int, int]:
        start, end = self.active_hours.split("-")
        return int(start), int(end)


@dataclass
class NotifierChannelConfig:
    type: str
    enabled: bool
    options: dict = field(default_factory=dict)


@dataclass
class TelemetryConfig:
    enabled: bool = False
    endpoint: Optional[str] = None


@dataclass
class AppConfig:
    location: LocationConfig
    wind: WindConfig
    forecast: ForecastConfig
    chart: ChartConfig
    schedule: ScheduleConfig
    channels: list[NotifierChannelConfig]
    telemetry: TelemetryConfig
    state_path: str = "~/.wingfoil_alert_state.json"


def load_config(path: str) -> AppConfig:
    if not os.path.exists(path):
        raise ConfigError(
            f"Config file not found: {path}. "
            f"Copy config.example.yaml to config.yaml and edit it first."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if not raw:
        raise ConfigError(f"Config file {path} is empty.")

    try:
        raw = _resolve_env_vars(raw)

        loc = raw["location"]
        location = LocationConfig(
            name=loc["name"],
            latitude=float(loc["latitude"]),
            longitude=float(loc["longitude"]),
            fmi_station_id=loc.get("fmi_station_id"),
        )

        wind_raw = raw.get("wind", {})
        hyst_raw = wind_raw.get("hysteresis", {})
        wind = WindConfig(
            min_speed_ms=float(wind_raw.get("min_speed_ms", 6.0)),
            max_speed_ms=float(wind_raw.get("max_speed_ms", 25.0)),
            direction_filter=list(wind_raw.get("direction_filter", []) or []),
            hysteresis=HysteresisConfig(
                trigger_margin_ms=float(hyst_raw.get("trigger_margin_ms", 0.5)),
                release_margin_ms=float(hyst_raw.get("release_margin_ms", 1.0)),
                min_minutes_above=int(hyst_raw.get("min_minutes_above", 10)),
            ),
        )

        forecast_raw = raw.get("forecast", {})
        forecast = ForecastConfig(
            enabled=bool(forecast_raw.get("enabled", True)),
            hours_ahead=int(forecast_raw.get("hours_ahead", 6)),
        )

        chart_raw = raw.get("chart", {})
        chart = ChartConfig(
            enabled=bool(chart_raw.get("enabled", False)),
            lookback_hours=int(chart_raw.get("lookback_hours", 8)),
        )

        sched_raw = raw.get("schedule", {})
        schedule = ScheduleConfig(
            active_hours=str(sched_raw.get("active_hours", "0-23")),
            poll_interval_minutes=int(sched_raw.get("poll_interval_minutes", 10)),
        )

        channels = []
        for ch in raw.get("notifications", {}).get("channels", []):
            channels.append(
                NotifierChannelConfig(
                    type=ch["type"],
                    enabled=bool(ch.get("enabled", False)),
                    options={k: v for k, v in ch.items() if k not in ("type", "enabled")},
                )
            )
        if not any(c.enabled for c in channels):
            raise ConfigError(
                "No notification channel is enabled in config.yaml. "
                "Enable at least one under notifications.channels."
            )

        tel_raw = raw.get("telemetry", {})
        telemetry = TelemetryConfig(
            enabled=bool(tel_raw.get("enabled", False)),
            endpoint=tel_raw.get("endpoint"),
        )

        return AppConfig(
            location=location,
            wind=wind,
            forecast=forecast,
            chart=chart,
            schedule=schedule,
            channels=channels,
            telemetry=telemetry,
            state_path=raw.get("state_path", "~/.wingfoil_alert_state.json"),
        )
    except KeyError as e:
        raise ConfigError(f"Missing required config key: {e}") from e


def load_config_or_exit(path: str) -> AppConfig:
    """Convenience wrapper for main.py: print a clean error and exit(1)
    instead of a raw traceback, since this runs unattended in cron/Actions."""
    try:
        return load_config(path)
    except ConfigError as e:
        print(f"[CONFIG ERROR] {e}", file=sys.stderr)
        sys.exit(1)
