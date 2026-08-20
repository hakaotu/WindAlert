import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.config import HysteresisConfig, WindConfig  # noqa: E402
from core.hysteresis import HysteresisState, evaluate  # noqa: E402
from core.models import AlertState, WindReading  # noqa: E402


def make_wind_cfg(**overrides) -> WindConfig:
    defaults = dict(
        min_speed_ms=6.0,
        max_speed_ms=15.0,
        direction_filter=[],
        hysteresis=HysteresisConfig(
            trigger_margin_ms=0.5, release_margin_ms=1.0, min_minutes_above=10
        ),
    )
    defaults.update(overrides)
    return WindConfig(**defaults)


def reading(speed, minutes_ago=0, direction=225.0):
    ts = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return WindReading(timestamp=ts, speed_ms=speed, gust_ms=speed + 2, direction_deg=direction)


def test_no_alert_below_threshold():
    cfg = make_wind_cfg()
    state = HysteresisState()
    decision = evaluate(reading(4.0), state, cfg)
    assert decision.should_notify is False
    assert decision.new_state.state == AlertState.IDLE.value


def test_single_spike_does_not_trigger():
    """One reading above threshold with no sustained history must not alert."""
    cfg = make_wind_cfg()
    state = HysteresisState()
    decision = evaluate(reading(7.0), state, cfg)
    assert decision.should_notify is False


def test_sustained_wind_triggers_alert():
    cfg = make_wind_cfg()
    # Simulate 20 minutes of history already above trigger threshold (6.5 m/s).
    history = [
        {"ts": (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat(), "speed": 7.0}
        for m in (20, 10)
    ]
    state = HysteresisState(state=AlertState.IDLE.value, recent_readings=history)
    decision = evaluate(reading(7.2), state, cfg)
    assert decision.should_notify is True
    assert decision.new_severity == "wind_start"
    assert decision.new_state.state == AlertState.ALERTED.value


def test_release_requires_margin_not_just_below_min():
    """Wind dropping to 5.5 (only 0.5 under min) should NOT release yet,
    because release_margin_ms is 1.0 -> release threshold is 5.0."""
    cfg = make_wind_cfg()
    state = HysteresisState(state=AlertState.ALERTED.value, last_alert_at="2026-01-01T10:00:00+00:00")
    decision = evaluate(reading(5.5), state, cfg)
    assert decision.should_notify is False
    assert decision.new_state.state == AlertState.ALERTED.value


def test_release_below_margin_triggers_stop_alert():
    cfg = make_wind_cfg()
    state = HysteresisState(state=AlertState.ALERTED.value, last_alert_at="2026-01-01T10:00:00+00:00")
    decision = evaluate(reading(4.5), state, cfg)
    assert decision.should_notify is True
    assert decision.new_severity == "wind_stop"
    assert decision.new_state.state == AlertState.IDLE.value


def test_wrong_direction_blocks_alert():
    cfg = make_wind_cfg(direction_filter=["SW", "W", "NW"])
    history = [
        {"ts": (datetime.now(timezone.utc) - timedelta(minutes=m)).isoformat(), "speed": 7.0}
        for m in (20, 10)
    ]
    state = HysteresisState(state=AlertState.IDLE.value, recent_readings=history)
    # direction=90 -> East, not in allowed list
    decision = evaluate(reading(7.2, direction=90.0), state, cfg)
    assert decision.should_notify is False


def test_missing_data_does_not_change_state_or_crash():
    cfg = make_wind_cfg()
    state = HysteresisState(state=AlertState.ALERTED.value)
    bad_reading = WindReading(timestamp=datetime.now(timezone.utc), speed_ms=None, gust_ms=None, direction_deg=None)
    decision = evaluate(bad_reading, state, cfg)
    assert decision.should_notify is False
    assert decision.new_state.state == AlertState.ALERTED.value


def test_too_strong_wind_releases_alert():
    """Above max_speed_ms should also release (too dangerous), not just below min."""
    cfg = make_wind_cfg()
    state = HysteresisState(state=AlertState.ALERTED.value)
    decision = evaluate(reading(20.0), state, cfg)
    assert decision.should_notify is True
    assert decision.new_severity == "wind_stop"
