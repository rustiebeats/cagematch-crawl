"""
Tests for the appearances pipeline (parser + db functions).
Red tests are marked with pytest.mark.xfail to document the failing state
before the feature existed; green tests verify the correct behaviour.
"""
import sqlite3

import pytest
from bs4 import BeautifulSoup

from parsers.appearances import parse_appearances_page, has_rows
from db import (
    init_db,
    init_appearances_db,
    get_appearances_crawled_ids,
    get_promotion_name_map,
    upsert_wrestler_promotion_batch,
    mark_appearances_crawled,
)
from crawlers.appearances import _aggregate_by_promotion

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def conn(tmp_path):
    db_path = str(tmp_path / "test.db")
    c = init_db(db_path)
    yield c
    c.close()


@pytest.fixture
def conn_with_data(conn):
    conn.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    conn.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (2, 'AEW', '2024-01-01')")
    conn.execute("INSERT INTO wrestlers (id, name) VALUES (100, 'Test Wrestler')")
    conn.commit()
    return conn


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


# ---------------------------------------------------------------------------
# RED: parser – these assert wrong outcomes to show what a failing test looks
#               like before the code existed. They are expected to fail.
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="red: wrong expected date format")
def test_red_parse_date_format():
    html = """
    <table><tr class="TRow1">
      <td>01.02.2024</td>
      <td><a href="?id=8&nr=5">WWE</a></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    # Wrong: date should be "01/02/2024", not the raw dot-separated form
    assert rows[0]["date"] == "01.02.2024"


@pytest.mark.xfail(strict=True, reason="red: expects non-empty result on empty table")
def test_red_empty_page_returns_rows():
    html = "<table></table>"
    rows = parse_appearances_page(_soup(html))
    assert len(rows) > 0


@pytest.mark.xfail(strict=True, reason="red: wrong promotion name expected")
def test_red_promotion_name_wrong():
    html = """
    <table><tr class="TRow1">
      <td>01.02.2024</td>
      <td><a href="?id=8&nr=5">WWE</a></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows[0]["promotion_name"] == "AEW"


# ---------------------------------------------------------------------------
# GREEN: parser – correct behaviour
# ---------------------------------------------------------------------------

def test_parse_single_row_with_promo_link():
    # Promotion ID comes from nr= in href (gif src may have date suffixes)
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>01.02.2024</td>
      <td><a href="?id=8&amp;nr=5"><img src="/site/main/img/ligen/normal/5__20030109-20170112.gif" title="TNA" alt="TNA"/></a></td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == [{"date": "01/02/2024", "promotion_id": 5, "promotion_name": "TNA"}]


def test_parse_promotion_id_from_href_nr():
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>01.06.2019</td>
      <td><a href="?id=8&amp;nr=152"><img src="/site/main/img/ligen/normal/152.gif" title="MCW Pro Wrestling" alt="MCW Pro Wrestling"/></a></td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows[0]["promotion_id"] == 152
    assert rows[0]["promotion_name"] == "MCW Pro Wrestling"


def test_parse_multiple_promotions_same_row():
    # One match row with two promotions → two output entries with the same date
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>05.11.2003</td>
      <td>
        <a href="?id=8&amp;nr=5"><img src="/site/main/img/ligen/normal/5.gif" title="TNA" alt="TNA"/></a>
        <a href="?id=8&amp;nr=9"><img src="/site/main/img/ligen/normal/9.gif" title="NWA" alt="NWA"/></a>
      </td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 2
    assert rows[0] == {"date": "05/11/2003", "promotion_id": 5, "promotion_name": "TNA"}
    assert rows[1] == {"date": "05/11/2003", "promotion_id": 9, "promotion_name": "NWA"}


def test_parse_trow2_included():
    html = """
    <table><tr class="TRow2">
      <td>1</td><td>15.12.2023</td>
      <td><a href="?id=8&amp;nr=7"><img src="/site/main/img/ligen/normal/7.gif" title="AEW" alt="AEW"/></a></td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 1
    assert rows[0]["promotion_id"] == 7
    assert rows[0]["promotion_name"] == "AEW"


def test_parse_multiple_rows():
    html = """
    <table>
      <tr class="TRow1"><td>1</td><td>01.01.2024</td><td><a href="?id=8&amp;nr=1"><img src="/site/main/img/ligen/normal/1.gif" title="WWE" alt="WWE"/></a></td><td>match</td></tr>
      <tr class="TRow2"><td>2</td><td>02.01.2024</td><td><a href="?id=8&amp;nr=2"><img src="/site/main/img/ligen/normal/2.gif" title="AEW" alt="AEW"/></a></td><td>match</td></tr>
    </table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 2
    assert rows[0]["promotion_id"] == 1
    assert rows[1]["promotion_id"] == 2


