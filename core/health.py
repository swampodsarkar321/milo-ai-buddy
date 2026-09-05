"""Screen-time health guard: track active PC use, nudge breaks.

- Active = user input within the last 5 min (Windows GetLastInputInfo,
  ctypes only — no new dependencies).
- Every 60s tick adds active seconds to today's row (health_day table).
- Continuous streak >= break_minutes -> gentle nudge (bubble). Re-nudges
  every 30 min of continued use. Going idle 5+ min ends the streak and
  counts a break.
- today_stats(db) -> (active_secs, breaks) for voice + Buddy page.
- All functions guarded; nothing raises, nothing blocks.
"""
from __future__ import annotations

import time
from datetime import datetime

IDLE_AWAY_S = 300      # 5 min without input = away (streak resets)
RENUDGE_MIN = 30       # re-nudge cadence while pushing through


def idle_seconds() -> float | None:
    """Seconds since last mouse/keyboard input (Windows). None if unknown."""
    try:
        import ctypes
        from ctypes import wintypes

        class LASTINPUTINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(lii)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
            return None
        now = ctypes.windll.kernel32.GetTickCount()
        return max(0.0, (now - lii.dwTime) / 1000.0)
    except Exception:
        return None


def today_stats(db) -> tuple[int, int]:
    """(active_secs, breaks) for today. Never raises."""
    try:
        day = datetime.now().strftime("%Y-%m-%d")
        rows = db.query("SELECT active_secs, breaks FROM health_day WHERE day=?",
                        (day,))
        if rows:
            return int(rows[0]["active_secs"] or 0), int(rows[0]["breaks"] or 0)
        return 0, 0
    except Exception:
        return 0, 0


def fmt_dur(secs: int) -> str:
    h, rem = divmod(max(0, int(secs)), 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


class ScreenTime:
    """Per-session streak tracker. tick() returns a nudge string or None."""

    def __init__(self, db, break_minutes: int = 60, enabled: bool = True):
        self.db = db
        self.break_minutes = max(15, int(break_minutes or 60))
        self.enabled = enabled
        self.streak = 0            # continuous active seconds
        self.last_nudged_at = 0    # streak value at last nudge

    def tick(self, idle_s: float | None = None, step: int = 60) -> str | None:
        """Advance one step (default 60s). Returns nudge text or None."""
        try:
            if not self.enabled:
                return None
            if idle_s is None:
                idle_s = idle_seconds()
            day = datetime.now().strftime("%Y-%m-%d")
            if idle_s is not None and idle_s >= IDLE_AWAY_S:
                # away -> streak ends; count a break if they were at it a while
                if self.streak >= 15 * 60:
                    self._add_break(day)
                self.streak = 0
                self.last_nudged_at = 0
                return None
            self.streak += step
            self._add_secs(day, step)
            need = self.break_minutes * 60
            if self.streak >= need and self.streak - self.last_nudged_at >= RENUDGE_MIN * 60:
                self.last_nudged_at = self.streak
                mins = self.streak // 60
                tips = ("Stretch a little, roll your shoulders.",
                        "Look 20 feet away for 20 seconds.",
                        "Drink some water.",
                        "Stand up for a minute.")
                import random as _r
                return (f"{mins} minutes of screen time — time for a break! "
                        f"{_r.choice(tips)}")
            return None
        except Exception:
            return None

    # ---------- storage ----------
    def _add_secs(self, day: str, step: int) -> None:
        try:
            self.db.execute(
                "INSERT INTO health_day (day, active_secs, breaks) VALUES (?,?,0)"
                " ON CONFLICT(day) DO UPDATE SET active_secs=active_secs+?",
                (day, step, step))
        except Exception:
            # older sqlite without UPSERT grammar guard: fallback
            try:
                rows = self.db.query("SELECT 1 FROM health_day WHERE day=?", (day,))
                if rows:
                    self.db.execute(
                        "UPDATE health_day SET active_secs=active_secs+? WHERE day=?",
                        (step, day))
                else:
                    self.db.execute(
                        "INSERT INTO health_day (day, active_secs, breaks) VALUES (?,?,0)",
                        (day, step))
            except Exception:
                pass

    def _add_break(self, day: str) -> None:
        try:
            self.db.execute(
                "INSERT INTO health_day (day, active_secs, breaks) VALUES (?,0,1)"
                " ON CONFLICT(day) DO UPDATE SET breaks=breaks+1",
                (day,))
        except Exception:
            try:
                rows = self.db.query("SELECT 1 FROM health_day WHERE day=?", (day,))
                if rows:
                    self.db.execute("UPDATE health_day SET breaks=breaks+1 WHERE day=?",
                                    (day,))
                else:
                    self.db.execute(
                        "INSERT INTO health_day (day, active_secs, breaks) VALUES (?,0,1)",
                        (day,))
            except Exception:
                pass
