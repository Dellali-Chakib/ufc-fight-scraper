import argparse
import csv
import sqlite3
from pathlib import Path

import requests

from scraper.publication import locked, recover
from scraper.stat_scraper import main
from scraper.runtime import Cancelled

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Default: collect a full candidate for review"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run", action="store_true", help="Collect a candidate only (default)"
    )
    mode.add_argument("--publish", action="store_true")
    mode.add_argument("--publish-candidate", type=Path)
    mode.add_argument("--recover", action="store_true")
    parser.add_argument("--bootstrap", action="store_true")
    parser.add_argument("--pace", type=float, default=0.5)
    parser.add_argument(
        "--budget", type=int, default=18000, help="Request budget in seconds"
    )
    parser.add_argument("--directory-limit", type=int, default=1000)
    parser.add_argument("--workers", type=int, default=4, help="Profile workers and maximum in-flight requests (1-16)")
    parser.add_argument("--resume", type=Path, help="Prior candidate or responses directory; raw HTML is reparsed")
    parser.add_argument("--cache-age", type=float, default=24, help="Maximum source response age in hours (default 24)")
    parser.add_argument("--refresh-cache", action="store_true", help="Ignore prior responses, keeping the archive intact")
    parser.add_argument("--refresh-url", action="append", default=[], help="Refresh an athlete/directory path and its pagination; repeatable")
    parser.add_argument("--cancel-file", type=Path, help="Create this file to cancel safely; default is stage/cancel.request")
    args = parser.parse_args()
    if args.bootstrap and not args.publish_candidate:
        parser.error("--bootstrap requires --publish-candidate")
    if args.recover:
        with locked(Path.cwd()):
            recover(Path.cwd())
    else:
        try:
            main(
                publish_now=args.publish,
                reviewed=args.publish_candidate,
                bootstrap=args.bootstrap,
                pace=args.pace,
                budget=args.budget,
                directory_limit=args.directory_limit,
                workers=args.workers, resume=args.resume, cache_age=args.cache_age,
                refresh_cache=args.refresh_cache, refresh_urls=args.refresh_url,
                cancel_file=args.cancel_file,
            )
        except (KeyboardInterrupt, Cancelled) as exc:
            parser.exit(130, f"Collection cancelled; response archive and progress preserved: {exc}\n")
        except (
            OSError,
            ValueError,
            sqlite3.Error,
            csv.Error,
            requests.RequestException,
        ) as exc:
            parser.exit(1, f"Refresh failed: {exc}\n")
