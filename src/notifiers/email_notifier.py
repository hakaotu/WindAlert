from __future__ import annotations

import logging
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from core.models import Alert

from .base import Notifier

log = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    """Sends alerts via SMTP. Works with Gmail app passwords or any SMTP
    provider. Kept dependency-free (uses Python's stdlib smtplib) so it
    works the same on GitHub Actions and self-hosted setups.
    """

    def __init__(
        self,
        smtp_host: str,
        smtp_port: int,
        smtp_user: str,
        smtp_password: str,
        to_address: str,
        from_address: str | None = None,
        use_tls: bool = True,
    ):
        self.smtp_host = smtp_host
        self.smtp_port = smtp_port
        self.smtp_user = smtp_user
        self.smtp_password = smtp_password
        self.to_address = to_address
        self.from_address = from_address or smtp_user
        self.use_tls = use_tls

    def name(self) -> str:
        return "email"

    def send(self, alert: Alert) -> bool:
        if alert.image_path:
            msg = MIMEMultipart()
            msg.attach(MIMEText(alert.body, _charset="utf-8"))
            try:
                with open(alert.image_path, "rb") as f:
                    img = MIMEImage(f.read())
                    img.add_header("Content-Disposition", "attachment", filename="tuuli.png")
                    msg.attach(img)
            except OSError as e:
                log.warning("Could not attach chart image, sending text-only: %s", e)
        else:
            msg = MIMEText(alert.body, _charset="utf-8")

        msg["Subject"] = alert.title
        msg["From"] = self.from_address
        msg["To"] = self.to_address

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=15) as server:
                if self.use_tls:
                    server.starttls()
                server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.from_address, [self.to_address], msg.as_string())
            return True
        except (smtplib.SMTPException, OSError) as e:
            log.error("Email send failed: %s", e)
            return False
