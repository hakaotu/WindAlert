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


def _write_config(tmp_dir: str) -> str:
    state_path = os.path.join(tmp_dir, "state.json")
    config_path = os.path.join(tmp_dir, "config.yaml")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(CONFIG_TEMPLATE.replace("{state_path}", state_path))
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
