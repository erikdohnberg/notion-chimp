"""notion-chimp command line.

    notion-chimp gen-key                      new tracking secret
    notion-chimp auth-gmail                   one-time Gmail OAuth consent
    notion-chimp -c config.yaml check         validate config against your database
    notion-chimp -c config.yaml run           dry run: show what would send
    notion-chimp -c config.yaml run --send    actually send and advance rows
    notion-chimp -c config.yaml test-send --page URL --to you@example.com
    notion-chimp -c config.yaml link --page URL --url https://...
                                              tracked link for an email you write by hand
    notion-chimp -c config.yaml serve         run the tracking server
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from dotenv import load_dotenv

from .config import Config, ConfigError, load_config
from .properties import ROLE_TYPES, SUGGESTED_TYPE
from .templates import Template, TemplateError
from .tracking import generate_key


def _notion(config: Config):
    from .notion import NotionClient
    return NotionClient(config.notion_token)


def _tracker(config: Config):
    from .tracking import Tracker
    if not config.tracking.enabled:
        return None
    return Tracker(config.tracking.base_url, config.tracking.secret_key)


def _sender(config: Config):
    from .senders import get_sender
    return get_sender(config.sender.provider, config.sender.options)


def cmd_gen_key(args, config=None) -> int:
    print(generate_key())
    return 0


def cmd_auth_gmail(args, config=None) -> int:
    from .senders.gmail import authorize
    options = config.sender.options if config else {}
    authorize(options, open_browser=not args.no_browser)
    print("Gmail authorized. Token saved; keep it out of git.")
    return 0


def cmd_check(args, config: Config) -> int:
    problems: list[str] = []
    notes: list[str] = []
    if config.killed():
        notes.append("kill switch is ON: nothing will send and no engagement will be written")
    if config.tracking.enabled:
        if not config.tracking.base_url:
            problems.append("tracking.base_url is empty (set NOTION_CHIMP_BASE_URL)")
        if not config.tracking.secret_key:
            problems.append("tracking secret key is empty (run `notion-chimp gen-key`)")
    else:
        notes.append("tracking is disabled; emails go out without pixel or click links")

    notion = _notion(config)
    ds = notion.resolve_data_source(config.data_source)
    schema = notion.schema(ds)
    types = {n: p["type"] for n, p in schema.items()}
    print(f"Data source {ds}: {len(types)} properties")

    missing = []
    for role, name in config.properties.all_roles().items():
        if name not in types:
            missing.append((role, name))
        elif types[name] not in ROLE_TYPES[role]:
            problems.append(f"{role} -> {name!r} is {types[name]}, expected one of {sorted(ROLE_TYPES[role])}")
        else:
            print(f"  ok  {role:17} -> {name} ({types[name]})")
    for role, name in missing:
        target = problems if role not in config.properties.tracking_roles() else notes
        target.append(f"missing property {name!r} for {role}; add it in Notion as {SUGGESTED_TYPE.get(role, '?')}")
    if missing:
        notes.append("notion-chimp never creates or changes properties; add missing ones yourself")

    status_def = schema.get(config.properties.status, {})
    options = {o["name"] for o in (status_def.get(status_def.get("type"), {}) or {}).get("options", [])}
    for step in config.sequence:
        for s in (step.when_status, step.set_status):
            if options and s not in options:
                problems.append(f"step {step.name}: status {s!r} is not an option on {config.properties.status!r}")
        try:
            t = Template.load(step.template)
        except (OSError, TemplateError) as e:
            problems.append(f"step {step.name}: {e}")
            continue
        for ph in sorted(t.placeholders() - set(types)):
            problems.append(f"step {step.name}: template uses {{{ph}}} which is not a property")

    for n in notes:
        print(f"  note  {n}")
    for p in problems:
        print(f"  FAIL  {p}")
    print("OK" if not problems else f"{len(problems)} problem(s)")
    return 1 if problems else 0


def _print_plan(results) -> None:
    for r in results:
        p = r.planned
        state = "SENT" if r.sent else ("SKIP" if r.error else "WOULD SEND")
        line = f"[{state}] {p.step.name:12} {p.label} <{p.to or '-'}>"
        if p.subject and not p.skip:
            line += f"  \"{p.subject}\""
        if r.error:
            line += f"  ({r.error})"
        print(line)


def cmd_run(args, config: Config) -> int:
    from .campaign import Campaign, KilledError
    if args.send and config.killed():
        print("Kill switch is on. Refusing to send.", file=sys.stderr)
        return 2
    sender = _sender(config) if args.send else None
    campaign = Campaign(config, _notion(config), sender=sender, tracker=_tracker(config))
    try:
        results = campaign.run(send=args.send, limit=args.limit)
    except KilledError as e:
        print(str(e), file=sys.stderr)
        return 2
    _print_plan(results)
    if not args.send:
        print("\nDry run. Nothing sent, no rows changed. Add --send to send.")
    return 1 if any(r.error and r.sent for r in results) else 0


def cmd_test_send(args, config: Config) -> int:
    from .campaign import Campaign, Outcome
    if config.killed():
        print("Kill switch is on. Refusing to send.", file=sys.stderr)
        return 2
    step = args.step or config.sequence[0].name
    campaign = Campaign(config, _notion(config), sender=_sender(config), tracker=_tracker(config))
    planned = campaign.single(args.page, step, to_override=args.to)
    if planned.skip:
        print(f"Can't send: {planned.skip}", file=sys.stderr)
        return 1
    planned.subject = f"[TEST] {planned.subject}"
    result: Outcome = campaign.deliver(planned, advance=args.advance)
    _print_plan([result])
    if result.sent:
        print("\nOpen it from the recipient inbox (not your Sent folder) to register an open.")
    return 0 if result.sent and not result.error else 1


def cmd_link(args, config: Config) -> int:
    """Print tracked links (and optionally the open pixel) for one row, for
    pasting into an email you write yourself."""
    from .properties import parse_id
    from .tracking import Tracker
    if not args.url and not args.pixel:
        print("Nothing to do: pass --url and/or --pixel", file=sys.stderr)
        return 2
    tracker = Tracker(config.tracking.base_url, config.tracking.secret_key)
    page_id = parse_id(args.page)
    label = page_id
    if not args.offline:
        # Catch typos now: a link for the wrong row would track silently into nothing
        notion = _notion(config)
        page = notion.get_page(page_id)
        ds = notion.resolve_data_source(config.data_source)
        parent = (page.get("parent") or {}).get("data_source_id")
        if parent and parent.replace("-", "") != ds.replace("-", ""):
            print("Error: that page is not a row in the configured database", file=sys.stderr)
            return 1
        from .campaign import row_label
        label = row_label(config, page.get("properties", {}))
    meta = Tracker.metadata(page_id, args.step)
    print(f"# {label}  (step: {args.step})", file=sys.stderr)
    for url in args.url:
        print(tracker.click_url(url, meta))
    if args.pixel:
        print(tracker.pixel_tag(meta))
    return 0


def cmd_serve(args, config: Config) -> int:
    from .server import create_app
    app = create_app(config)
    app.run(host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_dotenv(os.environ.get("NOTION_CHIMP_ENV_FILE", ".env"))
    parser = argparse.ArgumentParser(prog="notion-chimp", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-c", "--config", default=os.environ.get("NOTION_CHIMP_CONFIG", "notion-chimp.yaml"))
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("gen-key", help="print a new tracking secret key").set_defaults(fn=cmd_gen_key, needs_config=False)

    p = sub.add_parser("auth-gmail", help="authorize Gmail sending (one time)")
    p.add_argument("--no-browser", action="store_true", help="print the consent URL instead of opening a browser")
    p.set_defaults(fn=cmd_auth_gmail, needs_config=False)

    sub.add_parser("check", help="validate config against the Notion database").set_defaults(fn=cmd_check)

    p = sub.add_parser("run", help="send due steps (dry run unless --send)")
    p.add_argument("--send", action="store_true", help="actually send and update rows")
    p.add_argument("--limit", type=int, help="send at most N emails this run")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("test-send", help="send one row's email to yourself")
    p.add_argument("--page", required=True, help="Notion page URL or id of the test row")
    p.add_argument("--to", required=True, help="where to send the test (your own address)")
    p.add_argument("--step", help="sequence step to render (default: first step)")
    p.add_argument("--advance", action="store_true", help="also advance the row's status and dates")
    p.set_defaults(fn=cmd_test_send)

    p = sub.add_parser("link", help="make tracked links for an email you write yourself")
    p.add_argument("--page", required=True, help="Notion page URL or id of the recipient's row")
    p.add_argument("--url", action="append", default=[], help="destination URL (repeat for several)")
    p.add_argument("--pixel", action="store_true", help="also print the open-tracking <img> tag")
    p.add_argument("--step", default="manual", help="label for this email (default: manual)")
    p.add_argument("--offline", action="store_true", help="skip checking the row in Notion")
    p.set_defaults(fn=cmd_link)

    p = sub.add_parser("serve", help="run the tracking server (use gunicorn in production)")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    config = None
    if getattr(args, "needs_config", True) or os.path.exists(args.config):
        try:
            config = load_config(args.config)
        except FileNotFoundError:
            print(f"Config not found: {args.config}. Pass -c path/to/config.yaml", file=sys.stderr)
            return 2
        except ConfigError as e:
            print(f"Config error: {e}", file=sys.stderr)
            return 2
    try:
        return args.fn(args, config)
    except (ValueError, RuntimeError, FileNotFoundError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
