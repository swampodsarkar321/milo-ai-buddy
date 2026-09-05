"""Reminder storage + natural-language due-date parsing + schedules."""
from __future__ import annotations

import re
import time
from datetime import datetime, timedelta

BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

WEEKDAYS_EN = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
               "friday": 4, "saturday": 5, "sunday": 6}
WEEKDAYS_BN = {"sombar": 0, "somber": 0, "mongolbar": 1, "budhbar": 2,
               "budbar": 2, "brihospotibar": 3, "brihosotibar": 3,
               "shukrobar": 4, "shukkurbar": 4, "jumma": 4,
               "shonibar": 5, "robibar": 6, "robbar": 6}


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

    # ---------- recurring schedules ----------
    def create_schedule(self, text: str, kind: str, hour: int,
                        minute: int, weekday: int = -1) -> int:
        """kind: 'daily' | 'weekly'. Next occurrence computed on tick."""
        now = datetime.now()
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if kind == "daily" and nxt <= now:
            nxt += timedelta(days=1)
        if kind == "weekly":
            days_ahead = (weekday - now.weekday()) % 7
            cand = nxt + timedelta(days=days_ahead)
            if cand <= now:
                cand += timedelta(days=7)
            nxt = cand
        cur = self.db.execute(
            "INSERT INTO reminders (text, due_at, done, created_at,"
            " repeat, repeat_day, last_fired)"
            " VALUES (?,?,0,?,?,?,?)",
            (text.strip(), nxt.timestamp(), time.time(),
             kind, weekday, ""))
        return int(cur.lastrowid)

    def schedules(self) -> list[dict]:
        try:
            rows = self.db.query(
                "SELECT * FROM reminders WHERE repeat IN ('daily','weekly')"
                " ORDER BY repeat_day, due_at")
            return [dict(r) for r in rows]
        except Exception:
            return []

    def delete_schedule(self, num: int) -> dict:
        items = self.schedules()
        if num < 1 or num > len(items):
            return {"ok": False, "message": "Which number? Say 'my schedules' first."}
        self.db.execute("DELETE FROM reminders WHERE id=?", (items[num - 1]["id"],))
        return {"ok": True, "message": "Schedule cancelled."}

    def due_schedules(self, now: datetime | None = None) -> list[dict]:
        """Schedules whose time arrived and haven't fired today. Marks them."""
        now = now or datetime.now()
        today = now.strftime("%Y-%m-%d")
        fired: list[dict] = []
        try:
            for r in self.schedules():
                try:
                    due = datetime.fromtimestamp(r["due_at"])
                except Exception:
                    continue
                if due > now or (r.get("last_fired") or "") == today:
                    continue
                if r.get("repeat") == "weekly" and r.get("repeat_day", -1) != now.weekday():
                    continue
                fired.append(dict(r))
                # advance to next occurrence + stamp today
                if r.get("repeat") == "daily":
                    nxt = due + timedelta(days=1)
                    while nxt <= now:
                        nxt += timedelta(days=1)
                else:
                    nxt = due + timedelta(days=7)
                    while nxt <= now:
                        nxt += timedelta(days=7)
                self.db.execute(
                    "UPDATE reminders SET due_at=?, last_fired=? WHERE id=?",
                    (nxt.timestamp(), today, r["id"]))
        except Exception:
            pass
        return fired


def parse_hm(text: str) -> tuple[int, int] | None:
    """'9tay', 'sokal 9', '5pm', 'bikal 5:30', '10:15' -> (hour, minute)."""
    t = text.translate(BN_DIGITS).lower()
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm|tay|tai|ta|te)?", t)
    if not m:
        return None
    h, mins, ap = int(m.group(1)), int(m.group(2) or 0), (m.group(3) or "")
    if ap == "pm" and h < 12:
        h += 12
    if ap == "am" and h == 12:
        h = 0
    # Bangla day parts nudge ambiguous hours
    if not ap or ap in ("tay", "tai", "ta", "te"):
        if re.search(r"bikal|bikel|sondha|sondhya|evening", t) and h < 12:
            h += 12
        if re.search(r"rat|night", t) and h < 12:
            h += 12
    if not (0 <= h <= 23 and 0 <= mins <= 59):
        return None
    return h, mins


def parse_schedule(text: str) -> dict | None:
    """'remind me every day at 9am about office' / 'protodin sokal 9 tay ...'.

    Returns {'kind','hour','minute','weekday','text'} or None.
    """
    t = text.translate(BN_DIGITS)
    low = t.lower()
    kind, weekday = "", -1
    if re.search(r"every day|daily|protodin|protidin|\broj\b|roj |daily", low):
        kind = "daily"
    else:
        for name, day in WEEKDAYS_EN.items():
            if re.search(rf"\b{name}\b|\bevery {name}\b", low):
                kind, weekday = "weekly", day
                break
        if not kind:
            for name, day in WEEKDAYS_BN.items():
                if name in low:
                    kind, weekday = "weekly", day
                    break
    if not kind:
        return None
    hm = parse_hm(t)
    if not hm:
        return None
    hour, minute = hm
    # strip schedule scaffolding to get the message
    msg = re.sub(r"(?i)remind me|mone koriye (dio|diyo|dao)|please|doya kore", "", t)
    msg = re.sub(r"(?i)every\s+\w+|daily|protodin|protidin", "", msg)
    for name in list(WEEKDAYS_EN) + list(WEEKDAYS_BN):
        msg = re.sub(rf"(?i)\b{name}\b", "", msg)
    msg = re.sub(r"(?i)\b\d{1,2}(?::\d{2})?\s*(am|pm|tay|tai|ta|te)?\b", "", msg)
    msg = re.sub(r"(?i)\b(sokal|bikal|bikel|sondha|sondhya|rat|morning|evening|night|at|to|about|je|jonno|er jonno)\b", "", msg)
    msg = " ".join(msg.split()).strip(" -:,")
    return {"kind": kind, "hour": hour, "minute": minute, "weekday": weekday,
            "text": msg or "Scheduled reminder"}
