"""Buddy awareness: proactive watchers that feed the speech bubble.

Credential-free (no logins needed):
- Battery: low / full / plugged / unplugged transitions (laptops).
- Time of day: lunch nudge, late-night note, fresh-morning hello (once daily).
- Downloads: new files landing in ~/Downloads.

Optional Gmail (needs GMAIL_ADDRESS + GMAIL_APP_PASSWORD in your local
.env — Google Account -> Security -> 2-Step Verification -> App passwords):
- check_mail() returns up to 2 "From — Subject" lines for UNSEEN mail.
  Polled slowly, all failures silent, nothing stored except in-RAM UIDs.

Every check_* returns display-ready strings. The GUI polls from a
background thread; results hop to the GUI thread for the bubble.
Nothing here ever raises (all guarded) and nothing blocks the UI.
"""
from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path

TEMP_EXTS = {".crdownload", ".part", ".tmp", ".download", ".opdownload"}


class Awareness:
    def __init__(self, downloads_dir: str | Path = "", db=None):
        self.downloads = Path(downloads_dir or Path.home() / "Downloads")
        try:
            self._dl_snapshot: set[str] = set(os.listdir(self.downloads))
        except Exception:
            self._dl_snapshot = set()
        self.db = db  # optional: enables mood follow-ups
        self._last_plugged: bool | None = None
        self._low_warned = False
        self._full_warned = False
        self._last_hot = 0.0            # CPU-heat cooldown timestamp
        self._daily: dict[str, str] = {}   # kind -> "YYYY-MM-DD" shown
        self._mail_seen: set[bytes] = set()

    # ================= battery =================
    def check_battery(self) -> str | None:
        try:
            import psutil
            b = psutil.sensors_battery()
        except Exception:
            return None
        if b is None:
            return None  # desktop PC, no battery
        try:
            plugged, pct = bool(b.power_plugged), float(b.percent)
            msg = None
            if self._last_plugged is None:
                self._last_plugged = plugged
            elif plugged != self._last_plugged:
                self._last_plugged = plugged
                msg = "Charger connected." if plugged else "On battery now."
                self._low_warned = False
                if plugged:
                    self._full_warned = False
            if not plugged and pct <= 20 and not self._low_warned:
                self._low_warned = True
                msg = f"Battery low ({pct:.0f}%)! Plug me in?"
            elif plugged and pct >= 99 and not self._full_warned:
                self._full_warned = True
                msg = "Fully charged!"
            elif pct > 30:
                self._low_warned = False
            return msg
        except Exception:
            return None

    # ================= system load (buddy feels the heat) =================
    def check_system_load(self, threshold: float = 85.0,
                          cooldown_s: float = 600.0) -> str | None:
        """CPU cooking? Returns a line (max once per cooldown). Never raises."""
        try:
            import psutil
            pct = float(psutil.cpu_percent(interval=0.5))
        except Exception:
            return None
        try:
            if pct >= threshold and time.time() - self._last_hot > cooldown_s:
                self._last_hot = time.time()
                return f"CPU is cooking ({pct:.0f}%) — I'm fanning myself!"
            return None
        except Exception:
            return None

    # ================= mood follow-up (human continuity) =================
    def check_mood_followup(self) -> str | None:
        """'Yesterday you seemed tired — feeling better today?' Once a day."""
        if self.db is None:
            return None
        try:
            from datetime import datetime as _dt
            today = _dt.now().strftime("%Y-%m-%d")
            rows = self.db.query(
                "SELECT value, created_at FROM memories WHERE category='mood'"
                " ORDER BY updated_at DESC LIMIT 5")
            if not rows:
                return None
            try:
                day = _dt.fromtimestamp(rows[0]["created_at"]).strftime("%Y-%m-%d")
            except Exception:
                return None
            if day >= today:
                return None  # mood is from today — too soon
            try:
                mood = str(rows[0]["value"]).split()[2].strip(".,")
            except Exception:
                mood = "down"
            done = self.db.query(
                "SELECT 1 FROM routine_nudges WHERE day=? AND cmd='mood-followup'",
                (today,))
            if done:
                return None
            self.db.execute(
                "INSERT OR IGNORE INTO routine_nudges (day, cmd, hour, created_at)"
                " VALUES (?,?,?,?)",
                (today, "mood-followup", _dt.now().hour, time.time()))
            return f"Last time you seemed {mood} — feeling better today?"
        except Exception:
            return None

    # ================= time of day =================
    def check_time(self, now: datetime | None = None) -> str | None:
        try:
            now = now or datetime.now()
            today = now.strftime("%Y-%m-%d")
            h = now.hour

            def once(key: str) -> bool:
                if self._daily.get(key) == today:
                    return False
                self._daily[key] = today
                return True

            if 5 <= h < 9 and once("morning"):
                return f"Good morning! {now.strftime('%A')} — let's have a great day."
            if 12 <= h < 14 and once("lunch"):
                return "Lunch time! Don't forget to eat."
            if h >= 23 and once("late"):
                return "It's getting late… don't forget to rest."
            return None
        except Exception:
            return None

    # ================= downloads =================
    def check_downloads(self) -> str | None:
        try:
            current = set(os.listdir(self.downloads))
        except Exception:
            return None
        try:
            fresh = [f for f in (current - self._dl_snapshot)
                     if Path(f).suffix.lower() not in TEMP_EXTS]
            self._dl_snapshot = current
            if not fresh:
                return None
            if len(fresh) == 1:
                name = fresh[0][:40]
                return f"Something new in Downloads: {name}"
            return f"{len(fresh)} new files in Downloads."
        except Exception:
            return None

    # ================= gmail (optional) =================
    @staticmethod
    def mail_configured() -> bool:
        return bool(os.getenv("GMAIL_ADDRESS") and os.getenv("GMAIL_APP_PASSWORD"))

    def check_mail(self, limit: int = 2) -> list[str]:
        """Unread subjects since last check. [] when unconfigured/offline."""
        user = (os.getenv("GMAIL_ADDRESS") or "").strip()
        pwd = (os.getenv("GMAIL_APP_PASSWORD") or "").strip()
        if not (user and pwd):
            return []
        try:
            import imaplib
            import email
            from email.header import decode_header
            from email.utils import parseaddr
        except Exception:
            return []
        try:
            box = imaplib.IMAP4_SSL("imap.gmail.com", timeout=15)
            box.login(user, pwd)
            box.select("INBOX", readonly=True)
            typ, data = box.search(None, "UNSEEN")
            if typ != "OK" or not data or not data[0]:
                try:
                    box.logout()
                except Exception:
                    pass
                return []
            ids = [i for i in data[0].split() if i not in self._mail_seen]
            if not ids:
                try:
                    box.logout()
                except Exception:
                    pass
                return []
            # only announce the newest few; remember the rest silently
            fresh, known = ids[-limit:], ids[:-limit]
            self._mail_seen.update(known)
            self._mail_seen.update(fresh)
            # cap memory (dropping old UIDs may rarely re-announce — harmless)
            while len(self._mail_seen) > 300:
                self._mail_seen.pop()
            out: list[str] = []
            for uid in fresh:
                try:
                    _t, d = box.fetch(uid, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                    raw = (d[0][1] if d and d[0] else b"").decode("utf-8", "replace")
                    msg = email.message_from_string(raw)
                    subj = self._decode(msg.get("Subject", "(no subject)"))[:60]
                    who = parseaddr(msg.get("From", ""))[0] or parseaddr(msg.get("From", ""))[1]
                    who = who[:30]
                    out.append(f"{who} — {subj}" if who else subj)
                except Exception:
                    continue
            try:
                box.logout()
            except Exception:
                pass
            return out
        except Exception:
            return []  # offline / bad password / imap blocked -> silent

    @staticmethod
    def _decode(value: str) -> str:
        try:
            from email.header import decode_header
            parts = []
            for chunk, enc in decode_header(value):
                if isinstance(chunk, bytes):
                    parts.append(chunk.decode(enc or "utf-8", "replace"))
                else:
                    parts.append(chunk)
            return "".join(parts).strip() or "(no subject)"
        except Exception:
            return str(value)[:80]
