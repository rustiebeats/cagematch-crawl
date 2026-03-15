import asyncio
import logging
import sqlite3

from fetcher import Fetcher
from db import upsert_event, insert_match, insert_match_participant, is_crawled, get_known_ids
from parsers.event import parse_event_list, parse_event, parse_event_matches

logger = logging.getLogger(__name__)


async def _collect_event_ids_from_index(fetcher: Fetcher) -> set[int]:
    """Paginate the global event results index."""
    all_ids: set[int] = set()
    page_start = 0
    while True:
        soup = await fetcher.fetch({"id": "1", "view": "results", "s": str(page_start)})
        ids = parse_event_list(soup)
        if not ids:
            logger.info("No more event IDs at s=%d", page_start)
            break
        new_ids = set(ids) - all_ids
        all_ids.update(ids)
        logger.info("Event index s=%d: %d IDs (%d new)", page_start, len(ids), len(new_ids))
        page_start += 100
    return all_ids


async def crawl_events(
    fetcher: Fetcher,
    conn: sqlite3.Connection,
    resume: bool = True,
) -> None:
    logger.info("Crawling event index...")
    all_ids = await _collect_event_ids_from_index(fetcher)
    logger.info("Total event IDs discovered: %d", len(all_ids))

    crawled = get_known_ids(conn, "events") if resume else set()
    to_crawl = sorted(all_ids - crawled) if resume else sorted(all_ids)

    logger.info("Events to crawl: %d (skipping %d)", len(to_crawl), len(all_ids) - len(to_crawl))

    async def crawl_one(event_id: int) -> None:
        if resume and is_crawled(conn, "events", event_id):
            return
        try:
            soup = await fetcher.fetch({"id": "1", "nr": str(event_id)})
            data = parse_event(event_id, soup)
            upsert_event(conn, data)

            matches = parse_event_matches(event_id, soup)
            for match in matches:
                participants = match.pop("participants", [])
                match_id = insert_match(conn, match)
                for p in participants:
                    insert_match_participant(conn, {**p, "match_id": match_id})

            logger.debug("Saved event %d: %s (%d matches)", event_id, data.get("name", ""), len(matches))
        except Exception as exc:
            logger.error("Failed to crawl event %d: %s", event_id, exc)

    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i : i + batch_size]
        await asyncio.gather(*[crawl_one(eid) for eid in batch])
        logger.info("Progress: %d/%d events crawled", min(i + batch_size, len(to_crawl)), len(to_crawl))
