"""Vercel entry point. Vercel's Flask support looks for `app` in app.py.

Configure the deployment with environment variables (see README, "Deploying
to Vercel"): NOTION_CHIMP_CONFIG_YAML, NOTION_TOKEN, NOTION_CHIMP_SECRET_KEY,
NOTION_CHIMP_BASE_URL.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from notion_chimp.wsgi import app  # noqa: E402,F401
