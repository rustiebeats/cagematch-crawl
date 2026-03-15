import asyncio
import logging
import sqlite3

from fetcher import Fetcher
from db import upsert_wrestler, is_crawled, get_known_ids
from parsers.wrestler import parse_wrestler_list, parse_wrestler

logger = logging.getLogger(__name__)


async def crawl_wrestlers(
    fetcher: Fetcher,
    conn: sqlite3.Connection,
    resume: bool = True,
) -> None:
    logger.info("Crawling wrestler index...")
    all_ids: set[int] = set()

    page_start = 0
    while True:
        soup = await fetcher.fetch({"id": "2", "view": "workers", "s": str(page_start)})
        ids = parse_wrestler_list(soup)
        if not ids:
            logger.info("No more wrestler IDs at s=%d, stopping index crawl", page_start)
            break
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        logger.info("Wrestler index s=%d: %d IDs (%d new)", page_start, len(ids), len(new_ids))
        page_start += 100

    logger.info("Total wrestler IDs discovered: %d", len(all_ids))

    crawled = get_known_ids(conn, "wrestlers") if resume else set()
    to_crawl = sorted(all_ids - crawled) if resume else sorted(all_ids)

    logger.info("Wrestlers to crawl: %d (skipping %d)", len(to_crawl), len(all_ids) - len(to_crawl))

    async def crawl_one(wrestler_id: int) -> None:
        if resume and is_crawled(conn, "wrestlers", wrestler_id):
            return
        try:
            soup = await fetcher.fetch({"id": "2", "nr": str(wrestler_id)})
            data, gimmicks = parse_wrestler(wrestler_id, soup)
            upsert_wrestler(conn, data, gimmicks)
            logger.debug("Saved wrestler %d: %s", wrestler_id, data.get("name", ""))
        except Exception as exc:
            logger.error("Failed to crawl wrestler %d: %s", wrestler_id, exc)

    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i : i + batch_size]
        await asyncio.gather(*[crawl_one(wid) for wid in batch])
        logger.info(
            "Progress: %d/%d wrestlers crawled",
            min(i + batch_size, len(to_crawl)),
            len(to_crawl),
        )
