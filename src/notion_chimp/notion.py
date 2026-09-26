"""Minimal Notion REST client: just the calls notion-chimp needs."""
from __future__ import annotations

import logging
import time
from typing import Any, Iterator

import requests

from .properties import parse_id

log = logging.getLogger(__name__)

API_BASE = "https://api.notion.com/v1"
# Data sources (multi-source databases) arrived in this version
NOTION_VERSION = "2025-09-03"


class NotionError(RuntimeError):
    def __init__(self, status: int, body: Any):
        super().__init__(f"Notion API error {status}: {body}")
        self.status = status
        self.body = body


class NotionClient:
    def __init__(self, token: str, session: requests.Session | None = None,
                 base_url: str = API_BASE, max_retries: int = 3):
        if not token:
            raise ValueError("Notion token is empty. Set NOTION_TOKEN (see .env.example).")
        self.base_url = base_url
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type": "application/json",
        })
        self._schemas: dict[str, dict] = {}

    def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        for attempt in range(self.max_retries + 1):
            resp = self.session.request(method, url, json=json, timeout=30)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self.max_retries:
                    wait = float(resp.headers.get("Retry-After", 2 ** attempt))
                    log.warning("Notion %s on %s, retrying in %.1fs", resp.status_code, path, wait)
                    time.sleep(wait)
                    continue
            if resp.status_code >= 400:
                try:
                    body = resp.json()
                except ValueError:
                    body = resp.text
                raise NotionError(resp.status_code, body)
            return resp.json()
        raise AssertionError("unreachable")

    def resolve_data_source(self, ref: str) -> str:
        """Accept a data source id/URL, or a database id/URL with exactly one source."""
        obj_id = parse_id(ref)
        if ref.startswith("collection://"):
            return obj_id
        try:
            self._request("GET", f"/data_sources/{obj_id}")
            return obj_id
        except NotionError as e:
            if e.status not in (400, 404):
                raise
        db = self._request("GET", f"/databases/{obj_id}")
        sources = db.get("data_sources") or []
        if len(sources) != 1:
            names = [s.get("name") for s in sources]
            raise ValueError(
                f"database {obj_id} has {len(sources)} data sources {names}; "
                "put the specific collection:// URL in notion.data_source"
            )
        return sources[0]["id"]

    def schema(self, data_source_id: str) -> dict[str, dict]:
        """Property name -> property definition (includes 'type')."""
        if data_source_id not in self._schemas:
            ds = self._request("GET", f"/data_sources/{data_source_id}")
            self._schemas[data_source_id] = ds.get("properties", {})
        return self._schemas[data_source_id]

    def query(self, data_source_id: str, filter: dict | None = None) -> Iterator[dict]:
        body: dict[str, Any] = {"page_size": 100}
        if filter:
            body["filter"] = filter
        while True:
            data = self._request("POST", f"/data_sources/{data_source_id}/query", body)
            yield from data.get("results", [])
            if not data.get("has_more"):
                return
            body["start_cursor"] = data["next_cursor"]

    def get_page(self, page_id: str) -> dict:
        return self._request("GET", f"/pages/{parse_id(page_id)}")

    def update_page(self, page_id: str, properties: dict) -> dict:
        return self._request("PATCH", f"/pages/{parse_id(page_id)}", {"properties": properties})
