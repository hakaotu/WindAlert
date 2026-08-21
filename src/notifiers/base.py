"""Common interface for all notification channels.

Adding a new channel means: implement this class, register it in
main.py's NOTIFIER_FACTORIES, done. The core engine never needs to change.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from core.models import Alert


class Notifier(ABC):
    @abstractmethod
    def send(self, alert: Alert) -> bool:
        """Send the alert. Return True on success, False on failure.

        Implementations should catch their own exceptions and log them -
        one channel failing must never crash the whole run or stop other
        channels from being tried.
        """
        raise NotImplementedError

    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError
