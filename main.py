#!/usr/bin/env python3
"""
Cagematch.net crawler CLI.

Usage:
    python main.py [--db cagematch.db] [--delay 1.5] [--concurrency 3]
                   [--only promotions|events|titles|wrestlers]
                   [--resume]
"""
import argparse
import asyncio
import logging
import sys

from db import init_db
from fetcher import Fetcher
from crawlers.promotions import crawl_promotions
from crawlers.events import crawl_events
from crawlers.titles import crawl_titles
from crawlers.wrestlers import crawl_wrestlers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("main")

CRAWL_ORDER = ["promotions", "events", "titles", "wrestlers"]


async def run(args: argparse.Namespace) -> None:
    conn = init_db(args.db)
    logger.info("Database: %s", args.db)

    targets = [args.only] if args.only else CRAWL_ORDER

    async with Fetcher(delay=args.delay, concurrency=args.concurrency) as fetcher:
        for target in targets:
            logger.info("=== Starting: %s ===", target)
            if target == "promotions":
                await crawl_promotions(fetcher, conn, resume=args.resume)
            elif target == "events":
                await crawl_events(fetcher, conn, resume=args.resume)
            elif target == "titles":
                await crawl_titles(fetcher, conn, resume=args.resume)
            elif target == "wrestlers":
                await crawl_wrestlers(fetcher, conn, resume=args.resume)
            else:
                logger.error("Unknown target: %s", target)
            logger.info("=== Done: %s ===", target)

    conn.close()
    logger.info("All done.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Crawl cagematch.net into SQLite")
    parser.add_argument("--db", default="cagematch.db", help="SQLite database path")
    parser.add_argument("--delay", type=float, default=1.5, help="Delay between requests (seconds)")
    parser.add_argument("--concurrency", type=int, default=3, help="Max concurrent requests")
    parser.add_argument(
        "--only",
        choices=CRAWL_ORDER,
        default=None,
        help="Crawl only this entity type",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip already-crawled entities (default: on)",
    )
    parser.add_argument(
        "--no-resume",
        dest="resume",
        action="store_false",
        help="Re-crawl all entities even if already in DB",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
