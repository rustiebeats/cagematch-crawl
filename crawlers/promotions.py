import asyncio
import logging
import sqlite3

from fetcher import Fetcher
from db import upsert_promotion, is_crawled, get_known_ids
from parsers.promotion import parse_promotion_list, parse_promotion

logger = logging.getLogger(__name__)


async def crawl_promotions(
    fetcher: Fetcher,
    conn: sqlite3.Connection,
    resume: bool = True,
) -> None:
    logger.info("Crawling promotion index...")
    all_ids: set[int] = set()

    # Paginate the promotions index (100 per page)
    page_start = 0
    while True:
        soup = await fetcher.fetch({"id": "8", "view": "promotions", "s": str(page_start)})
        ids = parse_promotion_list(soup)
        if not ids:
            logger.info("No more promotion IDs at s=%d, stopping index crawl", page_start)
            break
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        logger.info("Page s=%d: found %d IDs (%d new)", page_start, len(ids), len(new_ids))
        page_start += 100

    logger.info("Total promotion IDs discovered: %d", len(all_ids))

    # Crawl detail pages
    crawled = get_known_ids(conn, "promotions") if resume else set()
    to_crawl = sorted(all_ids - crawled) if resume else sorted(all_ids)

    logger.info("Promotions to crawl: %d (skipping %d already crawled)", len(to_crawl), len(all_ids) - len(to_crawl))

    async def crawl_one(promotion_id: int) -> None:
        if resume and is_crawled(conn, "promotions", promotion_id):
            return
        try:
            soup = await fetcher.fetch({"id": "8", "nr": str(promotion_id)})
            data = parse_promotion(promotion_id, soup)
            upsert_promotion(conn, data)
            logger.debug("Saved promotion %d: %s", promotion_id, data.get("name", ""))
        except Exception as exc:
            logger.error("Failed to crawl promotion %d: %s", promotion_id, exc)

    # Process in batches to avoid creating too many tasks at once
    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i : i + batch_size]
        await asyncio.gather(*[crawl_one(pid) for pid in batch])
        logger.info("Progress: %d/%d promotions crawled", min(i + batch_size, len(to_crawl)), len(to_crawl))
