"""WSGI entry point for production servers:

    NOTION_CHIMP_CONFIG=config.yaml gunicorn notion_chimp.wsgi:app

On hosts where you deploy straight from a public repo (Vercel, Render...),
put the whole config in the NOTION_CHIMP_CONFIG_YAML environment variable
instead, so your database id and property names stay out of the repo. The
server doesn't read templates, so the sequence section can be copied as is.
"""
import logging
import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .config import load_config, parse_config
from .server import create_app

load_dotenv(os.environ.get("NOTION_CHIMP_ENV_FILE", ".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _config():
    inline = os.environ.get("NOTION_CHIMP_CONFIG_YAML")
    if inline:
        return parse_config(yaml.safe_load(inline) or {}, base_dir=Path.cwd())
    return load_config(os.environ.get("NOTION_CHIMP_CONFIG", "notion-chimp.yaml"))


app = create_app(_config())
