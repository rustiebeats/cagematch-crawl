# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Python 3.10+ required.

## Running the crawler

```bash
# Full crawl (promotions → events → titles → wrestlers)
python main.py

# Crawl only one entity type
python main.py --only promotions
python main.py --only events
python main.py --only titles
python main.py --only wrestlers

# Re-crawl everything (ignore already-crawled records)
python main.py --no-resume

# Tune rate limiting
python main.py --delay 2.0 --concurrency 2

# Custom DB path
python main.py --db mydata.db
```

## Architecture

The crawler follows a two-layer pattern for each entity type:

**`crawlers/`** — orchestration layer. Each module (promotions, events, titles, wrestlers) handles:
1. Paginating the index page to discover all entity IDs
2. Filtering already-crawled IDs via `db.is_crawled()` / `db.get_known_ids()` (resume mode)
3. Batching async `fetcher.fetch()` calls (50 at a time) with `asyncio.gather`
4. Calling the corresponding parser and writing to DB

**`parsers/`** — HTML parsing layer. Pure functions that take a `BeautifulSoup` object and return structured dicts. No I/O.

**`fetcher.py`** — `Fetcher` async context manager wrapping `httpx.AsyncClient` with a semaphore for concurrency control, per-request delay, and exponential backoff on 429/5xx.

**`db.py`** — SQLite schema init and upsert functions. All writes use `INSERT OR REPLACE`. Resume support via `crawled_at` timestamp column — an entity is considered crawled if `crawled_at IS NOT NULL`.

### cagematch.net URL pattern

All requests go to `https://www.cagematch.net/` with query params:
- `id=8` = promotions, `id=1` = events, `id=5` = titles, `id=2` = wrestlers
- `nr=<entity_id>` = detail page
- `s=<offset>` = pagination offset (100 per page)

### DB schema relationships

`promotions` ← `events`, `titles`
`wrestlers` ← `matches` (via `match_participants`), `title_reigns`
`events` ← `matches` ← `match_participants`
`titles` ← `title_reigns`
