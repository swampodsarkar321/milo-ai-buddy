"""SQLite storage: memories, reminders, conversation logs."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'note',
    created_at REAL,
    updated_at REAL
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    due_at REAL NOT NULL,
    done INTEGER DEFAULT 0,
    created_at REAL,
    repeat TEXT DEFAULT '',
    repeat_day INTEGER DEFAULT -1,
    last_fired TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS chat_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    done INTEGER DEFAULT 0,
    created_at REAL
);
CREATE TABLE IF NOT EXISTS habit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    tool TEXT DEFAULT '',
    created_at REAL
);
CREATE TABLE IF NOT EXISTS routine_nudges (
    day TEXT NOT NULL,
    cmd TEXT NOT NULL,
    hour INTEGER NOT NULL,
    created_at REAL,
    PRIMARY KEY (day, cmd, hour)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Additive migrations for existing user databases. Never raises."""
        try:
            cols = {r[1] for r in
                    self._conn.execute("PRAGMA table_info(reminders)").fetchall()}
            for col, ddl in (("repeat", "TEXT DEFAULT ''"),
                             ("repeat_day", "INTEGER DEFAULT -1"),
                             ("last_fired", "TEXT DEFAULT ''")):
                if col not in cols:
                    self._conn.execute(f"ALTER TABLE reminders ADD COLUMN {col} {ddl}")
            with self._conn:
                pass
        except Exception:
            pass

    # generic helper
    def execute(self, sql: str, params: tuple = ()):
        with self._conn:
            cur = self._conn.execute(sql, params)
        return cur

    def query(self, sql: str, params: tuple = ()):
        return self._conn.execute(sql, params).fetchall()


def now_ts() -> float:
    return time.time()