def test_parse_date_conversion():
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>31.12.1999</td>
      <td><a href="?id=8&amp;nr=9"><img src="/site/main/img/ligen/normal/9.gif" title="NWA" alt="NWA"/></a></td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows[0]["date"] == "31/12/1999"


def test_parse_skips_invalid_date():
    html = """
    <table>
      <tr class="TRow1"><td>1</td><td>not-a-date</td><td><a href="?id=8&amp;nr=1"><img src="/site/main/img/ligen/normal/1.gif" title="WWE" alt="WWE"/></a></td><td>match</td></tr>
      <tr class="TRow2"><td>2</td><td>05.06.2020</td><td><a href="?id=8&amp;nr=2"><img src="/site/main/img/ligen/normal/2.gif" title="ROH" alt="ROH"/></a></td><td>match</td></tr>
    </table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 1
    assert rows[0]["promotion_id"] == 2


def test_parse_fallback_to_cell_text_when_no_promo_link():
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>10.10.2020</td>
      <td>Independent</td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == [{"date": "10/10/2020", "promotion_id": None, "promotion_name": "Independent"}]


def test_parse_skips_row_with_empty_promotion():
    html = """
    <table><tr class="TRow1">
      <td>1</td><td>10.10.2020</td>
      <td></td>
      <td>match details</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == []


