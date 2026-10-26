"""Smoke test for the full run() pipeline with FMI calls mocked out.

This exists because unit tests on individual modules can all pass while
the wiring between them (main.py) is still broken - this test catches
that class of bug without needing real network access to FMI.
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import main  # noqa: E402
from core.models import WindReading, ForecastPoint  # noqa: E402

CONFIG_TEMPLATE = """
location:
  name: "Testijärvi"
  latitude: 62.0
  longitude: 26.0
  fmi_station_id: 101311

wind:
  min_speed_ms: 6.0
  max_speed_ms: 15.0
  hysteresis:
    trigger_margin_ms: 0.0
    release_margin_ms: 1.0
    min_minutes_above: 0

chart:
  enabled: true

notifications:
  channels:
    - type: telegram
      enabled: true
      bot_token: "${TEST_BOT_TOKEN}"
      chat_id: "${TEST_CHAT_ID}"

state_path: "{state_path}"
"""


# Tampere coordinates and the owner's schedule: 06-22 Helsinki time, daylight
# only, closing 2 h before sunset. Window on 2026-10-25 is 05:34Z-12:43Z.
WINDOW_CONFIG_TEMPLATE = CONFIG_TEMPLATE.replace("latitude: 62.0", "latitude: 61.5177") \
    .replace("longitude: 26.0", "longitude: 23.7538") \
    .replace("    min_minutes_above: 0", "    min_minutes_above: 0\n    reminder_interval_minutes: 120") \
    + """
schedule:
  active_hours: "6-22"
  daylight_only: true
  sunset_margin_minutes: 120
