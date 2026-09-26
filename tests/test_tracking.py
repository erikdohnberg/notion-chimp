from notion_chimp.tracking import PIXEL_GIF, Tracker


def test_round_trip_open_and_click(secret):
    t = Tracker("https://t.example.com/", secret)
    meta = Tracker.metadata("page-1", "initial", sent_at=1000)
    open_url = t.open_url(meta)
    assert open_url.startswith("https://t.example.com/o/") and open_url.endswith(".gif")
    token = open_url.split("/o/", 1)[1]
    hit = t.decode(token, is_open=True)
    assert (hit.page_id, hit.step, hit.sent_at, hit.url) == ("page-1", "initial", 1000, None)

    click = t.click_url("https://example.com/b.pdf?x=1&y=2", meta)
    hit = t.decode(click.split("/c/", 1)[1], is_open=False)
    assert hit.url == "https://example.com/b.pdf?x=1&y=2"


def test_tokens_are_encrypted_and_unforgeable(secret):
    t = Tracker("https://t.example.com", secret)
    token = t.click_url("https://example.com", Tracker.metadata("secret-page", "s")).split("/c/")[1]
    assert "secret-page" not in token
    assert t.decode("not-a-token", is_open=False) is None
    other = Tracker("https://t.example.com", "x" * 43 + "=")
    assert other.decode(token, is_open=False) is None


def test_instrument_html_rewrites_links_and_adds_pixel(secret):
    t = Tracker("https://t.example.com", secret)
    html = '<html><body><a href="https://example.com/a?x=1&amp;y=2">A</a> <a href="mailto:x@y.z">m</a></body></html>'
    out = t.instrument_html(html, Tracker.metadata("p", "s", 0))
    assert "https://example.com/a" not in out
    assert 'href="mailto:x@y.z"' in out
    assert out.count("https://t.example.com/c/") == 1
    assert out.index("/o/") < out.index("</body>")
    token = out.split("https://t.example.com/c/")[1].split('"')[0]
    assert t.decode(token, is_open=False).url == "https://example.com/a?x=1&y=2"


def test_pixel_is_a_gif():
    assert PIXEL_GIF[:6] == b"GIF89a"
