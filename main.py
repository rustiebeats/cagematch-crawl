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

import sqlite3

from db import init_db, init_appearances_db
from fetcher import Fetcher
from crawlers.promotions import crawl_promotions
from crawlers.events import crawl_events
from crawlers.titles import crawl_titles
from crawlers.wrestlers import crawl_wrestlers
from crawlers.appearances import crawl_appearances

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stderr,
)
logger = logging.getLogger("main")

CRAWL_ORDER = ["promotions", "events", "titles", "wrestlers", "appearances"]


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
            elif target == "appearances":
                appearances_conn = conn
                promo_conn = None
                wrestler_conn = None
                extra_conns = []
                if args.appearances_db:
                    appearances_conn = init_appearances_db(args.appearances_db)
                    extra_conns.append(appearances_conn)
                    logger.info("Appearances DB: %s", args.appearances_db)
                if args.promotions_db:
                    promo_conn = sqlite3.connect(args.promotions_db)
                    extra_conns.append(promo_conn)
                    logger.info("Promotions source DB: %s", args.promotions_db)
                if args.wrestlers_db:
                    wrestler_conn = sqlite3.connect(args.wrestlers_db)
                    extra_conns.append(wrestler_conn)
                    logger.info("Wrestlers source DB: %s", args.wrestlers_db)
                await crawl_appearances(
                    fetcher, appearances_conn, resume=args.resume,
                    promo_conn=promo_conn, wrestler_conn=wrestler_conn,
                )
                for c in extra_conns:
                    if c is not conn:
                        c.close()
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
    parser.add_argument(
        "--appearances-db",
        default=None,
        help="Path for appearances output DB (default: uses --db)",
    )
    parser.add_argument(
        "--promotions-db",
        default=None,
        help="Path to existing promotions source DB",
    )
    parser.add_argument(
        "--wrestlers-db",
        default=None,
        help="Path to existing wrestlers source DB",
    )
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
