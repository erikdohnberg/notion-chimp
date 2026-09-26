"""Sender interface. The campaign runner and tracking core only see this."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class OutgoingEmail:
    to: str
    subject: str
    text: str
    html: str
    from_address: str
    from_name: str | None = None
    reply_to: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


class Sender(Protocol):
    name: str

    def send(self, email: OutgoingEmail) -> str:
        """Send one message and return a provider message id."""
        ...


def build_mime(email: OutgoingEmail):
    from email.message import EmailMessage
    from email.utils import formataddr, make_msgid

    msg = EmailMessage()
    msg["To"] = email.to
    msg["From"] = formataddr((email.from_name, email.from_address)) if email.from_name else email.from_address
    msg["Subject"] = email.subject
    msg["Message-ID"] = make_msgid(domain=email.from_address.split("@")[-1])
    if email.reply_to:
        msg["Reply-To"] = email.reply_to
    for k, v in email.headers.items():
        msg[k] = v
    msg.set_content(email.text)
    msg.add_alternative(email.html, subtype="html")
    return msg
