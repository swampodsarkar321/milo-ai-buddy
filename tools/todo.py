"""Tiny to-do list (SQLite). Voice: 'todo add X' / 'my todos' / 'todo done 2'."""
from __future__ import annotations

import time


class TodoStore:
    def __init__(self, db):
        self.db = db

    def add(self, text: str) -> int:
        cur = self.db.execute(
            "INSERT INTO todos (text, done, created_at) VALUES (?,0,?)",
            (text.strip(), time.time()),
        )
        return int(cur.lastrowid)

    def open_items(self, limit: int = 10) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM todos WHERE done=0 ORDER BY id LIMIT ?", (limit,))
        return [dict(r) for r in rows]

    def done(self, num: int) -> dict:
        """Mark the Nth open item done (1-based as shown to the user)."""
        items = self.open_items(50)
        if num < 1 or num > len(items):
            return {"ok": False, "message": "Which number? Say 'my todos' first."}
        self.db.execute("UPDATE todos SET done=1 WHERE id=?", (items[num - 1]["id"],))
        return {"ok": True, "message": f"Done: {items[num - 1]['text']}. Nice!"}

    def clear_done(self) -> None:
        self.db.execute("DELETE FROM todos WHERE done=1")