"""


def _write_config(tmp_dir: str, template: str = CONFIG_TEMPLATE) -> str:
    state_path = os.path.join(tmp_dir, "state.json")
    config_path = os.path.join(tmp_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(template.replace("{state_path}", state_path))
    return config_path


def test_full_run_sends_telegram_photo_when_wind_is_good(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")

    now = datetime.now(timezone.utc)
    fake_observations = [
        WindReading(timestamp=now - timedelta(minutes=10), speed_ms=8.0, gust_ms=10.0, direction_deg=225.0),
        WindReading(timestamp=now, speed_ms=8.5, gust_ms=10.5, direction_deg=225.0),
    ]
    fake_forecast = [
        ForecastPoint(timestamp=now + timedelta(hours=1), speed_ms=8.0, gust_ms=10.0, direction_deg=225.0),
    ]

    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch("core.fmi_client.fetch_observations", return_value=fake_observations), \
         patch("core.fmi_client.fetch_forecast", return_value=fake_forecast), \
         patch("notifiers.telegram.requests.post") as mock_post:

        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"

        config_path = _write_config(tmp_dir)
        exit_code = main.run(config_path)

        assert exit_code == 0
        assert mock_post.called
        called_url = mock_post.call_args[0][0]
        # Chart is enabled -> should have used sendPhoto, not sendMessage.
        assert "sendPhoto" in called_url


def test_full_run_skips_notification_when_wind_too_weak(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")

    now = datetime.now(timezone.utc)
    fake_observations = [
        WindReading(timestamp=now, speed_ms=2.0, gust_ms=3.0, direction_deg=225.0),
    ]

    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch("core.fmi_client.fetch_observations", return_value=fake_observations), \
         patch("core.fmi_client.fetch_forecast", return_value=[]), \
         patch("notifiers.telegram.requests.post") as mock_post:

        config_path = _write_config(tmp_dir)
        exit_code = main.run(config_path)

        assert exit_code == 0
        assert not mock_post.called


# --- WA-1: alert window (daylight, 6-22 Helsinki time) -------------------------

def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def _observations(now: datetime, speed: float = 8.5) -> list[WindReading]:
    return [
        WindReading(timestamp=now - timedelta(minutes=20), speed_ms=speed - 0.5, gust_ms=speed + 1.5, direction_deg=225.0),
        WindReading(timestamp=now - timedelta(minutes=10), speed_ms=speed - 0.5, gust_ms=speed + 1.5, direction_deg=225.0),
        WindReading(timestamp=now, speed_ms=speed, gust_ms=speed + 2.0, direction_deg=225.0),
    ]


def _run_at(now: datetime, state_json: str | None = None, speed: float = 8.5):
    """Run main.run with the clock at `now`; return (post mock, fetch mock, state text before, after)."""
    with tempfile.TemporaryDirectory() as tmp_dir, \
         patch("core.fmi_client.fetch_observations", return_value=_observations(now, speed)) as fetch, \
         patch("core.fmi_client.fetch_forecast", return_value=[]), \
         patch("notifiers.telegram.requests.post") as mock_post:

        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "ok"

        config_path = _write_config(tmp_dir, WINDOW_CONFIG_TEMPLATE)
        state_path = os.path.join(tmp_dir, "state.json")
        if state_json is not None:
            with open(state_path, "w", encoding="utf-8") as f:
                f.write(state_json)
        before = state_json
        assert main.run(config_path, now=now) == 0
        after = None
        if os.path.exists(state_path):
            with open(state_path, encoding="utf-8") as f:
                after = f.read()
        return mock_post, fetch, before, after


IDLE_STATE = '{"state": "IDLE", "last_alert_at": null, "last_reminder_at": null}'
ALERTED_STATE = (
    '{"state": "ALERTED", "last_alert_at": "2026-10-25T06:59:00+00:00", '
    '"last_reminder_at": "2026-10-25T12:30:00+00:00"}'
)


def _caption(mock_post) -> str:
    return mock_post.call_args.kwargs["data"]["caption"]


@pytest.mark.parametrize("now", [
    _utc(2026, 10, 25, 17, 15),  # 19:15 local, after sunset - 2 h
    _utc(2026, 10, 25, 19, 45),  # 21:45 local, still inside 6-22
    _utc(2026, 10, 25, 22, 5),   # 00:05 local on the 26th
])
def test_no_send_after_sunset_margin_2026_10_25(monkeypatch, now):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, fetch, before, after = _run_at(now, IDLE_STATE)
    assert mock_post.called is False
    assert fetch.called is False
    assert after == before


def test_no_send_before_sunrise_inside_6_22(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, before, after = _run_at(_utc(2026, 10, 25, 5, 0), IDLE_STATE)  # 07:00 local, sunrise 07:35
    assert mock_post.called is False
    assert after == before


@pytest.mark.parametrize("now", [
    _utc(2026, 10, 25, 22, 5),  # 00:05 EET
    _utc(2026, 6, 21, 21, 5),   # 00:05 EEST
])
def test_no_send_at_0005_local_winter_and_summer(monkeypatch, now):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, _, _ = _run_at(now, IDLE_STATE)
    assert mock_post.called is False


def test_sends_inside_window_2026_10_25_noon(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, _, after = _run_at(_utc(2026, 10, 25, 10, 0), IDLE_STATE)  # 12:00 local
    assert mock_post.call_count == 1
    assert "sendPhoto" in mock_post.call_args[0][0]
    assert '"state": "ALERTED"' in after


def test_reminder_not_sent_outside_window(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    state = '{"state": "ALERTED", "last_alert_at": "2026-10-25T06:59:00+00:00", "last_reminder_at": null}'
    mock_post, _, before, after = _run_at(_utc(2026, 10, 25, 17, 15), state)
    assert mock_post.called is False
    assert after == before
    assert "last_reminder_at\": null" in after


def test_reminder_sent_inside_window(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    state = '{"state": "ALERTED", "last_alert_at": "2026-10-25T06:59:00+00:00", "last_reminder_at": null}'
    mock_post, _, _, after = _run_at(_utc(2026, 10, 25, 10, 0), state)
    assert mock_post.call_count == 1
    assert "edelleen" in _caption(mock_post)
    assert "2026-10-25T10:00:00+00:00" in after


def test_inside_window_weak_wind_sends_nothing(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, _, _ = _run_at(_utc(2026, 10, 25, 10, 0), IDLE_STATE, speed=2.0)
    assert mock_post.called is False


def test_morning_after_sends_fresh_wind_start(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, _, after = _run_at(_utc(2026, 10, 26, 7, 0), ALERTED_STATE)  # 09:00 local
    assert mock_post.call_count == 1
    assert "Tuulee ajokelpoisesti" in _caption(mock_post)
    assert "edelleen" not in _caption(mock_post)
    assert '"state": "ALERTED"' in after
    assert "2026-10-26T07:00:00+00:00" in after


def test_morning_after_no_wind_sends_nothing_and_goes_idle(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "dummy-token")
    monkeypatch.setenv("TEST_CHAT_ID", "12345")
    mock_post, _, _, after = _run_at(_utc(2026, 10, 26, 7, 0), ALERTED_STATE, speed=2.0)
    assert mock_post.called is False
    assert '"state": "IDLE"' in after
