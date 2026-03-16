import asyncio
import logging
import sqlite3

from db import get_known_ids, get_appearances_crawled_ids, get_promotion_name_map, \
               insert_appearances_batch, mark_appearances_crawled
from fetcher import Fetcher
from parsers.appearances import parse_appearances_page

logger = logging.getLogger(__name__)


async def crawl_appearances(
    fetcher: Fetcher,
    conn: sqlite3.Connection,
    resume: bool = True,
    *,
    promo_conn: sqlite3.Connection | None = None,
    wrestler_conn: sqlite3.Connection | None = None,
    limit: int | None = None,
) -> None:
    promo_count = (promo_conn or conn).execute(
        "SELECT COUNT(*) FROM promotions WHERE crawled_at IS NOT NULL"
    ).fetchone()[0]
    if promo_count == 0:
        logger.error("Promotions table is empty. Run promotions crawler first.")
        return

    promo_map = get_promotion_name_map(promo_conn or conn)
    logger.info("Loaded %d promotion names for mapping", len(promo_map))

    all_ids = get_known_ids(wrestler_conn or conn, "wrestlers")
    done_ids = get_appearances_crawled_ids(conn) if resume else set()
    to_crawl = sorted(all_ids - done_ids)
    if limit is not None:
        to_crawl = to_crawl[:limit]
    logger.info("Wrestlers to process: %d (skipping %d)", len(to_crawl), len(done_ids))

    async def crawl_one(wrestler_id: int) -> None:
        appearances = []
        unresolved = []
        page_num = 0
        while True:
            params = {"id": "2", "nr": str(wrestler_id), "page": "4", "pageNum": str(page_num)}
            try:
                soup = await fetcher.fetch(params)
            except Exception as exc:
                logger.error("Fetch failed wrestler=%d pageNum=%d: %s", wrestler_id, page_num, exc)
                return  # Don't mark crawled — retry next run

            rows = parse_appearances_page(soup)
            if not rows:
                break

            for row in rows:
                promo_id = promo_map.get(row["promotion_name"])
                if promo_id is not None:
                    appearances.append({"wrestler_id": wrestler_id, "promotion_id": promo_id, "date": row["date"]})
                else:
                    unresolved.append({"wrestler_id": wrestler_id, "promotion_name": row["promotion_name"], "date": row["date"]})

            logger.debug("wrestler=%d pageNum=%d rows=%d", wrestler_id, page_num, len(rows))
            page_num += 1

        if appearances or unresolved:
            insert_appearances_batch(conn, appearances, unresolved)
        else:
            mark_appearances_crawled(conn, wrestler_id)

    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i:i + batch_size]
        await asyncio.gather(*[crawl_one(wid) for wid in batch])
        logger.info("Progress: %d/%d", min(i + batch_size, len(to_crawl)), len(to_crawl))
