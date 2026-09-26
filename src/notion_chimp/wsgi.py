"""WSGI entry point for production servers:

    NOTION_CHIMP_CONFIG=config.yaml gunicorn notion_chimp.wsgi:app
"""
import logging
import os

from dotenv import load_dotenv

from .config import load_config
from .server import create_app

load_dotenv(os.environ.get("NOTION_CHIMP_ENV_FILE", ".env"))
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
app = create_app(load_config(os.environ.get("NOTION_CHIMP_CONFIG", "notion-chimp.yaml")))
