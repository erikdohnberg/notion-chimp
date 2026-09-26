from pathlib import Path

import pytest

from notion_chimp.config import ConfigError, load_config, parse_config
from notion_chimp.properties import build_value, parse_id
from notion_chimp.templates import Template, TemplateError, to_html

from .conftest import make_page

ROOT = Path(__file__).resolve().parent.parent


def test_example_config_loads(secret):
    cfg = load_config(ROOT / "examples/sponsor-outreach/config.yaml")
    assert cfg.properties.status == "Status"
    assert [s.name for s in cfg.sequence] == ["initial", "follow-up-1", "follow-up-2"]
    assert cfg.tracking.base_url == "https://t.example.com"
    for s in cfg.sequence:
        Template.load(s.template)


def test_missing_required(secret):
    with pytest.raises(ConfigError):
        parse_config({"notion": {"data_source": "x"}, "properties": {"email": "E"}})


def test_parse_id():
    assert parse_id("collection://0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d") == "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    assert parse_id("https://www.notion.so/ws/aaaabbbbccccddddeeeeffff00001111?v=abcdefabcdefabcdefabcdefabcdefab") \
        == "aaaabbbb-cccc-dddd-eeee-ffff00001111"


def test_build_value():
    assert build_value("status", "Done") == {"status": {"name": "Done"}}
    assert build_value("date", None) == {"date": None}
    with pytest.raises(ValueError):
        build_value("relation", [])


def test_template_errors_and_braces():
    page = make_page("a", "Acme")["properties"]
    t = Template.parse("Subject: {{literal}} {Company}\n\nBody {Contact Name|friend}")
    assert t.render(page) == ("{literal} Acme", "Body friend")
    with pytest.raises(TemplateError):
        Template.parse("Subject: x\n\n{Nope}").render(page)
    with pytest.raises(TemplateError):
        Template.parse("Subject: x\n\n{Contact Name}").render(page)
    with pytest.raises(TemplateError):
        Template.parse("no subject line")


def test_to_html_escapes_and_links():
    out = to_html("A <b> & [x](https://e.com/?a=1&b=2)\nsee https://e.com/p.")
    assert "&lt;b&gt; &amp;" in out
    assert '<a href="https://e.com/?a=1&amp;b=2">x</a>' in out
    assert '<a href="https://e.com/p">https://e.com/p</a>.' in out
