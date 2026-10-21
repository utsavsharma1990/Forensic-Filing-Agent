"""CLI entry point for the filing watchlist monitor.

python watchlist_monitor.py --add AAPL:High --list --once [--force] [--daemon] [--remove AAPL]
"""
from __future__ import annotations

import argparse
import sys
import time

from tools.common import get_logger, load_env

log = get_logger("watchlist_monitor")


def _print_list() -> None:
    from watchlist import manager
    rows = manager.list_companies()
    if not rows:
        print("Watchlist is empty.")
        return
    for r in rows:
        flags = r["flags_fired"] if r["flags_fired"] is not None else "-"
        score = r["suspicion_score"] if r["suspicion_score"] is not None else "-"
        print(f"{r['ticker']:<8} {'active' if r['active'] else 'inactive':<9} thr={r['alert_threshold']:<8} "
              f"grade={r['last_grade'] or '-':<8} flags={flags!s:<3} score={score!s:<4} "
              f"trend={r['trend'] or '-':<5} last={r['last_analyzed'] or 'never'}  {r['company_name'] or ''}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forensic filing watchlist monitor")
    ap.add_argument("--once", action="store_true", help="run one check now and exit")
    ap.add_argument("--force", action="store_true", help="re-analyse even without a new filing")
    ap.add_argument("--add", action="append", default=[], metavar="TICKER[:THRESHOLD]")
    ap.add_argument("--remove", action="append", default=[], metavar="TICKER", help="remove a company (and its history) from the watchlist")
    ap.add_argument("--list", action="store_true", help="show the watchlist")
    ap.add_argument("--daemon", action="store_true", help="run the scheduler until Ctrl+C")
    args = ap.parse_args(argv)
    load_env()
    from watchlist import manager, scheduler
    manager.init_db()
    rc = 0
    for spec in args.add:
        ticker, _, thr = spec.partition(":")
        try:
            c = manager.add_company(ticker, thr or "Medium")
            log.info("added %s (%s) threshold=%s", c["ticker"], c["company_name"], c["alert_threshold"])
        except manager.WatchlistError as e:
            log.error("cannot add %s: %s", spec, e)
            rc = 1
    for t in args.remove:
        try:
            if manager.remove_company(t):
                log.info("removed %s (soft: history kept, inactive)", t.upper())
            else:
                log.error("%s is not on the watchlist", t)
                rc = 1
        except manager.WatchlistError as e:
            log.error("cannot remove %s: %s", t, e)
            rc = 1
    if args.once or args.force:
        for r in scheduler.run_watchlist_check(force=args.force):
            detail = r.get("error") or (f"{r.get('previous_grade')} -> {r.get('new_grade')}" if r.get("analyzed") else "")
            log.info("%s: %s %s", r.get("ticker"), r.get("status"), detail)
            if r.get("status") == "error":
                rc = 1
    if args.list:
        _print_list()
    if args.daemon:
        scheduler.start_scheduler()
        log.info("daemon running; Ctrl+C to stop")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            scheduler.stop_scheduler()
    if not (args.once or args.force or args.daemon or args.list or args.add or args.remove):
        ap.print_help()
    return rc


if __name__ == "__main__":
    sys.exit(main())
