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
    get_appearances_crawled_ids,
    get_promotion_name_map,
    insert_appearances_batch,
    mark_appearances_crawled,
)

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
    html = """
    <table><tr class="TRow1">
      <td>01.02.2024</td>
      <td><a href="?id=8&nr=5">WWE</a></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == [{"date": "01/02/2024", "promotion_name": "WWE"}]


def test_parse_trow2_included():
    html = """
    <table><tr class="TRow2">
      <td>15.12.2023</td>
      <td><a href="?id=8&nr=7">AEW</a></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 1
    assert rows[0]["promotion_name"] == "AEW"


def test_parse_multiple_rows():
    html = """
    <table>
      <tr class="TRow1"><td>01.01.2024</td><td><a href="?id=8&nr=1">WWE</a></td></tr>
      <tr class="TRow2"><td>02.01.2024</td><td><a href="?id=8&nr=2">AEW</a></td></tr>
    </table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 2


def test_parse_date_conversion():
    html = """
    <table><tr class="TRow1">
      <td>31.12.1999</td>
      <td><a href="?id=8&nr=9">NWA</a></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows[0]["date"] == "31/12/1999"


def test_parse_skips_invalid_date():
    html = """
    <table>
      <tr class="TRow1"><td>not-a-date</td><td><a href="?id=8&nr=1">WWE</a></td></tr>
      <tr class="TRow2"><td>05.06.2020</td><td><a href="?id=8&nr=2">ROH</a></td></tr>
    </table>"""
    rows = parse_appearances_page(_soup(html))
    assert len(rows) == 1
    assert rows[0]["promotion_name"] == "ROH"


def test_parse_fallback_to_cell_text_when_no_promo_link():
    html = """
    <table><tr class="TRow1">
      <td>10.10.2020</td>
      <td>Independent</td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == [{"date": "10/10/2020", "promotion_name": "Independent"}]


def test_parse_skips_row_with_empty_promotion():
    html = """
    <table><tr class="TRow1">
      <td>10.10.2020</td>
      <td></td>
    </tr></table>"""
    rows = parse_appearances_page(_soup(html))
    assert rows == []


def test_parse_skips_row_with_too_few_cells():
    html = """
    <table><tr class="TRow1"><td>10.10.2020</td></tr></table>"""
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


def test_insert_appearances_batch_resolved(conn_with_data):
    appearances = [{"wrestler_id": 100, "promotion_id": 1, "date": "01/01/2024"}]
    insert_appearances_batch(conn_with_data, appearances, [])

    rows = conn_with_data.execute("SELECT wrestler_id, promotion_id, date FROM appearances").fetchall()
    assert rows == [(100, 1, "01/01/2024")]

    crawled = get_appearances_crawled_ids(conn_with_data)
    assert 100 in crawled


def test_insert_appearances_batch_unresolved(conn_with_data):
    unresolved = [{"wrestler_id": 100, "promotion_name": "Mystery Promotion", "date": "01/01/2024"}]
    insert_appearances_batch(conn_with_data, [], unresolved)

    rows = conn_with_data.execute(
        "SELECT wrestler_id, promotion_name FROM unresolved_appearances"
    ).fetchall()
    assert rows == [(100, "Mystery Promotion")]

    crawled = get_appearances_crawled_ids(conn_with_data)
    assert 100 in crawled


def test_insert_appearances_batch_mixed(conn_with_data):
    appearances = [{"wrestler_id": 100, "promotion_id": 1, "date": "01/01/2024"}]
    unresolved = [{"wrestler_id": 100, "promotion_name": "Unknown", "date": "02/01/2024"}]
    insert_appearances_batch(conn_with_data, appearances, unresolved)

    assert conn_with_data.execute("SELECT COUNT(*) FROM appearances").fetchone()[0] == 1
    assert conn_with_data.execute("SELECT COUNT(*) FROM unresolved_appearances").fetchone()[0] == 1


def test_insert_appearances_batch_duplicate_ignored(conn_with_data):
    appearances = [{"wrestler_id": 100, "promotion_id": 1, "date": "01/01/2024"}]
    insert_appearances_batch(conn_with_data, appearances, [])
    insert_appearances_batch(conn_with_data, appearances, [])  # second call, same data

    count = conn_with_data.execute("SELECT COUNT(*) FROM appearances").fetchone()[0]
    assert count == 1
