import sqlite3
import logging

DB_PATH = "events.db"
log = logging.getLogger(__name__)


def get_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    with get_db(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                email       TEXT    NOT NULL UNIQUE,
                name        TEXT,
                token       TEXT    NOT NULL UNIQUE,
                email_sent  INTEGER NOT NULL DEFAULT 0,
                redeemed    INTEGER NOT NULL DEFAULT 0,
                redeemed_at TEXT
            )
        """)
        _ensure_columns(conn, "users", {
            "name":         "TEXT",
            "email_sent":   "INTEGER NOT NULL DEFAULT 0",
            "redeemed":     "INTEGER NOT NULL DEFAULT 0",
            "redeemed_at":  "TEXT",
        })
    log.info("DB ready at %s", db_path)


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for col, typedef in columns.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {typedef}")
            log.info("Added column %s.%s", table, col)
