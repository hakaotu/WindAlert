from __future__ import annotations

import logging

import requests

from core.models import Alert

from .base import Notifier

log = logging.getLogger(__name__)


class TelegramNotifier(Notifier):
    """Sends alerts via a Telegram bot.

    Requires:
    - bot_token: from @BotFather (set as env var, referenced via ${TELEGRAM_BOT_TOKEN})
    - chat_id: the chat/user id to send to (set as env var, e.g. ${TELEGRAM_CHAT_ID})
    """

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id

    def name(self) -> str:
        return "telegram"

    def send(self, alert: Alert) -> bool:
        text = f"*{alert.title}*\n{alert.body}"
        try:
            if alert.image_path:
                return self._send_photo(text, alert.image_path)
            return self._send_text(text)
        except requests.RequestException as e:
            log.error("Telegram send failed: %s", e)
            return False

    def _send_text(self, text: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        resp = requests.post(
            url,
            json={"chat_id": self.chat_id, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.error("Telegram send failed: HTTP %s - %s", resp.status_code, resp.text)
            return False
        return True

    def _send_photo(self, caption: str, image_path: str) -> bool:
        url = f"https://api.telegram.org/bot{self.bot_token}/sendPhoto"
        with open(image_path, "rb") as f:
            resp = requests.post(
                url,
                data={"chat_id": self.chat_id, "caption": caption, "parse_mode": "Markdown"},
                files={"photo": f},
                timeout=30,
            )
        if resp.status_code != 200:
            log.error("Telegram photo send failed: HTTP %s - %s", resp.status_code, resp.text)
            return False
        return True
