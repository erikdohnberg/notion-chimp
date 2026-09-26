"""Load and validate a notion-chimp YAML config.

Nothing in here knows about any particular database. Every property name comes
from the config file, and ``${VAR}`` references are expanded from the
environment so secrets stay out of the file.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

_ENV_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")
_TRUTHY = {"1", "true", "yes", "on"}

DEFAULT_IGNORED_USER_AGENTS = [
    # Link and attachment scanners that fetch every URL in a message
    "barracuda",
    "mimecast",
    "proofpoint",
    "symantec",
    "trendmicro",
    "forcepoint",
    "safelinks",
    # Generic HTTP clients and crawlers, never a human reading mail
    "python-requests",
    "curl/",
    "wget/",
    "go-http-client",
    "bot",
    "spider",
    "crawler",
    "preview",
]


class ConfigError(ValueError):
    pass


@dataclass
class PropertyMap:
    """Maps notion-chimp's roles to the property names in *your* database."""

    email: str
    status: str
    last_touch: str
    next_action_date: str
    title: str | None = None
    open_count: str | None = None
    first_opened: str | None = None
    link_clicked: str | None = None
    last_engagement: str | None = None

    def tracking_roles(self) -> dict[str, str]:
        roles = {
            "open_count": self.open_count,
            "first_opened": self.first_opened,
            "link_clicked": self.link_clicked,
            "last_engagement": self.last_engagement,
        }
        return {k: v for k, v in roles.items() if v}

    def all_roles(self) -> dict[str, str]:
        roles = {
            "email": self.email,
            "status": self.status,
            "last_touch": self.last_touch,
            "next_action_date": self.next_action_date,
            "title": self.title,
        }
        roles.update(self.tracking_roles())
        return {k: v for k, v in roles.items() if v}


@dataclass
class Step:
    name: str
    when_status: str
    template: Path
    set_status: str
    next_action_in_days: int | None = None


@dataclass
class FilterConfig:
    min_seconds_after_send: int = 30
    click_min_seconds_after_send: int = 10
    dedupe_minutes: int = 30
    apple_mpp: str = "skip"  # "skip" or "count"
    ignore_user_agents: list[str] = field(default_factory=lambda: list(DEFAULT_IGNORED_USER_AGENTS))
    ignore_ips: list[str] = field(default_factory=list)


@dataclass
class TrackingConfig:
    enabled: bool
    base_url: str
    secret_key: str
    filters: FilterConfig


@dataclass
class SenderConfig:
    provider: str
    from_address: str
    from_name: str | None = None
    reply_to: str | None = None
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class Config:
    name: str
    data_source: str
    notion_token: str
    timezone: str
    properties: PropertyMap
    sequence: list[Step]
    sender: SenderConfig
    tracking: TrackingConfig
    kill_switch_env: str = "NOTION_CHIMP_KILL_SWITCH"
    kill_switch_file: Path | None = None
    base_dir: Path = Path(".")

    def killed(self) -> bool:
        """True when the kill switch is on. Checked on every send and every hit,
        so flipping it takes effect without a restart."""
        if os.environ.get(self.kill_switch_env, "").strip().lower() in _TRUTHY:
            return True
        return bool(self.kill_switch_file and self.kill_switch_file.exists())

    def step(self, name: str) -> Step:
        for s in self.sequence:
            if s.name == name:
                return s
        raise ConfigError(f"no step named {name!r}; known steps: {[s.name for s in self.sequence]}")


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_REF.sub(lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [_expand(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    return value


def _require(d: dict, key: str, where: str) -> Any:
    if key not in d or d[key] in (None, ""):
        raise ConfigError(f"missing required setting {where}.{key}")
    return d[key]


def load_config(path: str | Path) -> Config:
    path = Path(path)
    raw = yaml.safe_load(path.read_text()) or {}
    return parse_config(raw, base_dir=path.parent)


def parse_config(raw: dict, base_dir: Path = Path(".")) -> Config:
    raw = _expand(raw)

    notion = _require(raw, "notion", "")
    token_env = notion.get("token_env", "NOTION_TOKEN")
    props_raw = _require(raw, "properties", "")
    properties = PropertyMap(
        email=_require(props_raw, "email", "properties"),
        status=_require(props_raw, "status", "properties"),
        last_touch=_require(props_raw, "last_touch", "properties"),
        next_action_date=_require(props_raw, "next_action_date", "properties"),
        title=props_raw.get("title"),
        open_count=props_raw.get("open_count"),
        first_opened=props_raw.get("first_opened"),
        link_clicked=props_raw.get("link_clicked"),
        last_engagement=props_raw.get("last_engagement"),
    )

    steps = []
    for i, s in enumerate(_require(raw, "sequence", "")):
        where = f"sequence[{i}]"
        days = s.get("next_action_in_days")
        steps.append(
            Step(
                name=_require(s, "name", where),
                when_status=_require(s, "when_status", where),
                template=(base_dir / _require(s, "template", where)).resolve(),
                set_status=_require(s, "set_status", where),
                next_action_in_days=int(days) if days is not None else None,
            )
        )
    names = [s.name for s in steps]
    if len(set(names)) != len(names):
        raise ConfigError("sequence step names must be unique")

    sender_raw = _require(raw, "sender", "")
    sender = SenderConfig(
        provider=_require(sender_raw, "provider", "sender"),
        from_address=_require(sender_raw, "from_address", "sender"),
        from_name=sender_raw.get("from_name"),
        reply_to=sender_raw.get("reply_to"),
        options={k: v for k, v in sender_raw.items()
                 if k not in {"provider", "from_address", "from_name", "reply_to"}},
    )

    tr = raw.get("tracking") or {}
    fr = tr.get("filters") or {}
    filters = FilterConfig(
        min_seconds_after_send=int(fr.get("min_seconds_after_send", 30)),
        click_min_seconds_after_send=int(fr.get("click_min_seconds_after_send", 10)),
        dedupe_minutes=int(fr.get("dedupe_minutes", 30)),
        apple_mpp=str(fr.get("apple_mpp", "skip")).lower(),
        ignore_user_agents=[u.lower() for u in fr.get("ignore_user_agents", DEFAULT_IGNORED_USER_AGENTS)],
        ignore_ips=list(fr.get("ignore_ips", [])),
    )
    if filters.apple_mpp not in {"skip", "count"}:
        raise ConfigError("tracking.filters.apple_mpp must be 'skip' or 'count'")
    enabled = bool(tr.get("enabled", True))
    tracking = TrackingConfig(
        enabled=enabled,
        base_url=str(tr.get("base_url", "")).rstrip("/"),
        secret_key=os.environ.get(tr.get("secret_key_env", "NOTION_CHIMP_SECRET_KEY"), ""),
        filters=filters,
    )

    ks = raw.get("kill_switch") or {}
    ks_file = ks.get("file")

    return Config(
        name=raw.get("name", "notion-chimp"),
        data_source=_require(notion, "data_source", "notion"),
        notion_token=os.environ.get(token_env, ""),
        timezone=raw.get("timezone", "UTC"),
        properties=properties,
        sequence=steps,
        sender=sender,
        tracking=tracking,
        kill_switch_env=ks.get("env", "NOTION_CHIMP_KILL_SWITCH"),
        kill_switch_file=(base_dir / ks_file).resolve() if ks_file else None,
        base_dir=base_dir,
    )
