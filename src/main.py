"""Entry point. Run this from cron, systemd, or GitHub Actions.

    python src/main.py --config config.yaml

Flow per run:
1. Load + validate config (fails fast if broken).
2. Resolve station (explicit fmisid or nearest-station lookup).
3. Fetch latest observation (+ forecast if enabled).
4. Feed into the hysteresis state machine.
5. If it decided to notify, build the message and send it through every
   enabled channel independently (one channel failing doesn't block others).
6. Persist state to disk regardless of outcome.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone

from core import fmi_client, hysteresis, message
from core.config import AppConfig, NotifierChannelConfig, load_config_or_exit
from core.models import Alert, WindReading
from notifiers.base import Notifier
from notifiers.email_notifier import EmailNotifier
from notifiers.ntfy import NtfyNotifier
from notifiers.telegram import TelegramNotifier
from telemetry import reporter as telemetry_reporter

log = logging.getLogger("wingfoil_alert")

# Adding a new channel = add one entry here + one file in notifiers/.
NOTIFIER_FACTORIES = {
    "telegram": lambda opts: TelegramNotifier(
        bot_token=opts["bot_token"], chat_id=opts["chat_id"]
    ),
    "email": lambda opts: EmailNotifier(
        smtp_host=opts["smtp_host"],
        smtp_port=int(opts.get("smtp_port", 587)),
        smtp_user=opts["smtp_user"],
        smtp_password=opts["smtp_password"],
        to_address=opts["to"],
        from_address=opts.get("from"),
        use_tls=bool(opts.get("use_tls", True)),
    ),
    "ntfy": lambda opts: NtfyNotifier(
        topic=opts["topic"], server=opts.get("server", "https://ntfy.sh")
    ),
}


def build_notifiers(channels: list[NotifierChannelConfig]) -> list[Notifier]:
    notifiers: list[Notifier] = []
    for ch in channels:
        if not ch.enabled:
            continue
        factory = NOTIFIER_FACTORIES.get(ch.type)
        if factory is None:
            log.warning("Unknown notifier type '%s' - skipping. "
                        "(WhatsApp etc. may be community plugins - "
                        "see docs/adding-a-notifier.md)", ch.type)
            continue
        try:
            notifiers.append(factory(ch.options))
        except KeyError as e:
            log.error("Notifier '%s' is missing required option %s - skipping.", ch.type, e)
    return notifiers


def is_within_active_hours(cfg: AppConfig) -> bool:
    start, end = cfg.schedule.active_hours_range()
    now_hour = datetime.now().hour
    return start <= now_hour <= end


def resolve_station(cfg: AppConfig) -> int:
    if cfg.location.fmi_station_id:
        return cfg.location.fmi_station_id
    fmisid, name = fmi_client.find_nearest_station(cfg.location.latitude, cfg.location.longitude)
    log.info("No fmi_station_id set - using nearest station: %s (%s)", name, fmisid)
    return fmisid


def send_alert(alert: Alert, notifiers: list[Notifier]) -> None:
    for notifier in notifiers:
        try:
            ok = notifier.send(alert)
            if ok:
                log.info("Sent alert via %s", notifier.name())
            else:
                log.error("Failed to send alert via %s", notifier.name())
        except Exception:  # noqa: BLE001 - one bad channel must not kill the run
            log.exception("Unexpected error sending via %s", notifier.name())


def run(config_path: str) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format='{"time": "%(asctime)s", "level": "%(levelname)s", "msg": %(message)r}',
    )

    cfg = load_config_or_exit(config_path)

    if not is_within_active_hours(cfg):
        log.info("Outside active hours (%s) - skipping this run.", cfg.schedule.active_hours)
        return 0

    notifiers = build_notifiers(cfg.channels)
    if not notifiers:
        log.error("No usable notifiers configured - aborting.")
        return 1

    try:
        fmisid = resolve_station(cfg)
        lookback = 60
        if cfg.chart.enabled:
            lookback = max(lookback, cfg.chart.lookback_hours * 60)
        observations = fmi_client.fetch_observations(fmisid, lookback_minutes=lookback)
    except fmi_client.FmiApiError as e:
        log.error("Could not fetch observations after retries: %s", e)
        return 1

    if not observations:
        log.warning("FMI returned no observation rows for this window.")
        return 0

    latest = observations[-1]

    forecast = []
    if cfg.forecast.enabled:
        try:
            forecast = fmi_client.fetch_forecast(
                cfg.location.latitude, cfg.location.longitude, cfg.forecast.hours_ahead
            )
        except fmi_client.FmiApiError as e:
            log.warning("Forecast fetch failed (continuing without it): %s", e)

    state = hysteresis.load_state(cfg.state_path)
    decision = hysteresis.evaluate(latest, state, cfg.wind)

    if decision.should_notify:
        if decision.new_severity == "wind_start":
            alert = message.build_start_alert(
                latest, forecast, cfg.location, cfg.wind, cfg.forecast,
                observations=observations, chart_cfg=cfg.chart,
            )
        else:
            alert = message.build_stop_alert(latest, cfg.location)
        send_alert(alert, notifiers)

        if cfg.telemetry.enabled:
            telemetry_reporter.report_event(
                cfg.telemetry.endpoint,
                cfg.location.latitude,
                cfg.location.longitude,
                decision.new_severity,
            )
    else:
        log.info(
            "No notification this run (state=%s, speed=%s m/s)",
            decision.new_state.state,
            latest.speed_ms,
        )

    hysteresis.save_state(cfg.state_path, decision.new_state)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Wingfoil/kite/surf wind alert bot")
    parser.add_argument("--config", default="config.yaml", help="Path to config.yaml")
    args = parser.parse_args()
    sys.exit(run(args.config))


if __name__ == "__main__":
    main()
