"""CLI entry point.

  python -m jobpipe init               create tables
  python -m jobpipe bot [--once]       run the Telegram bot (polling)
  python -m jobpipe collect            fetch jobs from all sources
  python -m jobpipe notify [--dry-run] send daily digests
  python -m jobpipe daily              collect from all sources + send digests (manual full run)
  python -m jobpipe digest             send today's digest unless it already went out (what Vercel's timer runs)
  python -m jobpipe verify-companies   check every slug in config/companies.yaml
  python -m jobpipe discover-companies FILE   try slugs on Greenhouse/Lever/Ashby
  python -m jobpipe set-webhook URL    switch the bot to instant webhook mode (optional)
  python -m jobpipe delete-webhook     switch back to polling
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from . import bot, collect, config, db, notify


def _report(title: str, report: dict) -> None:
    print(f"{title}: {json.dumps(report, default=str)}")
    if config.ADMIN_CHAT_ID and config.TELEGRAM_BOT_TOKEN:
        try:
            from .telegram_api import Telegram
            Telegram().send(config.ADMIN_CHAT_ID, f"<b>{title}</b>\n<code>{json.dumps(report, default=str, indent=1)[:3500]}</code>")
        except Exception as exc:  # reporting must never break the run
            logging.warning("admin report failed: %s", exc)


def verify_companies() -> int:
    from .normalize import finalize
    from .sources import ats
    companies = ats.load_companies(config.COMPANIES_FILE)
    bad = 0
    for kind, slug, name in companies:
        try:
            jobs = ats.fetch_board(kind, slug, name)
            india = sum(1 for j in jobs if ats.india_relevant(finalize(j)))
            print(f"  ok   {kind:10} {slug:22} {len(jobs):4} jobs, {india} India-relevant")
        except Exception as exc:
            bad += 1
            print(f"  FAIL {kind:10} {slug:22} {exc}")
    print(f"\n{len(companies) - bad}/{len(companies)} boards working")
    return 1 if bad == len(companies) else 0


def discover_companies(path: str) -> int:
    """Try every slug in a text file on Greenhouse, Lever and Ashby; print the ones with India jobs
    as ready-to-paste companies.yaml lines."""
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from .normalize import finalize
    from .sources import ats
    slugs = [s.strip().lower() for s in Path(path).read_text().splitlines()
             if s.strip() and not s.strip().startswith("#")]
    slugs = list(dict.fromkeys(slugs))
    tries = [(kind, slug) for slug in slugs for kind in ("greenhouse", "lever", "ashby")]

    def probe(t):
        kind, slug = t
        try:
            jobs = ats.fetch_board(kind, slug, slug)
        except Exception:
            return None
        return kind, slug, len(jobs), sum(1 for j in jobs if ats.india_relevant(finalize(j)))

    with ThreadPoolExecutor(max_workers=12) as pool:
        found = [r for r in pool.map(probe, tries) if r]
    print(f"probed {len(slugs)} slugs x 3 platforms, {len(found)} boards exist")
    for kind, slug, total, india in sorted(found, key=lambda r: -r[3]):
        print(f"FOUND {kind} {slug} total={total} india={india}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jobpipe")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    p_bot = sub.add_parser("bot")
    p_bot.add_argument("--once", action="store_true", help="drain pending updates and exit")
    sub.add_parser("collect")
    p_notify = sub.add_parser("notify")
    p_notify.add_argument("--dry-run", action="store_true", help="print digests instead of sending")
    sub.add_parser("daily")
    sub.add_parser("digest")
    sub.add_parser("verify-companies")
    p_disc = sub.add_parser("discover-companies")
    p_disc.add_argument("file")
    p_hook = sub.add_parser("set-webhook")
    p_hook.add_argument("url")
    sub.add_parser("delete-webhook")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.cmd == "verify-companies":
        return verify_companies()  # needs no database
    if args.cmd == "discover-companies":
        return discover_companies(args.file)
    if os.environ.get("GITHUB_ACTIONS") == "true" and config.DATABASE_URL.startswith("sqlite"):
        print("DATABASE_URL secret is missing. On GitHub Actions a SQLite file is wiped after every run, "
              "so users and jobs would vanish. Add your Supabase URL as a repository secret.")
        return 1
    try:
        from sqlalchemy.engine import make_url
        print("database:", make_url(db._normalize_url(config.DATABASE_URL)).render_as_string(hide_password=True))
    except Exception as exc:
        print(f"database URL could not be parsed: {type(exc).__name__}")
    db.init_db()

    if args.cmd == "init":
        print("database ready")
    elif args.cmd == "bot":
        from .telegram_api import Telegram
        tg = Telegram()
        bot.set_commands(tg)
        print("bot running, Ctrl+C to stop" if not args.once else "draining updates")
        print(f"handled {bot.poll(once=args.once, tg=tg)} updates")
    elif args.cmd == "collect":
        _report("collect", collect.run())
    elif args.cmd == "notify":
        _report("notify", notify.run(dry_run=args.dry_run))
    elif args.cmd == "daily":
        # Bot replies are handled by the bot workflow / webhook only, so two
        # processes never read the same Telegram updates.
        # Manual full run (all sources). Also takes today's digest slot, so the
        # Vercel morning timer won't send a second digest on the same day.
        from . import digest
        digest.claim_today()
        c = collect.run()
        n = notify.run()
        _report("daily run", {"collect": c, "notify": n})
    elif args.cmd == "digest":
        from . import digest
        _report("digest", digest.run_once_today())
    elif args.cmd == "verify-companies":
        return verify_companies()
    elif args.cmd == "set-webhook":
        from .telegram_api import Telegram
        Telegram().call("setWebhook", url=args.url, secret_token=config.TELEGRAM_WEBHOOK_SECRET,
                        allowed_updates=json.dumps(["message", "callback_query"]), drop_pending_updates="false")
        bot.set_commands(Telegram())
        print(f"webhook set to {args.url}: replies are instant now, polling is switched off")
    elif args.cmd == "delete-webhook":
        from .telegram_api import Telegram
        Telegram().call("deleteWebhook")
        print("webhook removed, polling works again")
    return 0


if __name__ == "__main__":
    sys.exit(main())
