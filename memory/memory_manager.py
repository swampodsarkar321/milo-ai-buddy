"""Long-term memory: save / search / update / delete with simple relevance."""
from __future__ import annotations

import time

from .database import Database


class MemoryManager:
    def __init__(self, db: Database, enabled: bool = True):
        self.db = db
        self.enabled = enabled

    # ----- CRUD -----
    def save_memory(self, value: str, key: str = "", category: str = "note") -> int:
        """Save a useful fact. Returns row id (or -1 when disabled)."""
        value = value.strip()
        if not self.enabled or not value:
            return -1
        ts = time.time()
        cur = self.db.execute(
            "INSERT INTO memories (key, value, category, created_at, updated_at)"
            " VALUES (?,?,?,?,?)",
            (key.strip(), value, category, ts, ts),
        )
        return int(cur.lastrowid)

    def search_memory(self, query: str, limit: int = 5) -> list[dict]:
        """Keyword search (LIKE-based, good enough for MVP, no embeddings)."""
        if not self.enabled:
            return []
        words = [w for w in query.lower().split() if len(w) > 2][:6]
        if not words:
            rows = self.db.query(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
            return [dict(r) for r in rows]
        conds = " OR ".join(["(LOWER(value) LIKE ? OR LOWER(key) LIKE ?)"] * len(words))
        params: list = []
        for w in words:
            like = f"%{w}%"
            params += [like, like]
        rows = self.db.query(
            f"SELECT * FROM memories WHERE {conds} ORDER BY updated_at DESC LIMIT ?",
            tuple(params + [limit]),
        )
        # Fallback: newest memories when nothing matches (helps recall).
        if not rows:
            rows = self.db.query(
                "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
            )
        return [dict(r) for r in rows]

    def all_memories(self, limit: int = 200) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def update_memory(self, mem_id: int, value: str) -> bool:
        cur = self.db.execute(
            "UPDATE memories SET value=?, updated_at=? WHERE id=?",
            (value.strip(), time.time(), mem_id),
        )
        return cur.rowcount > 0

    def delete_memory(self, mem_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id=?", (mem_id,))
        return cur.rowcount > 0

    def delete_matching(self, query: str) -> int:
        """Delete memories matching keywords. Returns deleted count."""
        words = [w for w in query.lower().split() if len(w) > 2][:6]
        if not words:
            return 0
        conds = " OR ".join(["(LOWER(value) LIKE ?)"] * len(words))
        params = tuple(f"%{w}%" for w in words)
        cur = self.db.execute(f"DELETE FROM memories WHERE {conds}", params)
        return cur.rowcount

    def clear_all(self) -> None:
        self.db.execute("DELETE FROM memories")

    # ----- helpers -----
    def format_for_prompt(self, query: str, limit: int = 5) -> str:
        hits = self.search_memory(query, limit)
        if not hits:
            return ""
        return "\n".join(f"- [{m['category']}] {m['value']}" for m in hits)

    def maybe_learn(self, user_text: str) -> str | None:
        """Auto-capture 'remember ...' / 'my favourite ... is ...' statements.

        Returns the stored value, else None.
        """
        if not self.enabled:
            return None
        t = user_text.strip()
        low = t.lower()
        value, category = "", "note"
        if low.startswith("remember that "):
            value = t[len("remember that "):]
            category = "note"
        elif low.startswith("remember "):
            value = t[len("remember "):]
            category = "preference"
        elif "my favorite" in low or "my favourite" in low:
            value, category = t, "preference"
        elif "my name is" in low:
            value, category = t, "profile"
        if value:
            self.save_memory(value, key=value[:60], category=category)
            return value
        return None
