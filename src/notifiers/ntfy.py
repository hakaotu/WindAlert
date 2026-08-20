"""ntfy.sh notifier (v0.3).

ntfy is a free, open-source push notification service - no account or
API key needed to receive messages, just a "topic" name you subscribe
to in the ntfy app or browser. This is the easiest way to get push
notifications on a phone without dealing with bot tokens or SMTP.

Security note: a topic name works like a shared password - anyone who
knows it can both read and post to it. Use a long, unguessable topic
(e.g. "wingfoil-rautalampi-x7q2f") rather than something short and
obvious, especially if using the public ntfy.sh server.
"""
from __future__ import annotations

import logging

import requests

from core.models import Alert

from .base import Notifier

log = logging.getLogger(__name__)

_PRIORITY_BY_SEVERITY = {
    "wind_start": "4",  # high
    "wind_stop": "2",   # low
    "warning": "5",     # max
    "info": "3",        # default
}

_TAG_BY_SEVERITY = {
    "wind_start": "ocean",
    "wind_stop": "cloud",
    "warning": "warning",
    "info": "information_source",
}


class NtfyNotifier(Notifier):
    def __init__(self, topic: str, server: str = "https://ntfy.sh"):
        self.topic = topic
        self.server = server.rstrip("/")

    def name(self) -> str:
        return "ntfy"

    def send(self, alert: Alert) -> bool:
        url = f"{self.server}/{self.topic}"
        headers = {
            "Title": alert.title.encode("utf-8"),
            "Priority": _PRIORITY_BY_SEVERITY.get(alert.severity, "3"),
            "Tags": _TAG_BY_SEVERITY.get(alert.severity, "information_source"),
        }
        try:
            resp = requests.post(
                url, data=alert.body.encode("utf-8"), headers=headers, timeout=15
            )
            if resp.status_code >= 300:
                log.error("ntfy send failed: HTTP %s - %s", resp.status_code, resp.text)
                return False
            return True
        except requests.RequestException as e:
            log.error("ntfy send failed: %s", e)
            return False
