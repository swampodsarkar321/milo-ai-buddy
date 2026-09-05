"""Conversation persistence + summarisation helper."""
from __future__ import annotations

import time

from .database import Database


class ConversationMemory:
    def __init__(self, db: Database):
        self.db = db

    def log(self, role: str, text: str) -> None:
        self.db.execute(
            "INSERT INTO chat_log (role, text, created_at) VALUES (?,?,?)",
            (role, text, time.time()),
        )

    def recent(self, limit: int = 30) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM chat_log ORDER BY id DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in reversed(rows)]

    def clear(self) -> None:
        self.db.execute("DELETE FROM chat_log")

    @staticmethod
    def summarize_conversation(turns: list[tuple[str, str]], max_chars: int = 800) -> str:
        """Cheap extractive summary (no LLM call) for long-term notes."""
        lines = [f"{role}: {text}" for role, text in turns][-20:]
        text = "\n".join(lines)
        return text[:max_chars]
