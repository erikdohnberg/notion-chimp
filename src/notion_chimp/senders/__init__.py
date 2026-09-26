"""Sender registry. To add a provider, write a class with ``name`` and
``send(OutgoingEmail) -> str`` and register it here."""
from __future__ import annotations

from typing import Callable

from .base import OutgoingEmail, Sender

_REGISTRY: dict[str, Callable[[dict], Sender]] = {}


def register(name: str, factory: Callable[[dict], Sender]) -> None:
    _REGISTRY[name] = factory


def get_sender(provider: str, options: dict | None = None) -> Sender:
    if provider not in _REGISTRY:
        raise ValueError(f"unknown sender {provider!r}; available: {sorted(_REGISTRY)}")
    return _REGISTRY[provider](options or {})


def _gmail(options: dict) -> Sender:
    from .gmail import GmailSender
    return GmailSender(options)


def _smtp(options: dict) -> Sender:
    from .smtp import SMTPSender
    return SMTPSender(options)


register("gmail", _gmail)
register("smtp", _smtp)

__all__ = ["OutgoingEmail", "Sender", "get_sender", "register"]
