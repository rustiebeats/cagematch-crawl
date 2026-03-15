import asyncio
import logging
import sqlite3

from fetcher import Fetcher
from db import upsert_title, insert_title_reign, is_crawled, get_known_ids
from parsers.title import parse_title_list, parse_title, parse_title_reigns

logger = logging.getLogger(__name__)


async def crawl_titles(
    fetcher: Fetcher,
    conn: sqlite3.Connection,
    resume: bool = True,
) -> None:
    logger.info("Crawling title index...")
    all_ids: set[int] = set()

    page_start = 0
    while True:
        soup = await fetcher.fetch({"id": "5", "view": "titlehistory", "s": str(page_start)})
        ids = parse_title_list(soup)
        if not ids:
            logger.info("No more title IDs at s=%d", page_start)
            break
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        logger.info("Title index s=%d: %d IDs (%d new)", page_start, len(ids), len(new_ids))
        page_start += 100

    logger.info("Total title IDs discovered: %d", len(all_ids))

    crawled = get_known_ids(conn, "titles") if resume else set()
    to_crawl = sorted(all_ids - crawled) if resume else sorted(all_ids)

    logger.info("Titles to crawl: %d (skipping %d)", len(to_crawl), len(all_ids) - len(to_crawl))

    async def crawl_one(title_id: int) -> None:
        if resume and is_crawled(conn, "titles", title_id):
            return
        try:
            soup = await fetcher.fetch({"id": "5", "nr": str(title_id)})
            data = parse_title(title_id, soup)
            upsert_title(conn, data)

            reigns = parse_title_reigns(title_id, soup)
            for reign in reigns:
                insert_title_reign(conn, reign)

            logger.debug("Saved title %d: %s (%d reigns)", title_id, data.get("name", ""), len(reigns))
        except Exception as exc:
            logger.error("Failed to crawl title %d: %s", title_id, exc)

    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i : i + batch_size]
        await asyncio.gather(*[crawl_one(tid) for tid in batch])
        logger.info("Progress: %d/%d titles crawled", min(i + batch_size, len(to_crawl)), len(to_crawl))
