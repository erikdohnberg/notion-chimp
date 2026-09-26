"""Sequence runner: read due rows from Notion, send the right step, advance the row."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Config, Step
from .notion import NotionClient
from .properties import build_value, plain_text, read_value, status_filter
from .senders import OutgoingEmail, Sender
from .templates import Template, TemplateError, to_html, to_plain
from .tracking import Tracker

log = logging.getLogger(__name__)

_EMAIL = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


class KilledError(RuntimeError):
    pass


@dataclass
class Planned:
    page_id: str
    label: str
    step: Step
    to: str | None = None
    subject: str = ""
    body: str = ""
    skip: str | None = None


@dataclass
class Outcome:
    planned: Planned
    sent: bool
    message_id: str | None = None
    error: str | None = None


def row_label(config: Config, props: dict) -> str:
    """Human-readable name for a row: the configured title property, else the title column."""
    title = config.properties.title
    if title and title in props:
        return plain_text(props[title]) or "(untitled)"
    for p in props.values():
        if p.get("type") == "title":
            return plain_text(p) or "(untitled)"
    return "(untitled)"


def extract_email(value: str) -> str | None:
    m = _EMAIL.search(value or "")
    return m.group(0) if m else None


class Campaign:
    def __init__(self, config: Config, notion: NotionClient, sender: Sender | None = None,
                 tracker: Tracker | None = None, today: date | None = None):
        self.config = config
        self.notion = notion
        self.sender = sender
        self.tracker = tracker
        self.tz = ZoneInfo(config.timezone)
        self.today = today or datetime.now(self.tz).date()
        self.data_source_id = notion.resolve_data_source(config.data_source)
        self._templates: dict[str, Template] = {}

    def template(self, step: Step) -> Template:
        if step.name not in self._templates:
            self._templates[step.name] = Template.load(step.template)
        return self._templates[step.name]

    def _types(self) -> dict[str, str]:
        return {n: p["type"] for n, p in self.notion.schema(self.data_source_id).items()}

    def _label(self, props: dict) -> str:
        return row_label(self.config, props)

    def _is_due(self, props: dict) -> bool:
        raw = read_value(props.get(self.config.properties.next_action_date))
        if not raw:
            return True
        return date.fromisoformat(raw[:10]) <= self.today

    def prepare(self, page: dict, step: Step, to_override: str | None = None) -> Planned:
        props = page.get("properties", {})
        planned = Planned(page_id=page["id"], label=self._label(props), step=step)
        planned.to = to_override or extract_email(plain_text(props.get(self.config.properties.email)))
        if not planned.to:
            planned.skip = "no email address in " + self.config.properties.email
            return planned
        try:
            planned.subject, planned.body = self.template(step).render(props)
        except TemplateError as e:
            planned.skip = str(e)
        return planned

    def plan(self) -> list[Planned]:
        types = self._types()
        status_prop = self.config.properties.status
        status_type = types.get(status_prop)
        if status_type not in {"select", "status"}:
            raise ValueError(f"status property {status_prop!r} must be Select or Status, found {status_type}")
        out: list[Planned] = []
        for step in self.config.sequence:
            flt = status_filter(status_prop, status_type, step.when_status)
            for page in self.notion.query(self.data_source_id, flt):
                if self._is_due(page.get("properties", {})):
                    out.append(self.prepare(page, step))
        return out

    def run(self, send: bool = False, limit: int | None = None) -> list[Outcome]:
        planned = self.plan()
        results: list[Outcome] = []
        sent = 0
        for p in planned:
            if p.skip:
                results.append(Outcome(p, sent=False, error=p.skip))
                continue
            if limit is not None and sent >= limit:
                results.append(Outcome(p, sent=False, error="over --limit"))
                continue
            if not send:
                results.append(Outcome(p, sent=False))
                continue
            results.append(self.deliver(p, advance=True))
            sent += results[-1].sent
        return results

    def deliver(self, p: Planned, advance: bool = True) -> Outcome:
        if self.config.killed():
            raise KilledError("kill switch is on; nothing sent")
        if self.sender is None:
            raise RuntimeError("no sender configured")
        text = to_plain(p.body)
        html = to_html(p.body)
        if self.config.tracking.enabled and self.tracker:
            html = self.tracker.instrument_html(html, Tracker.metadata(p.page_id, p.step.name))
        s = self.config.sender
        email = OutgoingEmail(to=p.to or "", subject=p.subject, text=text, html=html,
                              from_address=s.from_address, from_name=s.from_name, reply_to=s.reply_to)
        try:
            message_id = self.sender.send(email)
        except Exception as e:  # report and keep going with the next row
            log.exception("send failed for %s", p.label)
            return Outcome(p, sent=False, error=f"send failed: {e}")
        if advance:
            try:
                self.advance(p.page_id, p.step)
            except Exception as e:
                # The email went out; make this loud so the row can be fixed by hand
                log.error("SENT but failed to update Notion row %s (%s): %s", p.label, p.page_id, e)
                return Outcome(p, sent=True, message_id=message_id,
                               error=f"sent, but Notion update failed: {e}. Update this row by hand.")
        return Outcome(p, sent=True, message_id=message_id)

    def advance(self, page_id: str, step: Step) -> None:
        props = self.config.properties
        types = self._types()
        updates = {
            props.status: build_value(types[props.status], step.set_status),
            props.last_touch: build_value("date", self.today),
        }
        nxt = self.today + timedelta(days=step.next_action_in_days) if step.next_action_in_days is not None else None
        updates[props.next_action_date] = build_value("date", nxt)
        self.notion.update_page(page_id, updates)

    def single(self, page_ref: str, step_name: str, to_override: str | None = None) -> Planned:
        page = self.notion.get_page(page_ref)
        return self.prepare(page, self.config.step(step_name), to_override=to_override)
