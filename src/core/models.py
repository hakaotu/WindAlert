"""Core data structures shared across the whole application.

Keeping these as plain dataclasses (no FMI-specific or Telegram-specific
fields) is what lets fetchers and notifiers stay decoupled from each other.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


class AlertState(str, Enum):
    IDLE = "IDLE"
    ALERTED = "ALERTED"


@dataclass
class WindReading:
    """A single wind observation point."""
    timestamp: datetime
    speed_ms: Optional[float]
    gust_ms: Optional[float]
    direction_deg: Optional[float]

    @property
    def is_valid(self) -> bool:
        return self.speed_ms is not None


@dataclass
class ForecastPoint:
    timestamp: datetime
    speed_ms: Optional[float]
    gust_ms: Optional[float]
    direction_deg: Optional[float]


@dataclass
class Alert:
    """A fully-formed notification, ready to hand to any Notifier plugin.

    Notifier implementations must not need to know anything about wind,
    FMI, or hysteresis to send this - it's just text (+ optional image).
    """
    title: str
    body: str
    severity: str = "info"  # info | wind_start | wind_stop | warning
    image_path: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def deg_to_compass(deg: Optional[float]) -> str:
    """Convert a wind direction in degrees to an 8-point compass label."""
    if deg is None:
        return "?"
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    idx = int((deg / 45) + 0.5) % 8
    return directions[idx]
