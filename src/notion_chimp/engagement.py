"""Decide whether a hit is a real engagement, then write it back to Notion.

Filtering rules (all configurable under tracking.filters):

* HEAD requests never count. Scanners use them to probe links.
* Hits within N seconds of send are scanners or prefetchers, not people.
* Known scanner / bot user agents are ignored.
* Apple Mail Privacy Protection prefetches (bare "Mozilla/5.0" UA) are skipped
  by default, because they fire whether or not anyone read the message.
* Repeat opens of the same message inside the dedupe window count once.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from .config import Config, FilterConfig
from .notion import NotionClient
from .properties import build_value, read_value
from .tracking import Hit

log = logging.getLogger(__name__)

APPLE_MPP_UA = "mozilla/5.0"


@dataclass
class Request:
    method: str
    user_agent: str
    ip: str


def filter_reason(hit: Hit, req: Request, filters: FilterConfig, is_open: bool,
                  now: float | None = None) -> str | None:
    """Return why this hit should be ignored, or None if it counts."""
    now = time.time() if now is None else now
    if req.method.upper() == "HEAD":
        return "head-request"
    if req.ip and req.ip in filters.ignore_ips:
        return "ignored-ip"
    age = now - hit.sent_at
    min_age = filters.min_seconds_after_send if is_open else filters.click_min_seconds_after_send
    if age < min_age:
        return "too-soon-after-send"
    ua = (req.user_agent or "").strip().lower()
    if is_open and ua == APPLE_MPP_UA and filters.apple_mpp == "skip":
        return "apple-mpp-prefetch"
    for needle in filters.ignore_user_agents:
        if needle and needle in ua:
            return f"user-agent:{needle}"
    return None


class Deduper:
    """Remembers recent counted opens per (page, step). In-memory, so a restart
    forgets the window; the worst case is one extra counted open."""

    def __init__(self, minutes: int):
        self.window = minutes * 60
        self._seen: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def first_in_window(self, key: tuple[str, str], now: float) -> bool:
        if self.window <= 0:
            return True
        with self._lock:
            last = self._seen.get(key)
            if last is not None and now - last < self.window:
                return False
            self._seen[key] = now
            if len(self._seen) > 10000:
                cutoff = now - self.window
                self._seen = {k: v for k, v in self._seen.items() if v >= cutoff}
            return True


class EngagementRecorder:
    def __init__(self, config: Config, notion: NotionClient, data_source_id: str):
        self.config = config
        self.notion = notion
        self.data_source_id = data_source_id
        self.deduper = Deduper(config.tracking.filters.dedupe_minutes)
        self.tz = ZoneInfo(config.timezone)

    def _types(self) -> dict[str, str]:
        schema = self.notion.schema(self.data_source_id)
        return {name: p["type"] for name, p in schema.items()}

    def _now_iso(self) -> str:
        return datetime.now(self.tz).isoformat(timespec="seconds")

    def handle(self, hit: Hit, req: Request, is_open: bool, now: float | None = None) -> str:
        """Returns 'recorded', 'killed', 'disabled' or the filter reason."""
        now = time.time() if now is None else now
        if self.config.killed():
            return "killed"
        if not self.config.tracking.enabled:
            return "disabled"
        reason = filter_reason(hit, req, self.config.tracking.filters, is_open, now)
        if reason:
            return reason
        if is_open and not self.deduper.first_in_window((hit.page_id, hit.step), now):
            return "duplicate-open"
        if is_open:
            self.record_open(hit.page_id)
        else:
            self.record_click(hit.page_id, hit.url or "")
        return "recorded"

    def record_open(self, page_id: str) -> None:
        props = self.config.properties
        types = self._types()
        page = self.notion.get_page(page_id)
        current = page.get("properties", {})
        updates: dict[str, dict] = {}
        if props.open_count and props.open_count in types:
            count = read_value(current.get(props.open_count)) or 0
            updates[props.open_count] = build_value(types[props.open_count], int(count) + 1)
        if props.first_opened and props.first_opened in types:
            if not read_value(current.get(props.first_opened)):
                updates[props.first_opened] = build_value(types[props.first_opened], self._now_iso())
        self._touch_engagement(updates, types)
        if updates:
            self.notion.update_page(page_id, updates)

    def record_click(self, page_id: str, url: str) -> None:
        props = self.config.properties
        types = self._types()
        updates: dict[str, dict] = {}
        name = props.link_clicked
        if name and name in types:
            t = types[name]
            if t == "checkbox":
                updates[name] = build_value(t, True)
            elif t == "date":
                current = self.notion.get_page(page_id).get("properties", {})
                if not read_value(current.get(name)):  # keep the first click time
                    updates[name] = build_value(t, self._now_iso())
            elif t == "number":
                current = self.notion.get_page(page_id).get("properties", {})
                updates[name] = build_value(t, int(read_value(current.get(name)) or 0) + 1)
            else:  # rich_text / url: last clicked link
                updates[name] = build_value(t, url)
        self._touch_engagement(updates, types)
        if updates:
            self.notion.update_page(page_id, updates)

    def _touch_engagement(self, updates: dict, types: dict[str, str]) -> None:
        name = self.config.properties.last_engagement
        if name and name in types:
            updates[name] = build_value(types[name], self._now_iso())
