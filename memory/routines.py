"""Routine learning: notice repeated commands, nudge at the right hour.

- Every tool-using command is logged with its timestamp (habit_log).
- A routine = same command run 2+ times in the same hour-of-day window
  within the last 14 days (conversation chit-chat is ignored — only
  real actions count).
- should_suggest(now): returns one suggestion at most — due within
  ±20 min, not already nudged today, not run in the last 60 min.
- Nudges are recorded (routine_nudges) so each routine fires once a day.
- Fully local SQLite. Disabled when the user turns memory off.

Example: "open youtube" at 19:05, 19:20, 18:50 over several days
-> at ~19:00 buddy bubbles: "Usually 'open youtube' around now — just say it!"
"""
from __future__ import annotations

import time
from datetime import datetime

WINDOW_MIN = 20      # suggest ±20 min around the routine hour
MIN_COUNT = 2        # repeats needed before it counts as a habit
LOOKBACK_DAYS = 14
RECENT_GUARD_MIN = 60  # don't nudge if just did it


class RoutineTracker:
    def __init__(self, db, enabled: bool = True):
        self.db = db
        self.enabled = enabled

    # ---------- logging ----------
    @staticmethod
    def normalize(text: str) -> str:
        t = " ".join((text or "").lower().strip().split())
        return t[:80]

    def log(self, text: str, tool: str | None) -> None:
        """Log action commands only (tool is not None). Never raises."""
        try:
            if not self.enabled or not tool:
                return
            norm = self.normalize(text)
            if not norm:
                return
            self.db.execute(
                "INSERT INTO habit_log (text, tool, created_at) VALUES (?,?,?)",
                (norm, tool, time.time()))
        except Exception:
            pass

    # ---------- mining ----------
    def routines(self, now: float | None = None) -> list[dict]:
        """All learned routines: [{'text','hour','count'}]. Never raises."""
        try:
            if not self.enabled:
                return []
            now = now or time.time()
            since = now - LOOKBACK_DAYS * 86400
            rows = self.db.query(
                "SELECT text, created_at FROM habit_log WHERE created_at>=?",
                (since,))
            from collections import defaultdict
            buckets: dict[tuple[str, int], int] = defaultdict(int)
            for r in rows:
                try:
                    hour = datetime.fromtimestamp(r["created_at"]).hour
                except Exception:
                    continue
                buckets[(r["text"], hour)] += 1
            out = [{"text": t, "hour": h, "count": c}
                   for (t, h), c in buckets.items() if c >= MIN_COUNT]
            return sorted(out, key=lambda d: (-d["count"], d["hour"]))
        except Exception:
            return []

    # ---------- suggesting ----------
    def should_suggest(self, now: datetime | None = None) -> dict | None:
        """One due suggestion or None. Records the nudge. Never raises."""
        try:
            if not self.enabled:
                return None
            now = now or datetime.now()
            day = now.strftime("%Y-%m-%d")
            cur_min = now.hour * 60 + now.minute
            # prune old nudge records (keep a week)
            try:
                self.db.execute(
                    "DELETE FROM routine_nudges WHERE created_at<?",
                    (time.time() - 7 * 86400,))
            except Exception:
                pass
            for r in self.routines():
                target = r["hour"] * 60
                if abs(cur_min - target) > WINDOW_MIN:
                    continue
                done = self.db.query(
                    "SELECT 1 FROM routine_nudges WHERE day=? AND cmd=? AND hour=?",
                    (day, r["text"], r["hour"]))
                if done:
                    continue
                recent = self.db.query(
                    "SELECT 1 FROM habit_log WHERE text=? AND created_at>=? LIMIT 1",
                    (r["text"], time.time() - RECENT_GUARD_MIN * 60))
                if recent:
                    continue
                self.db.execute(
                    "INSERT OR IGNORE INTO routine_nudges (day, cmd, hour, created_at)"
                    " VALUES (?,?,?,?)",
                    (day, r["text"], r["hour"], time.time()))
                short = r["text"] if len(r["text"]) <= 48 else r["text"][:47] + "…"
                return {"text": r["text"],
                        "say": f"Usually '{short}' around now — just say it!"}
            return None
        except Exception:
            return None
