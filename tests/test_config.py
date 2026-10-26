import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from core.config import ConfigError, load_config  # noqa: E402

MINIMAL_CONFIG = """
location:
  name: "Testijärvi"
  latitude: 62.0
  longitude: 26.0

wind:
  min_speed_ms: 6.0
  max_speed_ms: 15.0

notifications:
  channels:
    - type: telegram
      enabled: true
      bot_token: "${TEST_BOT_TOKEN}"
      chat_id: "${TEST_CHAT_ID}"
"""


def write_temp_config(text: str) -> str:
    f = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False, encoding="utf-8")
    f.write(text)
    f.close()
    return f.name


def test_env_var_substitution(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    path = write_temp_config(MINIMAL_CONFIG)
    cfg = load_config(path)
    assert cfg.channels[0].options["bot_token"] == "abc123"
    assert cfg.channels[0].options["chat_id"] == "999"
    os.unlink(path)


def test_missing_env_var_raises_clear_error(monkeypatch):
    monkeypatch.delenv("TEST_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TEST_CHAT_ID", raising=False)
    path = write_temp_config(MINIMAL_CONFIG)
    with pytest.raises(ConfigError, match="TEST_BOT_TOKEN"):
        load_config(path)
    os.unlink(path)


def test_no_enabled_channel_raises(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc")
    monkeypatch.setenv("TEST_CHAT_ID", "1")
    disabled = MINIMAL_CONFIG.replace("enabled: true", "enabled: false")
    path = write_temp_config(disabled)
    with pytest.raises(ConfigError, match="No notification channel"):
        load_config(path)
    os.unlink(path)


def test_missing_file_raises():
    with pytest.raises(ConfigError, match="not found"):
        load_config("/tmp/does_not_exist_12345.yaml")


def test_schedule_defaults(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    path = write_temp_config(MINIMAL_CONFIG)
    cfg = load_config(path)
    os.unlink(path)
    assert cfg.schedule.active_hours == "0-24"
    assert cfg.schedule.daylight_only is False
    assert cfg.schedule.sunset_margin_minutes == 0


def test_schedule_keys_parsed(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    text = MINIMAL_CONFIG + (
        '\nschedule:\n  active_hours: "6-22"\n  daylight_only: true\n'
        "  sunset_margin_minutes: 120\n"
    )
    path = write_temp_config(text)
    cfg = load_config(path)
    os.unlink(path)
    assert cfg.schedule.active_hours_range() == (6, 22)
    assert cfg.schedule.daylight_only is True
    assert cfg.schedule.sunset_margin_minutes == 120


@pytest.mark.parametrize("value", ["22-6", "6-25", "abc"])
def test_invalid_active_hours_raises(monkeypatch, value):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    path = write_temp_config(MINIMAL_CONFIG + f'\nschedule:\n  active_hours: "{value}"\n')
    with pytest.raises(ConfigError, match="schedule.active_hours"):
        load_config(path)
    os.unlink(path)


def test_negative_sunset_margin_raises(monkeypatch):
    monkeypatch.setenv("TEST_BOT_TOKEN", "abc123")
    monkeypatch.setenv("TEST_CHAT_ID", "999")
    path = write_temp_config(MINIMAL_CONFIG + "\nschedule:\n  sunset_margin_minutes: -5\n")
    with pytest.raises(ConfigError, match="sunset_margin_minutes"):
        load_config(path)
    os.unlink(path)
