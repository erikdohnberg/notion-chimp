from notion_chimp.engagement import EngagementRecorder, Request, filter_reason
from notion_chimp.tracking import Hit

from .conftest import DS, FakeNotion, make_page

HUMAN = Request("GET", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "1.2.3.4")
GMAIL_PROXY = Request("GET", "Mozilla/5.0 (Windows NT 5.1; rv:11.0) Gecko Firefox/11.0 (via ggpht.com GoogleImageProxy)", "66.249.1.1")


def hit(sent_at=0, url=None):
    return Hit(page_id="p1", step="initial", sent_at=sent_at, url=url)


def test_filters(config):
    f = config.tracking.filters
    assert filter_reason(hit(), HUMAN, f, True, now=1000) is None
    assert filter_reason(hit(), GMAIL_PROXY, f, True, now=1000) is None
    assert filter_reason(hit(), Request("HEAD", HUMAN.user_agent, ""), f, True, now=1000) == "head-request"
    assert filter_reason(hit(sent_at=990), HUMAN, f, True, now=1000) == "too-soon-after-send"
    assert filter_reason(hit(sent_at=995), HUMAN, f, False, now=1000) == "too-soon-after-send"
    assert filter_reason(hit(), Request("GET", "Mozilla/5.0", ""), f, True, now=1000) == "apple-mpp-prefetch"
    assert filter_reason(hit(), Request("GET", "Barracuda Sentinel", ""), f, False, now=1000).startswith("user-agent")
    f.apple_mpp = "count"
    assert filter_reason(hit(), Request("GET", "Mozilla/5.0", ""), f, True, now=1000) is None


def test_open_writes_count_first_opened_and_engagement(config):
    notion = FakeNotion([make_page("p1", "Acme")])
    rec = EngagementRecorder(config, notion, DS)
    assert rec.handle(hit(), HUMAN, is_open=True, now=1000) == "recorded"
    props = notion.pages["p1"]["properties"]
    assert props["Open Count"]["number"] == 1
    first = props["First Opened"]["date"]["start"]
    assert props["Last Engagement"]["date"]["start"]

    # inside the dedupe window: ignored
    assert rec.handle(hit(), HUMAN, is_open=True, now=1100) == "duplicate-open"
    # after the window: counted, first-opened unchanged
    assert rec.handle(hit(), HUMAN, is_open=True, now=1000 + 31 * 60) == "recorded"
    assert props["Open Count"]["number"] == 2
    assert props["First Opened"]["date"]["start"] == first


def test_click_sets_checkbox(config):
    notion = FakeNotion([make_page("p1", "Acme")])
    rec = EngagementRecorder(config, notion, DS)
    assert rec.handle(hit(url="https://example.com/b.pdf"), HUMAN, is_open=False, now=1000) == "recorded"
    props = notion.pages["p1"]["properties"]
    assert props["Brochure Clicked"]["checkbox"] is True
    assert props["Open Count"]["number"] is None


def test_missing_tracking_properties_are_skipped(config):
    schema = {k: v for k, v in FakeNotion([]).schema(DS).items() if k not in {"Open Count", "Brochure Clicked"}}
    notion = FakeNotion([make_page("p1", "Acme")], schema=schema)
    rec = EngagementRecorder(config, notion, DS)
    rec.handle(hit(), HUMAN, is_open=True, now=1000)
    written = notion.updates[0][1]
    assert "Open Count" not in written and "First Opened" in written


def test_kill_switch_and_disabled(config, monkeypatch):
    notion = FakeNotion([make_page("p1", "Acme")])
    rec = EngagementRecorder(config, notion, DS)
    monkeypatch.setenv("NOTION_CHIMP_KILL_SWITCH", "1")
    assert rec.handle(hit(), HUMAN, is_open=True, now=1000) == "killed"
    monkeypatch.delenv("NOTION_CHIMP_KILL_SWITCH")
    config.kill_switch_file.write_text("")
    assert rec.handle(hit(), HUMAN, is_open=True, now=1000) == "killed"
    config.kill_switch_file.unlink()
    config.tracking.enabled = False
    assert rec.handle(hit(), HUMAN, is_open=True, now=1000) == "disabled"
    assert notion.updates == []
