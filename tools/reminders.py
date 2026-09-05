"""Reminder storage + natural-language due-date parsing."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta


def parse_reminder_time(text: str) -> float | None:
    """Parse 'at 8 PM', 'tomorrow at 10 AM', 'in 30 minutes' -> unix ts.

    Returns None when nothing parseable is found.
    """
    t = text.lower()
    now = datetime.now()

    m = re.search(r"in (\d+)\s*(minute|minutes|min|hour|hours|hr|second|seconds)", t)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        secs = n * (3600 if "hour" in unit or unit == "hr" else 60 if "min" in unit else 1)
        return time.time() + secs

    m = re.search(r"at (\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if m:
        h, mins, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        due = now.replace(hour=h, minute=mins, second=0, microsecond=0)
        if "tomorrow" in t and due <= now:
            due += timedelta(days=1)
        if due <= now:
            due = now + timedelta(hours=1)
        return due.timestamp()
    return None


class ReminderStore:
    def __init__(self, db):
        self.db = db

    def create(self, text: str, due_at: float) -> int:
        cur = self.db.execute(
            "INSERT INTO reminders (text, due_at, done, created_at) VALUES (?,?,0,?)",
            (text.strip(), float(due_at), time.time()),
        )
        return int(cur.lastrowid)

    def create_from_text(self, full_text: str, minutes_from_now: float = 0,
                         due_at_str: str = "") -> dict:
        """Create from LLM args. full_text like 'call Rahim'."""
        due: float | None = None
        if due_at_str:
            try:
                due = datetime.strptime(due_at_str, "%Y-%m-%d %H:%M").timestamp()
            except Exception:
                due = None
        if due is None and minutes_from_now:
            due = time.time() + float(minutes_from_now) * 60
        if due is None:
            due = parse_reminder_time(full_text) or (time.time() + 3600)
        rid = self.create(full_text, due)
        when = datetime.fromtimestamp(due).strftime("%I:%M %p, %b %d")
        return {"ok": True, "message": f"Reminder set for {when}: {full_text}.", "id": rid}

    def due(self) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM reminders WHERE done=0 AND due_at<=? ORDER BY due_at",
            (time.time(),),
        )
        return [dict(r) for r in rows]

    def upcoming(self, limit=50) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM reminders WHERE done=0 ORDER BY due_at LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def completed(self, limit=50) -> list[dict]:
        rows = self.db.query(
            "SELECT * FROM reminders WHERE done=1 ORDER BY due_at DESC LIMIT ?", (limit,)
        )
        return [dict(r) for r in rows]

    def mark_done(self, rid: int) -> None:
        self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))

    def delete(self, rid: int) -> bool:
        cur = self.db.execute("DELETE FROM reminders WHERE id=?", (rid,))
        return cur.rowcount > 0
