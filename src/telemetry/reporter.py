"""Opt-in, anonymized usage telemetry (v0.3).

Design principles (see PRIVACY.md for the full explanation):
- Off by default. Only runs at all if telemetry.enabled: true AND an
  endpoint is configured - a user who turns it on without pointing it
  anywhere gets a harmless no-op, not an error.
- Anonymization happens here, locally, BEFORE anything leaves the
  machine - never as a promise about what a server "will do" with raw
  data, because raw data is never sent in the first place.
- Coordinates are rounded to a coarse grid (default ~0.5 degrees,
  roughly 50 km) - never the exact configured location.
- Only a daily-resolution event is sent (date + region grid + event
  type). No message content, no minute-level timestamps, no IP is read
  or forwarded by this code (whatever the receiving server logs is
  outside this project's control - see docs/telemetry.md for what a
  privacy-respecting reference server implementation looks like).
- A random instance id is generated once and stored locally. It is
  never derived from, or combined with, the user's Telegram chat id,
  email address, or any other personal identifier.
- Telemetry must NEVER be able to break the actual alerting. Failures
  are logged at debug level and swallowed - a flaky telemetry endpoint
  must never prevent or delay a real wind alert.
"""
from __future__ import annotations

import logging
import os
import uuid
from datetime import date

import requests

log = logging.getLogger(__name__)

_INSTANCE_ID_PATH = "~/.wingfoil_instance_id"
DEFAULT_GRID_SIZE_DEGREES = 0.5


def _get_or_create_instance_id() -> str:
    path = os.path.expanduser(_INSTANCE_ID_PATH)
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = f.read().strip()
            if existing:
                return existing
        except OSError:
            pass
    new_id = str(uuid.uuid4())
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_id)
    except OSError:
        log.debug("Could not persist instance id - will regenerate a new one next run.")
    return new_id


def round_to_grid(
    latitude: float, longitude: float, grid_size: float = DEFAULT_GRID_SIZE_DEGREES
) -> tuple[float, float]:
    """Round coordinates down to a coarse grid so no exact location ever
    leaves the machine, even if the receiving server is untrustworthy."""
    return (
        round(latitude / grid_size) * grid_size,
        round(longitude / grid_size) * grid_size,
    )


def report_event(endpoint: str | None, latitude: float, longitude: float, event: str) -> None:
    """Fire-and-forget anonymized event report. Never raises."""
    if not endpoint:
        log.debug("Telemetry enabled but no endpoint configured - skipping.")
        return

    try:
        grid_lat, grid_lon = round_to_grid(latitude, longitude)
        payload = {
            "instance_id": _get_or_create_instance_id(),
            "region_grid": f"{grid_lat:.1f},{grid_lon:.1f}",
            "date": date.today().isoformat(),
            "event": event,  # "wind_start" | "wind_stop"
        }
        requests.post(endpoint, json=payload, timeout=5)
    except Exception as e:  # noqa: BLE001 - telemetry must never break alerting
        log.debug("Telemetry report failed (non-fatal, ignored): %s", e)
