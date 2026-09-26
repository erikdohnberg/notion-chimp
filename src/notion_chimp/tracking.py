"""Tracking core: URL encoding/decoding on top of pytracking.

Tokens are Fernet-encrypted by pytracking, so a recipient can't read the page
id out of a link, and nobody can mint a click URL that redirects somewhere you
didn't send. This module knows nothing about Notion or about how mail is sent.
"""
from __future__ import annotations

import base64
import html as html_lib
import re
import time
from dataclasses import dataclass

import pytracking
from cryptography.fernet import Fernet, InvalidToken

# 1x1 transparent GIF
PIXEL_GIF = base64.b64decode(b"R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")

_HREF = re.compile(r"""(<a\b[^>]*?\bhref\s*=\s*)(["'])(https?://[^"']+)\2""", re.I)


def generate_key() -> str:
    return Fernet.generate_key().decode()


@dataclass
class Hit:
    page_id: str
    step: str
    sent_at: int
    url: str | None  # set for clicks


class Tracker:
    def __init__(self, base_url: str, secret_key: str):
        if not base_url:
            raise ValueError("tracking.base_url is empty. Set NOTION_CHIMP_BASE_URL.")
        if not secret_key:
            raise ValueError("tracking secret key is empty. Run `notion-chimp gen-key` and set NOTION_CHIMP_SECRET_KEY.")
        self.base_url = base_url.rstrip("/")
        self._cfg = pytracking.Configuration(encryption_bytestring_key=secret_key.encode())

    @staticmethod
    def metadata(page_id: str, step: str, sent_at: int | None = None) -> dict:
        return {"p": page_id, "s": step, "t": int(sent_at if sent_at is not None else time.time())}

    def _encode(self, url: str | None, metadata: dict) -> str:
        data = self._cfg.get_data_to_embed(url, metadata)
        return self._cfg.get_url_encoded_data_str(data)

    def open_url(self, metadata: dict) -> str:
        return f"{self.base_url}/o/{self._encode(None, metadata)}.gif"

    def click_url(self, url: str, metadata: dict) -> str:
        return f"{self.base_url}/c/{self._encode(url, metadata)}"

    def decode(self, token: str, is_open: bool) -> Hit | None:
        """Return the hit, or None for a token we didn't issue."""
        if is_open and token.endswith(".gif"):
            token = token[: -len(".gif")]
        try:
            result = self._cfg.get_tracking_result(token, request_data=None, is_open=is_open)
        except (InvalidToken, ValueError, TypeError):
            return None
        meta = result.metadata or {}
        if "p" not in meta:
            return None
        if not is_open and not result.tracked_url:
            return None
        return Hit(page_id=meta["p"], step=meta.get("s", ""), sent_at=int(meta.get("t", 0)),
                   url=result.tracked_url)

    def pixel_tag(self, metadata: dict) -> str:
        return (f'<img src="{html_lib.escape(self.open_url(metadata))}" width="1" height="1" '
                'alt="" style="display:block;border:0;width:1px;height:1px" />')

    def instrument_html(self, body_html: str, metadata: dict) -> str:
        """Wrap every http(s) link in a click URL and append the open pixel."""
        def swap(m: re.Match) -> str:
            original = html_lib.unescape(m.group(3))
            return f"{m.group(1)}{m.group(2)}{html_lib.escape(self.click_url(original, metadata))}{m.group(2)}"

        out = _HREF.sub(swap, body_html)
        pixel = self.pixel_tag(metadata)
        if re.search(r"</body>", out, re.I):
            return re.sub(r"</body>", pixel + "</body>", out, count=1, flags=re.I)
        return out + pixel
