from notion_chimp import cli
from notion_chimp.tracking import Tracker

from .conftest import DS, FakeNotion, make_page

PAGE = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"


def run_link(monkeypatch, config, capsys, args, pages=None, parent=DS):
    page = make_page(PAGE, "Acme Skis")
    page["parent"] = {"type": "data_source_id", "data_source_id": parent}
    monkeypatch.setattr(cli, "_notion", lambda c: FakeNotion(pages if pages is not None else [page]))
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    code = cli.main(["-c", "x.yaml", "link", "--page", f"https://www.notion.so/{PAGE.replace('-', '')}"] + args)
    out = capsys.readouterr()
    return code, out.out.strip().splitlines(), out.err


def test_link_prints_tracked_urls_that_decode(monkeypatch, config, capsys):
    code, lines, err = run_link(monkeypatch, config, capsys,
                                ["--url", "https://example.com/a.pdf", "--url", "https://example.com/b", "--pixel"])
    assert code == 0 and "Acme Skis" in err
    assert len(lines) == 3
    t = Tracker(config.tracking.base_url, config.tracking.secret_key)
    hit = t.decode(lines[0].split("/c/")[1], is_open=False)
    assert (hit.page_id, hit.step, hit.url) == (PAGE, "manual", "https://example.com/a.pdf")
    assert t.decode(lines[1].split("/c/")[1], is_open=False).url == "https://example.com/b"
    assert lines[2].startswith('<img src="https://t.example.com/o/') and lines[2].count(".gif") == 1


def test_link_rejects_row_from_another_database(monkeypatch, config, capsys):
    code, lines, err = run_link(monkeypatch, config, capsys, ["--url", "https://example.com"],
                                parent="99999999-9999-9999-9999-999999999999")
    assert code == 1 and lines == [] and "not a row" in err


def test_link_offline_skips_notion(monkeypatch, config, capsys):
    monkeypatch.setattr(cli, "_notion", lambda c: (_ for _ in ()).throw(AssertionError("no Notion call")))
    monkeypatch.setattr(cli, "load_config", lambda path: config)
    code = cli.main(["-c", "x.yaml", "link", "--page", PAGE, "--url", "https://example.com", "--offline"])
    assert code == 0 and "/c/" in capsys.readouterr().out


def test_link_needs_url_or_pixel(monkeypatch, config, capsys):
    code, _, err = run_link(monkeypatch, config, capsys, [])
    assert code == 2 and "--url" in err
