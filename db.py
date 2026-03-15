import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def init_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS promotions (
            id          INTEGER PRIMARY KEY,
            name        TEXT,
            location    TEXT,
            years       TEXT,
            rating      REAL,
            votes       INTEGER,
            crawled_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS wrestlers (
            id              INTEGER PRIMARY KEY,
            name            TEXT,
            birthday        TEXT,
            birthplace      TEXT,
            gender          TEXT,
            height_cm       REAL,
            weight_kg       REAL,
            style           TEXT,
            trainers        TEXT,
            signature_moves TEXT,
            rating          REAL,
            votes           INTEGER,
            crawled_at      TEXT
        );

        CREATE TABLE IF NOT EXISTS wrestler_gimmicks (
            wrestler_id INTEGER REFERENCES wrestlers(id),
            gimmick     TEXT
        );

        CREATE TABLE IF NOT EXISTS events (
            id           INTEGER PRIMARY KEY,
            name         TEXT,
            date         TEXT,
            promotion_id INTEGER REFERENCES promotions(id),
            venue        TEXT,
            location     TEXT,
            rating       REAL,
            votes        INTEGER,
            crawled_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS titles (
            id           INTEGER PRIMARY KEY,
            name         TEXT,
            promotion_id INTEGER REFERENCES promotions(id),
            status       TEXT,
            rating       REAL,
            votes        INTEGER,
            crawled_at   TEXT
        );

        CREATE TABLE IF NOT EXISTS matches (
            id          INTEGER PRIMARY KEY,
            event_id    INTEGER REFERENCES events(id),
            match_order INTEGER,
            match_type  TEXT,
            result      TEXT,
            duration    TEXT
        );

        CREATE TABLE IF NOT EXISTS match_participants (
            match_id    INTEGER REFERENCES matches(id),
            wrestler_id INTEGER REFERENCES wrestlers(id),
            team        TEXT,
            outcome     TEXT
        );

        CREATE TABLE IF NOT EXISTS title_reigns (
            id           INTEGER PRIMARY KEY,
            title_id     INTEGER REFERENCES titles(id),
            wrestler_id  INTEGER REFERENCES wrestlers(id),
            reign_number INTEGER,
            date_won     TEXT,
            date_lost    TEXT,
            days         INTEGER,
            location     TEXT
        );
    """)
    conn.commit()
    return conn


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def is_crawled(conn: sqlite3.Connection, table: str, entity_id: int) -> bool:
    row = conn.execute(
        f"SELECT crawled_at FROM {table} WHERE id = ? AND crawled_at IS NOT NULL",
        (entity_id,),
    ).fetchone()
    return row is not None


def upsert_promotion(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO promotions
           (id, name, location, years, rating, votes, crawled_at)
           VALUES (:id, :name, :location, :years, :rating, :votes, :crawled_at)""",
        {**data, "crawled_at": now_utc()},
    )
    conn.commit()


def upsert_wrestler(conn: sqlite3.Connection, data: dict, gimmicks: list[str]) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO wrestlers
           (id, name, birthday, birthplace, gender, height_cm, weight_kg,
            style, trainers, signature_moves, rating, votes, crawled_at)
           VALUES (:id, :name, :birthday, :birthplace, :gender, :height_cm, :weight_kg,
                   :style, :trainers, :signature_moves, :rating, :votes, :crawled_at)""",
        {**data, "crawled_at": now_utc()},
    )
    conn.execute("DELETE FROM wrestler_gimmicks WHERE wrestler_id = ?", (data["id"],))
    for g in gimmicks:
        conn.execute(
            "INSERT INTO wrestler_gimmicks (wrestler_id, gimmick) VALUES (?, ?)",
            (data["id"], g),
        )
    conn.commit()


def upsert_event(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO events
           (id, name, date, promotion_id, venue, location, rating, votes, crawled_at)
           VALUES (:id, :name, :date, :promotion_id, :venue, :location, :rating, :votes, :crawled_at)""",
        {**data, "crawled_at": now_utc()},
    )
    conn.commit()


def upsert_title(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT OR REPLACE INTO titles
           (id, name, promotion_id, status, rating, votes, crawled_at)
           VALUES (:id, :name, :promotion_id, :status, :rating, :votes, :crawled_at)""",
        {**data, "crawled_at": now_utc()},
    )
    conn.commit()


def insert_match(conn: sqlite3.Connection, data: dict) -> int:
    cur = conn.execute(
        """INSERT INTO matches (event_id, match_order, match_type, result, duration)
           VALUES (:event_id, :match_order, :match_type, :result, :duration)""",
        data,
    )
    conn.commit()
    return cur.lastrowid


def insert_match_participant(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT INTO match_participants (match_id, wrestler_id, team, outcome)
           VALUES (:match_id, :wrestler_id, :team, :outcome)""",
        data,
    )
    conn.commit()


def insert_title_reign(conn: sqlite3.Connection, data: dict) -> None:
    conn.execute(
        """INSERT INTO title_reigns
           (title_id, wrestler_id, reign_number, date_won, date_lost, days, location)
           VALUES (:title_id, :wrestler_id, :reign_number, :date_won, :date_lost, :days, :location)""",
        data,
    )
    conn.commit()


def get_known_ids(conn: sqlite3.Connection, table: str) -> set[int]:
    rows = conn.execute(f"SELECT id FROM {table}").fetchall()
    return {r[0] for r in rows}
