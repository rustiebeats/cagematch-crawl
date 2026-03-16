# cagematch-crawl

Async crawler for [cagematch.net](https://www.cagematch.net) that builds a local SQLite database of wrestling promotions, events, titles, wrestlers, and match appearances — with the goal of generating a **promotion–promotion network graph** based on shared wrestler appearances.

---

## Setup

Python 3.10+ required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## Usage

```bash
# Full pipeline (recommended order)
python main.py

# Crawl one entity type
python main.py --only promotions
python main.py --only events
python main.py --only titles
python main.py --only wrestlers
python main.py --only appearances

# Re-crawl everything (ignore already-crawled records)
python main.py --no-resume

# Tune rate limiting
python main.py --delay 2.0 --concurrency 2

# Custom DB path
python main.py --db mydata.db
```

The appearances crawler requires promotions to be crawled first:

```bash
python main.py --only promotions
python main.py --only appearances
```

---

## Architecture

```
main.py                  CLI entry point
fetcher.py               Async HTTP client (httpx, semaphore, exponential backoff)
db.py                    SQLite schema init + upsert/query functions

crawlers/
  promotions.py          Paginate promotion index → fetch + store each promotion
  events.py              Paginate event index → fetch + store each event
  titles.py              Paginate title index → fetch + store each title
  wrestlers.py           Paginate wrestler index → fetch + store each wrestler
  appearances.py         For each wrestler, paginate match history → store appearances

parsers/
  promotion.py           Parse promotion list/detail pages
  event.py               Parse event detail pages
  title.py               Parse title detail pages
  wrestler.py            Parse wrestler detail pages
  appearances.py         Parse wrestler match history pages

tests/
  test_appearances.py    Red/green tests for parser + DB layer
```

Each crawler follows the same pattern:
1. Paginate the index to discover all entity IDs
2. Filter already-crawled IDs (`crawled_at IS NOT NULL`) when `--resume` is on
3. Batch async fetches (50 at a time) via `asyncio.gather`
4. Parse HTML with BeautifulSoup, write to SQLite

---

## Database Schema

```
promotions ←── events
           ←── titles ←── title_reigns ──→ wrestlers
                                                ↑
matches ──→ match_participants ────────────────┘
  ↑
events

appearances (wrestler_id, promotion_id, date)
unresolved_appearances (wrestler_id, promotion_name, date)
appearances_crawl_state (wrestler_id, crawled_at)
```

Resume support: a record is considered crawled when `crawled_at IS NOT NULL`.

---

## Tests

```bash
PYTHONPATH=. .venv/bin/python -m pytest tests/ -v
```

Tests follow a red/green pattern: `xfail` cases document wrong expectations, passing cases verify correct behaviour.

---

## Rate Limiting

Default: 1.5s delay between requests, 3 concurrent connections. Adjust with `--delay` and `--concurrency`. The fetcher retries on 429 and 5xx with exponential backoff.
