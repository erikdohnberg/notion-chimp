"""Read and build Notion property values without assuming a schema.

Writes look up the property's actual type from the data source, so a
"link clicked" property can be a checkbox, a date, a number or text and
notion-chimp does the sensible thing for each.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

_UUID = re.compile(r"([0-9a-f]{8})-?([0-9a-f]{4})-?([0-9a-f]{4})-?([0-9a-f]{4})-?([0-9a-f]{12})", re.I)

# Which Notion types are acceptable for each role
ROLE_TYPES: dict[str, set[str]] = {
    "email": {"email", "rich_text", "title", "url"},
    "status": {"status", "select"},
    "last_touch": {"date"},
    "next_action_date": {"date"},
    "title": {"title", "rich_text"},
    "open_count": {"number"},
    "first_opened": {"date"},
    "link_clicked": {"checkbox", "date", "number", "rich_text", "url"},
    "last_engagement": {"date"},
}

# What to suggest when a property is missing
SUGGESTED_TYPE = {
    "open_count": "Number",
    "first_opened": "Date",
    "link_clicked": "Checkbox (or Date to record when)",
    "last_engagement": "Date",
    "last_touch": "Date",
    "next_action_date": "Date",
    "status": "Select or Status",
    "email": "Email",
}


def parse_id(ref: str) -> str:
    """Pull a dashed UUID out of a Notion URL, collection:// URL or raw id."""
    matches = _UUID.findall(ref)
    if not matches:
        raise ValueError(f"no Notion id found in {ref!r}")
    # A notion.so URL with ?v= carries the view id last; the object id comes first
    return "-".join(matches[0]).lower()


def _rich(items: list[dict]) -> str:
    return "".join(i.get("plain_text") or i.get("text", {}).get("content", "") for i in items or [])


def read_value(prop: dict | None) -> Any:
    """Return a plain Python value for a page property object."""
    if not prop:
        return None
    t = prop.get("type")
    v = prop.get(t)
    if t in {"title", "rich_text"}:
        return _rich(v)
    if t in {"email", "url", "phone_number", "number", "checkbox"}:
        return v
    if t in {"select", "status"}:
        return v.get("name") if v else None
    if t == "multi_select":
        return [o["name"] for o in v or []]
    if t == "date":
        return v.get("start") if v else None
    if t == "people":
        return [p.get("name") or p.get("id") for p in v or []]
    if t == "formula":
        return v.get(v.get("type")) if v else None
    return v


def plain_text(prop: dict | None) -> str:
    v = read_value(prop)
    if v is None:
        return ""
    if isinstance(v, list):
        return ", ".join(str(x) for x in v)
    if isinstance(v, bool):
        return "Yes" if v else "No"
    return str(v)


def build_value(prop_type: str, value: Any) -> dict:
    """Build the JSON Notion expects when setting a property of this type."""
    if prop_type == "number":
        return {"number": value}
    if prop_type == "checkbox":
        return {"checkbox": bool(value)}
    if prop_type == "date":
        if value is None:
            return {"date": None}
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        return {"date": {"start": value}}
    if prop_type == "select":
        return {"select": {"name": value} if value else None}
    if prop_type == "status":
        return {"status": {"name": value} if value else None}
    if prop_type in {"rich_text", "title"}:
        return {prop_type: [{"type": "text", "text": {"content": str(value or "")[:2000]}}]}
    if prop_type in {"url", "email"}:
        return {prop_type: value or None}
    raise ValueError(f"notion-chimp can't write properties of type {prop_type!r}")


def status_filter(prop_name: str, prop_type: str, value: str) -> dict:
    return {"property": prop_name, prop_type: {"equals": value}}
