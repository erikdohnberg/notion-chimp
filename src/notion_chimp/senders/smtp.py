"""Plain SMTP sender. Mostly here to show the sender interface is pluggable."""
from __future__ import annotations

import os
import smtplib

from .base import OutgoingEmail, build_mime


class SMTPSender:
    name = "smtp"

    def __init__(self, options: dict | None = None):
        o = options or {}
        self.host = o.get("host") or os.environ.get("SMTP_HOST", "")
        self.port = int(o.get("port") or os.environ.get("SMTP_PORT", 587))
        self.username = o.get("username") or os.environ.get("SMTP_USERNAME", "")
        self.password = os.environ.get(o.get("password_env", "SMTP_PASSWORD"), "")
        self.starttls = bool(o.get("starttls", True))
        if not self.host:
            raise ValueError("SMTP host is empty. Set SMTP_HOST or sender.host.")

    def send(self, email: OutgoingEmail) -> str:
        msg = build_mime(email)
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            if self.starttls:
                s.starttls()
            if self.username:
                s.login(self.username, self.password)
            s.send_message(msg)
        return msg["Message-ID"]
