"""Tracking server: two routes plus a health check.

  GET /o/<token>.gif   open pixel, always returns the GIF
  GET /c/<token>       click redirect, 302 to the original URL

Recipients always get their pixel or their redirect, even when the kill switch
is on, the hit is filtered, or Notion is down. Only the write-back is skipped.
"""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor

from flask import Flask, Response, abort, redirect, request

from .config import Config
from .engagement import EngagementRecorder, Request
from .notion import NotionClient
from .tracking import PIXEL_GIF, Hit, Tracker

log = logging.getLogger(__name__)

NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


def _client_request() -> Request:
    forwarded = request.headers.get("X-Forwarded-For", "")
    ip = forwarded.split(",")[0].strip() if forwarded else (request.remote_addr or "")
    return Request(method=request.method, user_agent=request.headers.get("User-Agent", ""), ip=ip)


def create_app(config: Config, recorder: EngagementRecorder | None = None,
               tracker: Tracker | None = None, background: bool | None = None) -> Flask:
    """Build the app. Tracker and Notion client are created on first use, so a
    deployment with missing secrets still starts and reports itself via /healthz.

    On serverless hosts (Vercel sets VERCEL=1) the function can be frozen as
    soon as the response is sent, so writes happen before responding."""
    app = Flask("notion_chimp")
    if background is None:
        background = not os.environ.get("VERCEL")
    pool = ThreadPoolExecutor(max_workers=4) if background else None
    state: dict = {"tracker": tracker, "recorder": recorder}

    def get_tracker() -> Tracker | None:
        if state["tracker"] is None:
            try:
                state["tracker"] = Tracker(config.tracking.base_url, config.tracking.secret_key)
            except ValueError as e:
                log.error("tracking not configured: %s", e)
        return state["tracker"]

    def get_recorder() -> EngagementRecorder:
        if state["recorder"] is None:
            notion = NotionClient(config.notion_token)
            state["recorder"] = EngagementRecorder(config, notion, notion.resolve_data_source(config.data_source))
        return state["recorder"]

    def process(hit: Hit, req: Request, is_open: bool) -> None:
        try:
            outcome = get_recorder().handle(hit, req, is_open)
            log.info("%s page=%s step=%s -> %s", "open" if is_open else "click",
                     hit.page_id, hit.step, outcome)
        except Exception:  # never let a Notion failure break the response
            log.exception("failed to record %s for page %s", "open" if is_open else "click", hit.page_id)

    def dispatch(hit: Hit, is_open: bool) -> None:
        req = _client_request()
        if pool:
            pool.submit(process, hit, req, is_open)
        else:
            process(hit, req, is_open)

    @app.get("/healthz")
    def healthz():
        return {
            "ok": True,
            "killed": config.killed(),
            "tracking_enabled": config.tracking.enabled,
            "notion_token_set": bool(config.notion_token),
            "secret_key_set": bool(config.tracking.secret_key),
        }

    @app.route("/o/<path:token>", methods=["GET", "HEAD"])
    def pixel(token: str):
        t = get_tracker()
        hit = t.decode(token, is_open=True) if t else None
        if hit:
            dispatch(hit, is_open=True)
        return Response(PIXEL_GIF, mimetype="image/gif", headers=NO_CACHE)

    @app.route("/c/<path:token>", methods=["GET", "HEAD"])
    def click(token: str):
        t = get_tracker()
        hit = t.decode(token, is_open=False) if t else None
        if not hit:
            abort(404)
        dispatch(hit, is_open=False)
        resp = redirect(hit.url, code=302)
        resp.headers.update(NO_CACHE)
        return resp

    return app