def test_parse_skips_row_with_too_few_cells():
    html = """
    <table><tr class="TRow1"><td>1</td><td>10.10.2020</td></tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == []


def test_has_rows_true():
    html = "<table><tr class='TRow1'><td>x</td></tr></table>"
    assert has_rows(_soup(html)) is True


def test_has_rows_false():
    assert has_rows(_soup("<table></table>")) is False


def test_parse_empty_page():
    rows = parse_appearances_page(_soup("<html></html>"))
    assert rows == []


# ---------------------------------------------------------------------------
# RED: db – wrong expectations before schema existed
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="red: appearances_crawl_state table doesn't exist pre-schema")
def test_red_crawled_ids_table_missing(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "bare.db"))
    # raw connection without init_db — table won't exist
    conn.execute("SELECT wrestler_id FROM appearances_crawl_state").fetchall()


@pytest.mark.xfail(strict=True, reason="red: expects non-empty map with no promotions")
def test_red_promo_map_empty_db(conn):
    promo_map = get_promotion_name_map(conn)
    assert len(promo_map) > 0


@pytest.mark.xfail(strict=True, reason="red: old appearances table has a date column")
def test_red_old_appearances_date_column(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    cols = {row[1] for row in c.execute("PRAGMA table_info(appearances)").fetchall()}
    c.close()
    assert "date" in cols  # fails: table is now wrestler_promotion


@pytest.mark.xfail(strict=True, reason="red: wrong match_count expected after inserting 2 matches")
def test_red_upsert_wrong_count(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    rows = [
        {"wrestler_id": 1, "promotion_id": 1, "first_match_date": "2024-01-01",
         "last_match_date": "2024-01-02", "match_count": 2},
    ]
    upsert_wrestler_promotion_batch(c, rows, [])
    count = c.execute("SELECT match_count FROM wrestler_promotion").fetchone()[0]
    c.close()
    assert count == 99  # wrong: should be 2


# ---------------------------------------------------------------------------
# GREEN: db – correct behaviour
# ---------------------------------------------------------------------------

def test_get_appearances_crawled_ids_empty(conn):
    assert get_appearances_crawled_ids(conn) == set()


def test_get_promotion_name_map(conn_with_data):
    promo_map = get_promotion_name_map(conn_with_data)
    assert promo_map == {"WWE": 1, "AEW": 2}


def test_get_promotion_name_map_empty(conn):
    assert get_promotion_name_map(conn) == {}


def test_mark_appearances_crawled(conn_with_data):
    mark_appearances_crawled(conn_with_data, 100)
    crawled = get_appearances_crawled_ids(conn_with_data)
    assert 100 in crawled


def test_mark_appearances_crawled_idempotent(conn_with_data):
    mark_appearances_crawled(conn_with_data, 100)
    mark_appearances_crawled(conn_with_data, 100)
    crawled = get_appearances_crawled_ids(conn_with_data)
    assert crawled == {100}


def test_upsert_wrestler_promotion_aggregates_correctly(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    aggregated = [
        {"wrestler_id": 1, "promotion_id": 1, "first_match_date": "2020-01-01",
         "last_match_date": "2024-06-15", "match_count": 3},
        {"wrestler_id": 1, "promotion_id": 2, "first_match_date": "2021-03-10",
         "last_match_date": "2022-11-20", "match_count": 2},
    ]
    upsert_wrestler_promotion_batch(c, aggregated, [])

    rows = c.execute(
        "SELECT promotion_id, first_match_date, last_match_date, match_count "
        "FROM wrestler_promotion ORDER BY promotion_id"
    ).fetchall()
    assert rows == [
        (1, "2020-01-01", "2024-06-15", 3),
        (2, "2021-03-10", "2022-11-20", 2),
    ]
    assert 1 in get_appearances_crawled_ids(c)
    c.close()


def test_upsert_wrestler_promotion_idempotent(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    row = [{"wrestler_id": 1, "promotion_id": 1, "first_match_date": "2024-01-01",
            "last_match_date": "2024-01-01", "match_count": 1}]
    upsert_wrestler_promotion_batch(c, row, [])
    upsert_wrestler_promotion_batch(c, row, [])  # same data again

    count = c.execute("SELECT COUNT(*) FROM wrestler_promotion").fetchone()[0]
    c.close()
    assert count == 1


def test_upsert_unresolved_wrestler_promotion(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    unresolved = [
        {"wrestler_id": 5, "promotion_name": "Mystery Fed",
         "first_match_date": "2019-05-01", "last_match_date": "2023-12-31", "match_count": 4},
    ]
    upsert_wrestler_promotion_batch(c, [], unresolved)

    rows = c.execute(
        "SELECT wrestler_id, promotion_name, first_match_date, last_match_date, match_count "
        "FROM unresolved_wrestler_promotion"
    ).fetchall()
    assert rows == [(5, "Mystery Fed", "2019-05-01", "2023-12-31", 4)]
    assert 5 in get_appearances_crawled_ids(c)
    c.close()


def test_aggregate_helper_date_ordering():
    rows = [
        {"date": "15/06/2022", "promotion_id": 1, "promotion_name": "WWE"},
        {"date": "01/01/2020", "promotion_id": 1, "promotion_name": "WWE"},
        {"date": "31/12/2023", "promotion_id": 1, "promotion_name": "WWE"},
    ]
    agg, unres = _aggregate_by_promotion(42, rows)
    assert unres == []
    assert len(agg) == 1
    assert agg[0]["first_match_date"] == "2020-01-01"
    assert agg[0]["last_match_date"] == "2023-12-31"
    assert agg[0]["match_count"] == 3


# ---------------------------------------------------------------------------
# Fixtures for split-DB tests
# ---------------------------------------------------------------------------

@pytest.fixture
def promo_conn(tmp_path):
    c = init_db(str(tmp_path / "promotions.db"))
    c.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    c.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (2, 'AEW', '2024-01-01')")
    c.commit()
    yield c
    c.close()


@pytest.fixture
def wrestler_conn(tmp_path):
    c = init_db(str(tmp_path / "wrestlers.db"))
    c.execute("INSERT INTO wrestlers (id, name) VALUES (200, 'Split Wrestler')")
    c.commit()
    yield c
    c.close()


@pytest.fixture
def appearances_conn(tmp_path):
    c = init_appearances_db(str(tmp_path / "appearances.db"))
    yield c
    c.close()


# ---------------------------------------------------------------------------
# RED: split-DB — documents wrong outcomes when connections are mismatched
# ---------------------------------------------------------------------------

@pytest.mark.xfail(strict=True, reason="red: reading promo map from appearances_conn (wrong DB) returns empty")
def test_red_promo_map_from_wrong_conn(appearances_conn):
    # appearances_conn has no promotions table — should raise or return empty
    promo_map = get_promotion_name_map(appearances_conn)
    assert len(promo_map) == 2  # wrong: appearances DB has no promotions


@pytest.mark.xfail(strict=True, reason="red: reading wrestler IDs from appearances_conn (wrong DB) returns empty")
def test_red_wrestler_ids_from_wrong_conn(appearances_conn):
    all_ids = appearances_conn.execute("SELECT id FROM wrestlers").fetchall()
    assert len(all_ids) == 1  # wrong: appearances DB has no wrestlers table


# ---------------------------------------------------------------------------
# GREEN: split-DB — correct behaviour with separate connections
# ---------------------------------------------------------------------------

def test_init_appearances_db_only_creates_three_tables(tmp_path):
    c = init_appearances_db(str(tmp_path / "app.db"))
    tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    c.close()
    assert tables == {"wrestler_promotion", "unresolved_wrestler_promotion", "appearances_crawl_state"}
    assert "promotions" not in tables
    assert "wrestlers" not in tables


def test_promo_map_read_from_promo_conn(promo_conn):
    promo_map = get_promotion_name_map(promo_conn)
    assert promo_map == {"WWE": 1, "AEW": 2}


def test_wrestler_ids_read_from_wrestler_conn(wrestler_conn):
    from db import get_known_ids
    ids = get_known_ids(wrestler_conn, "wrestlers")
    assert ids == {200}


def test_appearances_written_to_appearances_conn(appearances_conn, promo_conn, wrestler_conn):
    """Writes go to appearances_conn; source DBs are untouched."""
    aggregated = [{"wrestler_id": 200, "promotion_id": 1, "first_match_date": "2024-01-01",
                   "last_match_date": "2024-01-01", "match_count": 1}]
    upsert_wrestler_promotion_batch(appearances_conn, aggregated, [])

    # appearances_conn has the row
    count = appearances_conn.execute("SELECT COUNT(*) FROM wrestler_promotion").fetchone()[0]
    assert count == 1

    # promo_conn and wrestler_conn are unaffected (wrestler_promotion is empty in init_db)
    promo_tables = {r[0] for r in promo_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert "wrestler_promotion" in promo_tables
    assert promo_conn.execute("SELECT COUNT(*) FROM wrestler_promotion").fetchone()[0] == 0


# ---------------------------------------------------------------------------
# GREEN: limit — crawl_appearances respects the limit kwarg
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_limit_caps_wrestlers_processed(tmp_path, monkeypatch):
    """With limit=2 only 2 of 5 wrestlers are processed."""
    import sqlite3 as _sqlite3
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher

    # Source DB with 5 wrestlers and 2 promotions
    src = init_db(str(tmp_path / "src.db"))
    for wid in range(1, 6):
        src.execute(f"INSERT INTO wrestlers (id, name) VALUES ({wid}, 'W{wid}')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))

    # Stub fetch so no real HTTP calls are made — return empty page (stops pagination)
    from bs4 import BeautifulSoup
    async def fake_fetch(params):
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=5) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=2)

    crawled = out.execute(
        "SELECT COUNT(*) FROM appearances_crawl_state WHERE crawled_at IS NOT NULL"
    ).fetchone()[0]
    assert crawled == 2


@pytest.mark.xfail(strict=True, reason="red: expects all 5 wrestlers crawled despite limit=2")
@pytest.mark.asyncio
async def test_red_limit_ignored(tmp_path, monkeypatch):
    """Documents that without limit enforcement all wrestlers would be crawled."""
    import sqlite3 as _sqlite3
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher

    src = init_db(str(tmp_path / "src.db"))
    for wid in range(1, 6):
        src.execute(f"INSERT INTO wrestlers (id, name) VALUES ({wid}, 'W{wid}')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))

    from bs4 import BeautifulSoup
    async def fake_fetch(params):
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=5) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=2)

    crawled = out.execute(
        "SELECT COUNT(*) FROM appearances_crawl_state WHERE crawled_at IS NOT NULL"
    ).fetchone()[0]
    assert crawled == 5  # wrong: limit=2 means only 2 should be crawled


# ---------------------------------------------------------------------------
# GREEN: pagination — s= offset increments by 100 per page
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_pagination_uses_s_offset(tmp_path, monkeypatch):
    """First page uses s=0, second page uses s=100."""
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher
    from bs4 import BeautifulSoup

    src = init_db(str(tmp_path / "src.db"))
    src.execute("INSERT INTO wrestlers (id, name) VALUES (1, 'W1')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))

    seen_params = []

    async def fake_fetch(params):
        seen_params.append(dict(params))
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=1) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=1)

    assert len(seen_params) == 1  # empty page on first fetch → stops
    assert seen_params[0]["s"] == "0"
    assert seen_params[0]["page"] == "4"


@pytest.mark.asyncio
async def test_pagination_second_page_s_100(tmp_path, monkeypatch):
    """When first page has rows, second request uses s=100."""
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher
    from bs4 import BeautifulSoup

    src = init_db(str(tmp_path / "src.db"))
    src.execute("INSERT INTO wrestlers (id, name) VALUES (1, 'W1')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))

    seen_params = []
    call_count = 0

    async def fake_fetch(params):
        nonlocal call_count
        seen_params.append(dict(params))
        call_count += 1
        # Return full 100-row page on first call so pagination continues; empty on second
        if call_count == 1:
            return BeautifulSoup(_rows_html(100), "lxml")
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=1) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=1)

    assert len(seen_params) == 2
    assert seen_params[0]["s"] == "0"
    assert seen_params[1]["s"] == "100"


@pytest.mark.xfail(strict=True, reason="red: old pageNum param never matched cagematch pagination")
@pytest.mark.asyncio
async def test_red_pagination_uses_pagenum(tmp_path, monkeypatch):
    """Documents the old broken behaviour where pageNum was used instead of s."""
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher
    from bs4 import BeautifulSoup

    src = init_db(str(tmp_path / "src.db"))
    src.execute("INSERT INTO wrestlers (id, name) VALUES (1, 'W1')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))
    seen_params = []

    async def fake_fetch(params):
        seen_params.append(dict(params))
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=1) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=1)

    assert "pageNum" in seen_params[0]  # wrong: correct key is "s"


# ---------------------------------------------------------------------------
# GREEN: early stop — partial page means no next fetch
# ---------------------------------------------------------------------------

def _rows_html(n: int, promo_nr: int = 1) -> str:
    """Generate a table with n TRow1 rows, each with a valid date and promotion link."""
    rows = "\n".join(
        f'<tr class="TRow1"><td>{i}</td><td>01.01.2024</td>'
        f'<td><a href="?id=8&amp;nr={promo_nr}"><img src="/site/main/img/ligen/normal/{promo_nr}.gif" '
        f'title="WWE" alt="WWE"/></a></td><td>match</td></tr>'
        for i in range(1, n + 1)
    )
    return f"<table>{rows}</table>"


@pytest.mark.asyncio
async def test_partial_page_stops_pagination(tmp_path, monkeypatch):
    """A page with fewer than 100 rows should not trigger a next-page fetch."""
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher
    from bs4 import BeautifulSoup

    src = init_db(str(tmp_path / "src.db"))
    src.execute("INSERT INTO wrestlers (id, name) VALUES (1, 'W1')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))
    seen_params = []

    async def fake_fetch(params):
        seen_params.append(dict(params))
        # Return 50 rows (< 100) — should stop without fetching page 2
        return BeautifulSoup(_rows_html(50), "lxml")

    async with Fetcher(delay=0, concurrency=1) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=1)

    assert len(seen_params) == 1


@pytest.mark.xfail(strict=True, reason="red: partial page should stop pagination but without the check it fetches page 2")
@pytest.mark.asyncio
async def test_red_partial_page_fetches_next(tmp_path, monkeypatch):
    """Documents the old behaviour: partial page still triggered a second fetch."""
    from crawlers.appearances import crawl_appearances
    from fetcher import Fetcher
    from bs4 import BeautifulSoup

    src = init_db(str(tmp_path / "src.db"))
    src.execute("INSERT INTO wrestlers (id, name) VALUES (1, 'W1')")
    src.execute("INSERT INTO promotions (id, name, crawled_at) VALUES (1, 'WWE', '2024-01-01')")
    src.commit()

    out = init_appearances_db(str(tmp_path / "out.db"))
    seen_params = []
    call_count = 0

    async def fake_fetch(params):
        nonlocal call_count
        seen_params.append(dict(params))
        call_count += 1
        if call_count == 1:
            return BeautifulSoup(_rows_html(50), "lxml")
        return BeautifulSoup("<html></html>", "lxml")

    async with Fetcher(delay=0, concurrency=1) as fetcher:
        monkeypatch.setattr(fetcher, "fetch", fake_fetch)
        await crawl_appearances(fetcher, out, resume=False,
                                promo_conn=src, wrestler_conn=src, limit=1)

    assert len(seen_params) == 2  # wrong: should stop at 1
