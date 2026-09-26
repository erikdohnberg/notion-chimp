import copy

import pytest
from cryptography.fernet import Fernet

from notion_chimp.config import parse_config

DS = "11111111-2222-3333-4444-555555555555"

SCHEMA = {
    "Company": {"type": "title"},
    "Contact Name": {"type": "rich_text"},
    "Contact Email or Route": {"type": "rich_text"},
    "Status": {"type": "select", "select": {"options": [
        {"name": n} for n in ["Ready", "Contacted", "Follow-up 1", "Follow-up 2", "Declined"]]}},
    "Last Touch": {"type": "date"},
    "Next Action Date": {"type": "date"},
    "Open Count": {"type": "number"},
    "First Opened": {"type": "date"},
    "Brochure Clicked": {"type": "checkbox"},
    "Last Engagement": {"type": "date"},
}


def rich(t):
    return [{"plain_text": t, "text": {"content": t}}] if t else []


def make_page(pid, company, email="", status="Ready", next_action=None, contact="", **extra):
    props = {
        "Company": {"type": "title", "title": rich(company)},
        "Contact Name": {"type": "rich_text", "rich_text": rich(contact)},
        "Contact Email or Route": {"type": "rich_text", "rich_text": rich(email)},
        "Status": {"type": "select", "select": {"name": status}},
        "Last Touch": {"type": "date", "date": None},
        "Next Action Date": {"type": "date", "date": {"start": next_action} if next_action else None},
        "Open Count": {"type": "number", "number": None},
        "First Opened": {"type": "date", "date": None},
        "Brochure Clicked": {"type": "checkbox", "checkbox": False},
        "Last Engagement": {"type": "date", "date": None},
    }
    props.update(extra)
    return {"id": pid, "properties": props}


class FakeNotion:
    def __init__(self, pages, schema=SCHEMA):
        self.pages = {p["id"]: p for p in pages}
        self._schema = schema
        self.updates = []

    def resolve_data_source(self, ref):
        return DS

    def schema(self, ds):
        return self._schema

    def query(self, ds, filter=None):
        for p in self.pages.values():
            if filter:
                prop = p["properties"][filter["property"]]
                t = prop["type"]
                want = filter[t]["equals"]
                if (prop[t] or {}).get("name") != want:
                    continue
            yield copy.deepcopy(p)

    def get_page(self, pid):
        return copy.deepcopy(self.pages[pid])

    def update_page(self, pid, properties):
        self.updates.append((pid, properties))
        page = self.pages[pid]
        for name, value in properties.items():
            t = self._schema[name]["type"]
            page["properties"][name] = {"type": t, t: value[t]}


class FakeSender:
    name = "fake"

    def __init__(self, fail=False):
        self.sent = []
        self.fail = fail

    def send(self, email):
        if self.fail:
            raise RuntimeError("smtp down")
        self.sent.append(email)
        return f"msg-{len(self.sent)}"


@pytest.fixture
def secret(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NOTION_CHIMP_SECRET_KEY", key)
    monkeypatch.setenv("NOTION_TOKEN", "secret_test")
    monkeypatch.setenv("NOTION_CHIMP_BASE_URL", "https://t.example.com")
    monkeypatch.delenv("NOTION_CHIMP_KILL_SWITCH", raising=False)
    return key


@pytest.fixture
def config(secret, tmp_path):
    tdir = tmp_path / "templates"
    tdir.mkdir()
    (tdir / "initial.txt").write_text(
        "Subject: Hello {Company}\n\nHi {Contact Name|there},\n\nSee [the brochure](https://example.com/b.pdf).\n"
    )
    (tdir / "fu.txt").write_text("Subject: Re: {Company}\n\nFollowing up. https://example.com/b.pdf\n")
    raw = {
        "name": "test",
        "timezone": "America/Toronto",
        "notion": {"data_source": f"collection://{DS}"},
        "properties": {
            "title": "Company",
            "email": "Contact Email or Route",
            "status": "Status",
            "last_touch": "Last Touch",
            "next_action_date": "Next Action Date",
            "open_count": "Open Count",
            "first_opened": "First Opened",
            "link_clicked": "Brochure Clicked",
            "last_engagement": "Last Engagement",
        },
        "sequence": [
            {"name": "initial", "when_status": "Ready", "template": "templates/initial.txt",
             "set_status": "Contacted", "next_action_in_days": 7},
            {"name": "fu", "when_status": "Contacted", "template": "templates/fu.txt",
             "set_status": "Follow-up 1"},
        ],
        "sender": {"provider": "gmail", "from_address": "me@example.com", "from_name": "Me"},
        "tracking": {"base_url": "${NOTION_CHIMP_BASE_URL}", "filters": {"dedupe_minutes": 30}},
        "kill_switch": {"file": "KILL"},
    }
    return parse_config(raw, base_dir=tmp_path)
