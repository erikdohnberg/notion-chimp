"""Email templates.

A template is a text file whose first line is ``Subject: ...``, then a blank
line, then the body. Placeholders are Notion property names in braces:

    Hi {Contact Name|there},

``{Name|fallback}`` uses the fallback when the property is empty. ``{{`` and
``}}`` produce literal braces. Links can be bare URLs or ``[text](url)``;
both become tracked links in the HTML part.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path

from .properties import plain_text

_PLACEHOLDER = re.compile(r"\{([^{}|]+)(?:\|([^{}]*))?\}")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?<![\"'>(])\bhttps?://[^\s<]+[^\s<.,;:!?)\]'\"]")


class TemplateError(ValueError):
    pass


@dataclass
class Template:
    subject: str
    body: str
    path: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "Template":
        return cls.parse(path.read_text(encoding="utf-8"), path)

    @classmethod
    def parse(cls, source: str, path: Path | None = None) -> "Template":
        lines = source.lstrip("﻿").splitlines()
        if not lines or not lines[0].lower().startswith("subject:"):
            raise TemplateError(f"{path or 'template'}: first line must be 'Subject: ...'")
        subject = lines[0].split(":", 1)[1].strip()
        body = "\n".join(lines[1:]).strip("\n")
        return cls(subject=subject, body=body, path=path)

    def placeholders(self) -> set[str]:
        text = (self.subject + "\n" + self.body).replace("{{", "").replace("}}", "")
        return {m.group(1).strip() for m in _PLACEHOLDER.finditer(text)}

    def render(self, page_properties: dict) -> tuple[str, str]:
        return _fill(self.subject, page_properties), _fill(self.body, page_properties)


def _fill(text: str, props: dict) -> str:
    text = text.replace("{{", "\x00").replace("}}", "\x01")

    def sub(m: re.Match) -> str:
        name, fallback = m.group(1).strip(), m.group(2)
        if name not in props:
            raise TemplateError(f"template uses {{{name}}} but the database has no property named {name!r}")
        value = plain_text(props[name]).strip()
        if not value:
            if fallback is None:
                raise TemplateError(f"property {name!r} is empty for this row; add a fallback like {{{name}|...}}")
            return fallback
        return value

    return _PLACEHOLDER.sub(sub, text).replace("\x00", "{").replace("\x01", "}")


def to_plain(body: str) -> str:
    return _MD_LINK.sub(lambda m: f"{m.group(1)} ({m.group(2)})", body)


def to_html(body: str) -> str:
    """Very small text -> HTML: paragraphs, line breaks and links."""
    paragraphs = re.split(r"\n\s*\n", body.strip())
    out = []
    for para in paragraphs:
        links: list[str] = []

        def stash(m: re.Match) -> str:
            links.append(f'<a href="{html.escape(m.group(2))}">{html.escape(m.group(1))}</a>')
            return f"\x02{len(links) - 1}\x03"

        p = _MD_LINK.sub(stash, para)
        p = html.escape(p)
        p = _BARE_URL.sub(lambda m: f'<a href="{m.group(0)}">{m.group(0)}</a>', p)
        p = re.sub(r"\x02(\d+)\x03", lambda m: links[int(m.group(1))], p)
        out.append("<p>" + p.replace("\n", "<br>\n") + "</p>")
    return ('<!doctype html><html><body style="font-family:Arial,Helvetica,sans-serif;'
            'font-size:14px;line-height:1.5;color:#222">\n' + "\n".join(out) + "\n</body></html>")
