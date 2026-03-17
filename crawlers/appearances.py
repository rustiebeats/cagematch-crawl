import asyncio
import logging
import sqlite3
from collections import defaultdict
from datetime import datetime

from db import get_known_ids, get_appearances_crawled_ids, \
               upsert_wrestler_promotion_batch, mark_appearances_crawled
from fetcher import Fetcher
from parsers.appearances import parse_appearances_page
from parsers.event import parse_event_promotions

logger = logging.getLogger(__name__)


def _aggregate_by_promotion(wrestler_id: int, rows: list[dict]):
    """
    rows: list of {promotion_id, promotion_name, date: "DD/MM/YYYY"}
    Returns (aggregated, unresolved) where each entry has
    first_match_date/last_match_date (YYYY-MM-DD) and match_count.
    """
    resolved = defaultdict(list)    # promotion_id → [(datetime, promotion_name), ...]
    unresolved = defaultdict(list)  # promotion_name → [datetime, ...]

    for r in rows:
        d = datetime.strptime(r["date"], "%d/%m/%Y")
        if r["promotion_id"] is not None:
            resolved[r["promotion_id"]].append((d, r["promotion_name"]))
        else:
            unresolved[r["promotion_name"]].append(d)

    agg = []
    for pid, entries in resolved.items():
        dates = [e[0] for e in entries]
        name = entries[0][1]
        agg.append({
            "wrestler_id": wrestler_id,
            "promotion_id": pid,
            "first_match_date": min(dates).strftime("%Y-%m-%d"),
            "last_match_date": max(dates).strftime("%Y-%m-%d"),
            "match_count": len(dates),
        })

    unres = []
    for pname, dates in unresolved.items():
        unres.append({
            "wrestler_id": wrestler_id,
            "promotion_name": pname,
            "first_match_date": min(dates).strftime("%Y-%m-%d"),
            "last_match_date": max(dates).strftime("%Y-%m-%d"),
            "match_count": len(dates),
        })

    return agg, unres


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

    all_ids = get_known_ids(wrestler_conn or conn, "wrestlers")
    done_ids = get_appearances_crawled_ids(conn) if resume else set()
    to_crawl = sorted(all_ids - done_ids)
    if limit is not None:
        to_crawl = to_crawl[:limit]
    logger.info("Wrestlers to process: %d (skipping %d)", len(to_crawl), len(done_ids))

    async def crawl_one(wrestler_id: int) -> None:
        all_rows = []
        page_num = 0
        while True:
            params = {"id": "2", "nr": str(wrestler_id), "page": "4", "s": str(page_num * 100)}
            try:
                soup = await fetcher.fetch(params)
            except Exception as exc:
                logger.error("Fetch failed wrestler=%d pageNum=%d: %s", wrestler_id, page_num, exc)
                return  # Don't mark crawled — retry next run

            rows = parse_appearances_page(soup)
            if not rows:
                break

            all_rows.extend(rows)
            logger.debug("wrestler=%d pageNum=%d rows=%d", wrestler_id, page_num, len(rows))
            if len(rows) < 100:
                break
            page_num += 1

        # Resolve rows that require an event-page lookup for the promotion
        event_nrs = list(dict.fromkeys(
            r["event_nr"] for r in all_rows if r.get("event_nr") is not None
        ))
        if event_nrs:
            event_promo_map: dict[int, list[dict]] = {}

            async def fetch_event_promotions(event_nr: int) -> None:
                try:
                    esoup = await fetcher.fetch({"id": "1", "nr": str(event_nr)})
                    event_promo_map[event_nr] = parse_event_promotions(esoup)
                except Exception as exc:
                    logger.error("Fetch failed event=%d: %s", event_nr, exc)
                    event_promo_map[event_nr] = []

            await asyncio.gather(*[fetch_event_promotions(enr) for enr in event_nrs])

            expanded = []
            for r in all_rows:
                enr = r.get("event_nr")
                if enr is None:
                    expanded.append(r)
                else:
                    for p in event_promo_map.get(enr, []):
                        expanded.append({
                            "date": r["date"],
                            "promotion_id": p["promotion_id"],
                            "promotion_name": p["promotion_name"],
                        })
            all_rows = expanded

        if all_rows:
            agg, unres = _aggregate_by_promotion(wrestler_id, all_rows)
            upsert_wrestler_promotion_batch(conn, agg, unres)
        else:
            mark_appearances_crawled(conn, wrestler_id)

    batch_size = 50
    for i in range(0, len(to_crawl), batch_size):
        batch = to_crawl[i:i + batch_size]
        await asyncio.gather(*[crawl_one(wid) for wid in batch])
        logger.info("Progress: %d/%d", min(i + batch_size, len(to_crawl)), len(to_crawl))
