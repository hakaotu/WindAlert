"""Hysteresis state machine for wind alerts.

Why this exists: without hysteresis, wind hovering right around the
threshold would trigger a notification every single poll, which is
useless and annoying. This module tracks a small history of recent
readings and only transitions IDLE -> ALERTED once wind has been above
threshold for a minimum duration, and only transitions back once it has
dropped meaningfully below it (release_margin), not just barely under.

State is persisted to JSON on disk so it survives between separate
process runs (cron, GitHub Actions, etc. - each run is a fresh process).
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .config import WindConfig
from .models import AlertState, WindReading, deg_to_compass


@dataclass
class HysteresisState:
    state: str = AlertState.IDLE.value
    last_alert_at: Optional[str] = None
    recent_readings: list[dict] = field(default_factory=list)  # [{ts, speed}]
    last_reminder_at: Optional[str] = None

    def to_json(self) -> str:
        return json.dumps(asdict(self), indent=2)

    @classmethod
    def from_json(cls, text: str) -> "HysteresisState":
        data = json.loads(text)
        return cls(**data)


def load_state(path: str) -> HysteresisState:
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return HysteresisState()
    try:
        with open(expanded, "r", encoding="utf-8") as f:
            return HysteresisState.from_json(f.read())
    except (json.JSONDecodeError, TypeError, KeyError):
        # Corrupt state file must never crash the whole run - start fresh.
        return HysteresisState()


def save_state(path: str, state: HysteresisState) -> None:
    expanded = os.path.expanduser(path)
    os.makedirs(os.path.dirname(expanded) or ".", exist_ok=True)
    with open(expanded, "w", encoding="utf-8") as f:
        f.write(state.to_json())


@dataclass
class Decision:
    should_notify: bool
    new_severity: Optional[str]  # "wind_start" | "wind_stop" | None
    new_state: HysteresisState


def _direction_ok(reading: WindReading, allowed: list[str]) -> bool:
    if not allowed:
        return True
    if reading.direction_deg is None:
        return False
    return deg_to_compass(reading.direction_deg) in allowed


def evaluate(
    latest: WindReading,
    state: HysteresisState,
    wind_cfg: WindConfig,
) -> Decision:
    """Feed the latest reading into the state machine and decide whether
    to fire a notification this run.
    """
    now = latest.timestamp
    trigger_threshold = wind_cfg.min_speed_ms + wind_cfg.hysteresis.trigger_margin_ms
    release_threshold = wind_cfg.min_speed_ms - wind_cfg.hysteresis.release_margin_ms

    # Keep a rolling window of recent readings for the min_minutes_above check.
    recent = list(state.recent_readings)
    if latest.is_valid:
        recent.append({"ts": now.isoformat(), "speed": latest.speed_ms})
    window_minutes = max(wind_cfg.hysteresis.min_minutes_above * 2, 30)
    cutoff = now.timestamp() - window_minutes * 60
    recent = [r for r in recent if datetime.fromisoformat(r["ts"]).timestamp() >= cutoff]

    current_state = AlertState(state.state)

    if not latest.is_valid:
        # Missing data: don't change state, don't notify, just persist as-is.
        return Decision(False, None, HysteresisState(current_state.value, state.last_alert_at, recent, state.last_reminder_at))

    in_speed_band = wind_cfg.min_speed_ms <= latest.speed_ms <= wind_cfg.max_speed_ms
    direction_ok = _direction_ok(latest, wind_cfg.direction_filter)

    if current_state == AlertState.IDLE:
        above_trigger = [r for r in recent if r["speed"] >= trigger_threshold]
        if len(above_trigger) >= 2:
            timestamps = [datetime.fromisoformat(r["ts"]).timestamp() for r in above_trigger]
            sustained_minutes = (max(timestamps) - min(timestamps)) / 60
        else:
            # A single reading can't demonstrate a sustained duration yet,
            # regardless of how high min_minutes_above is set.
            sustained_minutes = 0
        if (
            latest.speed_ms >= trigger_threshold
            and in_speed_band
            and direction_ok
            and sustained_minutes >= wind_cfg.hysteresis.min_minutes_above
        ):
            new_state = HysteresisState(AlertState.ALERTED.value, now.isoformat(), recent, last_reminder_at=None)
            return Decision(True, "wind_start", new_state)
        return Decision(False, None, HysteresisState(current_state.value, state.last_alert_at, recent, state.last_reminder_at))

    else:  # ALERTED
        if latest.speed_ms < release_threshold or not direction_ok or latest.speed_ms > wind_cfg.max_speed_ms:
            new_state = HysteresisState(AlertState.IDLE.value, state.last_alert_at, recent, last_reminder_at=None)
            return Decision(True, "wind_stop", new_state)

        # Still alerted and still good: optionally ping again periodically so
        # a long calm stretch of "still fine" doesn't look like silence/death.
        reminder_minutes = wind_cfg.hysteresis.reminder_interval_minutes
        if reminder_minutes > 0:
            last_notified = state.last_reminder_at or state.last_alert_at
            due = last_notified is None or (
                (now.timestamp() - datetime.fromisoformat(last_notified).timestamp()) / 60 >= reminder_minutes
            )
            if due:
                new_state = HysteresisState(
                    AlertState.ALERTED.value, state.last_alert_at, recent, last_reminder_at=now.isoformat()
                )
                return Decision(True, "wind_still", new_state)

        return Decision(False, None, HysteresisState(current_state.value, state.last_alert_at, recent, state.last_reminder_at))
