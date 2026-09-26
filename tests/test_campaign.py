from datetime import date

import pytest

from notion_chimp.campaign import Campaign, KilledError
from notion_chimp.tracking import Tracker

from .conftest import FakeNotion, FakeSender, make_page

TODAY = date(2026, 10, 1)


def rows():
    return [
        make_page("a", "Acme Skis", email="Jane <jane@acme.test>", contact="Jane"),
        make_page("b", "Brewco", email="use the web form", status="Ready"),
        make_page("c", "Cafe", email="c@cafe.test", status="Contacted", next_action="2026-10-05"),
        make_page("d", "Deli", email="d@deli.test", status="Contacted", next_action="2026-09-30"),
        make_page("e", "Eats", email="e@eats.test", status="Declined"),
    ]


def campaign(config, notion, sender=None):
    tracker = Tracker(config.tracking.base_url, config.tracking.secret_key)
    return Campaign(config, notion, sender=sender, tracker=tracker, today=TODAY)


def test_dry_run_plans_without_side_effects(config):
    notion, sender = FakeNotion(rows()), FakeSender()
    results = campaign(config, notion, sender).run(send=False)
    by_id = {r.planned.page_id: r for r in results}
    assert set(by_id) == {"a", "b", "d"}  # c not due yet, e not in sequence
    assert by_id["a"].planned.to == "jane@acme.test"
    assert by_id["a"].planned.subject == "Hello Acme Skis"
    assert "no email address" in by_id["b"].error
    assert sender.sent == [] and notion.updates == []


def test_send_advances_rows_and_tracks_links(config):
    notion, sender = FakeNotion(rows()), FakeSender()
    results = campaign(config, notion, sender).run(send=True)
    assert [r.planned.page_id for r in results if r.sent] == ["a", "d"]
    email = sender.sent[0]
    assert "Hi Jane," in email.text and "the brochure (https://example.com/b.pdf)" in email.text
    assert "https://t.example.com/c/" in email.html and "https://t.example.com/o/" in email.html
    assert "https://example.com/b.pdf" not in email.html

    a = notion.pages["a"]["properties"]
    assert a["Status"]["select"]["name"] == "Contacted"
    assert a["Last Touch"]["date"]["start"] == "2026-10-01"
    assert a["Next Action Date"]["date"]["start"] == "2026-10-08"
    d = notion.pages["d"]["properties"]
    assert d["Status"]["select"]["name"] == "Follow-up 1"
    assert d["Next Action Date"]["date"] is None  # last step clears it


def test_fallback_placeholder(config):
    notion = FakeNotion([make_page("a", "Acme", email="x@acme.test")])
    sender = FakeSender()
    campaign(config, notion, sender).run(send=True)
    assert "Hi there," in sender.sent[0].text


def test_limit(config):
    notion, sender = FakeNotion(rows()), FakeSender()
    campaign(config, notion, sender).run(send=True, limit=1)
    assert len(sender.sent) == 1


def test_send_failure_does_not_advance(config):
    notion = FakeNotion(rows())
    results = campaign(config, notion, FakeSender(fail=True)).run(send=True)
    assert all(not r.sent for r in results)
    assert notion.updates == []


def test_kill_switch_blocks_sending(config, monkeypatch):
    monkeypatch.setenv("NOTION_CHIMP_KILL_SWITCH", "1")
    notion, sender = FakeNotion(rows()), FakeSender()
    with pytest.raises(KilledError):
        campaign(config, notion, sender).run(send=True)
    assert sender.sent == []


def test_test_send_to_override_does_not_advance(config):
    notion, sender = FakeNotion(rows()), FakeSender()
    c = campaign(config, notion, sender)
    p = c.single("b", "initial", to_override="me@example.com")
    assert p.skip is None and p.to == "me@example.com"
    out = c.deliver(p, advance=False)
    assert out.sent and sender.sent[0].to == "me@example.com"
    assert notion.updates == []


def test_tracking_disabled_sends_clean_html(config):
    config.tracking.enabled = False
    notion, sender = FakeNotion(rows()), FakeSender()
    campaign(config, notion, sender).run(send=True, limit=1)
    assert "t.example.com" not in sender.sent[0].html
    assert 'href="https://example.com/b.pdf"' in sender.sent[0].html
