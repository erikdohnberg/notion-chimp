import time

from notion_chimp.engagement import EngagementRecorder
from notion_chimp.server import create_app
from notion_chimp.tracking import PIXEL_GIF, Tracker

from .conftest import DS, FakeNotion, make_page

UA = {"User-Agent": "Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15"}


def setup(config):
    notion = FakeNotion([make_page("p1", "Acme")])
    tracker = Tracker(config.tracking.base_url, config.tracking.secret_key)
    app = create_app(config, recorder=EngagementRecorder(config, notion, DS), tracker=tracker, background=False)
    meta = Tracker.metadata("p1", "initial", sent_at=int(time.time()) - 3600)
    return app.test_client(), notion, tracker, meta


def test_pixel_records_open(config):
    client, notion, tracker, meta = setup(config)
    path = tracker.open_url(meta).replace(config.tracking.base_url, "")
    resp = client.get(path, headers=UA)
    assert resp.status_code == 200 and resp.data == PIXEL_GIF
    assert resp.mimetype == "image/gif" and "no-store" in resp.headers["Cache-Control"]
    assert notion.pages["p1"]["properties"]["Open Count"]["number"] == 1


def test_bad_pixel_token_still_returns_gif(config):
    client, notion, _, _ = setup(config)
    resp = client.get("/o/garbage.gif")
    assert resp.status_code == 200 and resp.data == PIXEL_GIF
    assert notion.updates == []


def test_click_redirects_and_records(config):
    client, notion, tracker, meta = setup(config)
    path = tracker.click_url("https://example.com/b.pdf", meta).replace(config.tracking.base_url, "")
    resp = client.get(path, headers=UA)
    assert resp.status_code == 302 and resp.headers["Location"] == "https://example.com/b.pdf"
    assert notion.pages["p1"]["properties"]["Brochure Clicked"]["checkbox"] is True


def test_head_click_redirects_without_recording(config):
    client, notion, tracker, meta = setup(config)
    path = tracker.click_url("https://example.com/b.pdf", meta).replace(config.tracking.base_url, "")
    resp = client.head(path, headers=UA)
    assert resp.status_code == 302
    assert notion.updates == []


def test_forged_click_is_404(config):
    client, _, _, _ = setup(config)
    assert client.get("/c/eyJ1cmwiOiAiaHR0cHM6Ly9ldmlsLmNvbSJ9").status_code == 404


def test_kill_switch_still_serves_but_does_not_write(config, monkeypatch):
    client, notion, tracker, meta = setup(config)
    monkeypatch.setenv("NOTION_CHIMP_KILL_SWITCH", "true")
    path = tracker.click_url("https://example.com/b.pdf", meta).replace(config.tracking.base_url, "")
    assert client.get(path, headers=UA).status_code == 302
    assert client.get("/healthz").json["killed"] is True
    assert notion.updates == []
