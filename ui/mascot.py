"""Desktop buddy — a Shimeji/Desktop-Mate style companion that roams the PC.

- Frameless, always-on-top, transparent overlay (no taskbar entry, never
  steals focus). Click-through everywhere except its own body (ellipse mask).
- 100% painted in code (QPainter) — zero image assets to ship.
- Walks along the bottom of the screen, hops, blinks, turns at edges.
- Draggable anywhere; click it and NOVA reacts.
- Moods: IDLE / LISTENING / THINKING / SPEAKING / ERROR / HAPPY /
  SURPRISED / SLEEPY / CRY / ANGRY / LAUGH / MUNCH / HUNGRY.
- Hunger engine: gets hungry about every ~18 min — click to feed it.
- Speech bubble: shows status text ("Listening…", "Hungry!…") above its head.

No new dependencies. Toggle: Settings -> Desktop buddy.
"""
from __future__ import annotations

import math
import random

from PySide6.QtCore import Qt, QTimer, Signal, QPoint, QRect
from PySide6.QtGui import (QColor, QPainter, QRadialGradient, QPen, QBrush,
                           QRegion, QFont)
from PySide6.QtWidgets import QApplication, QLabel, QWidget

SIZES = {"small": 96, "medium": 124, "large": 156}

MOOD_COLORS = {
    "IDLE": "#7C5CFF",
    "LISTENING": "#34D399",
    "THINKING": "#FBBF24",
    "SPEAKING": "#38BDF8",
    "ERROR": "#F87171",
    "HAPPY": "#EC4899",
    "SURPRISED": "#8FD0FF",
    "SLEEPY": "#565E96",
    "CRY": "#60A5FA",
    "ANGRY": "#EF4444",
    "LAUGH": "#F472B6",
    "MUNCH": "#FBBF24",
    "HUNGRY": "#C9A227",
    "HOT": "#FF9F43",
    "CARE": "#F5B85C",
}

SLEEP_AFTER_S = 60.0   # doze off after a minute of nothing happening
HUNGRY_AT = 70.0       # hunger 0..100; belly rumbles past this
HUNGER_PER_TICK = 0.08  # _think runs every 1.2s -> hungry in ~18 min
POKE_ANGRY_N = 3       # rapid pokes within 2s -> grumpy
LAUGH_EVERY = 5        # every Nth poke is a giggle fit


class MascotBubble(QLabel):
    """Floating status text above the buddy (click-through, auto-hides).

    Tint = mood colour left-border + tinted text. Style modes:
    auto (mood tint) | white (neutral) | accent (product colour).
    """

    def __init__(self):
        super().__init__(
            None,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)  # never blocks clicks
        self._tint = "#7C5CFF"
        self._mode = "auto"
        self.hide()

    def configure(self, mode: str, accent: str = "#7C5CFF"):
        self._mode = mode if mode in ("auto", "white", "accent") else "auto"
        self._accent = accent
        self._restyle(self._tint)

    @staticmethod
    def _hex_to_rgb(value: str) -> tuple[int, int, int]:
        try:
            v = value.strip().lstrip("#")
            if len(v) == 3:
                v = "".join(c * 2 for c in v)
            return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
        except Exception:
            return 124, 92, 255

    @staticmethod
    def _mix(a: str, b: str, amt: float) -> str:
        """Solid mix of two hex colours (no alpha -> same on every PC).

        amt=0 -> a, amt=1 -> b. Used so the bubble never depends on
        compositor transparency (which washes out white on some GPUs).
        """
        def _h(v: str) -> tuple[int, int, int]:
            v = v.strip().lstrip("#")
            if len(v) == 3:
                v = "".join(c * 2 for c in v)
            try:
                return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
            except Exception:
                return 11, 17, 41
        ar, ag, ab = _h(a)
        br, bg_, bb = _h(b)
        t = max(0.0, min(1.0, amt))
        r = int(ar + (br - ar) * t)
        g = int(ag + (bg_ - ag) * t)
        bl = int(ab + (bb - ab) * t)
        return f"#{r:02X}{g:02X}{bl:02X}"

    def _restyle(self, tint: str):
        self._tint = tint
        if self._mode == "white":
            bg, border, color = "#0B1129", "#8B93C9", "#FFFFFF"
        elif self._mode == "accent":
            acc = getattr(self, "_accent", "#7C5CFF")
            bg, border, color = self._mix(acc, "#0B1129", 0.78), acc, "#FFFFFF"
        else:  # auto: dark mood-tinted SOLID pill — readable on any wallpaper
            bg = self._mix(tint, "#0B1129", 0.74)
            border, color = tint, "#FFFFFF"
        self.setStyleSheet(
            f"background:{bg}; color:{color};"
            f"border:2px solid {border};"
            "border-radius:14px; padding:10px 18px;"
            "font-size:14px; font-weight:800;")

    def show_text(self, text: str, tint: str = "#7C5CFF"):
        self._restyle(tint)
        self.setText(text)
        self.adjustSize()
        # re-assert transparency every show (some drivers drop it)
        try:
            self.setAttribute(Qt.WA_TranslucentBackground, True)
        except Exception:
            pass
        self.show()
        self.raise_()


class Mascot(QWidget):
    clicked = Signal()  # short click (not a drag)
    talk_requested = Signal()      # menu: talk right now
    command_requested = Signal(str)  # menu: run a voice command
    file_dropped = Signal(str)     # a text file was dropped on the buddy
    show_requested = Signal()      # menu: open the main window
    quit_requested = Signal()      # menu: quit the whole app

    def __init__(self, accent="#7C5CFF", size_name="medium", parent=None):
        super().__init__(
            parent,
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)  # never steal focus

        self.accent = accent
        self.app_mood = "IDLE"   # driven by the assistant state
        self.mood = "IDLE"       # may be temporarily overridden (HAPPY)
        self._mood_until = 0.0
        import time as _t
        self._last_active = _t.time()
        # hunger engine (session-only, starts peckish)
        self.hunger = 15.0
        self._was_hungry = False
        # poke tracking (grumpiness + giggles)
        self._poke_times: list[float] = []
        self._poke_count = 0
        self._shake = 0
        # showmanship: wave frames, spin-trick degrees remaining
        self._wave = 0
        self._spin = 0.0

        self.px = float(SIZES.get(size_name, 124))
        self.setFixedSize(int(self.px), int(self.px))
        self._apply_mask()

        # locomotion
        self.dir = 1
        self.speed = 2.2
        self.phase = 0.0
        self.paused = False
        self._pause_ticks = 0
        self.jump_v = 0.0
        self.jump_y = 0.0
        self.blink = 0          # frames remaining with eyes shut
        self._tilt = 0.0        # lean while dragged

        # dragging
        self._dragging = False
        self._drag_off = QPoint()
        self._press_pos = QPoint()
        self._moved = False
        self._right_down = False
        self.setAcceptDrops(True)  # drop a .txt file -> buddy reads it aloud

        # speech bubble ("Listening…" etc. above its head)
        self.bubble = MascotBubble()
        self._bubble_timer = QTimer(self)
        self._bubble_timer.setSingleShot(True)
        self._bubble_timer.timeout.connect(self.bubble.hide)

        self._tick = QTimer(self)
        self._tick.timeout.connect(self._step)
        self._tick.start(50)          # 20 fps animation
        self._brain = QTimer(self)
        self._brain.timeout.connect(self._think)
        self._brain.start(1200)       # behaviour decisions

        self._place_initial()

    # ================= public =================

    def set_app_mood(self, mood: str) -> None:
        self.app_mood = mood if mood in MOOD_COLORS else "IDLE"
        import time
        if mood != "IDLE":
            self._last_active = time.time()
        # SLEEPY/HUNGRY are sticky until real activity arrives (this call IS one)
        if time.time() >= self._mood_until or self.mood in ("SLEEPY", "HUNGRY"):
            self.mood = self.app_mood
        self.update()

    def _sticky(self) -> bool:
        return self.mood in ("SLEEPY", "HUNGRY")

    def surprise(self) -> None:
        """Wide-eyed gasp (wake-word heard). Auto-releases to app mood."""
        import time
        self._last_active = time.time()
        self.mood = "SURPRISED"
        self._mood_until = time.time() + 1.6
        self.jump_v = -5.0
        self.say("Yes? Listening…")
        self.update()

    def poke(self) -> None:
        """Happy bounce (called on click, before MainWindow speaks)."""
        import time
        self._last_active = time.time()
        self.mood = "HAPPY"
        self._mood_until = time.time() + 2.2
        self.jump_v = -9.0
        self._wave = 16
        self.say("Listening…")
        self.update()

    def cheer(self) -> None:
        """Happy bounce WITHOUT bubble (thanks-reaction; reply bubble stays)."""
        import time
        self._last_active = time.time()
        self.mood = "HAPPY"
        self._mood_until = time.time() + 2.0
        self.jump_v = -7.0
        self.update()

    def care(self) -> None:
        """Warm sympathetic lean (user tired/sad — reply bubble stays)."""
        import time
        self._last_active = time.time()
        self.mood = "CARE"
        self._mood_until = time.time() + 3.0
        self._tilt = 0.12
        self.update()

    def set_accent(self, accent: str) -> None:
        self.accent = accent or self.accent
        try:
            self.bubble.configure(getattr(self, "_bubble_mode", "auto"), self.accent)
        except Exception:
            pass
        self.update()

    def set_bubble_style(self, mode: str, accent: str = "") -> None:
        self._bubble_mode = mode if mode in ("auto", "white", "accent") else "auto"
        try:
            self.bubble.configure(self._bubble_mode, accent or self.accent)
        except Exception:
            pass

    def set_size_name(self, name: str) -> None:
        self.px = float(SIZES.get(name, 124))
        self.setFixedSize(int(self.px), int(self.px))
        self._apply_mask()
        self._clamp_to_screen()
        self.update()

    # ================= internals =================

    def _apply_mask(self):
        # ellipse body: corners stay click-through to windows behind
        r = self.rect().adjusted(6, 4, -6, -4)
        self.setMask(QRegion(r, QRegion.Ellipse))

    def _screen_rect(self) -> QRect:
        scr = QApplication.primaryScreen()
        if scr:
            return scr.availableGeometry()
        return QRect(0, 0, 1280, 720)

    def _place_initial(self):
        g = self._screen_rect()
        self.move(g.right() - self.width() - 60, g.bottom() - self.height() - 8)

    def _clamp_to_screen(self):
        g = self._screen_rect()
        x = min(max(self.x(), g.left()), g.right() - self.width())
        y = min(max(self.y(), g.top()), g.bottom() - self.height())
        self.move(int(x), int(y))

    def _step(self):
        import time
        if (not self._sticky() and self.mood != self.app_mood
                and time.time() >= self._mood_until):
            if self.mood == "CARE" and not self._dragging:
                self._tilt = 0.0  # straighten up after sympathising
            self.mood = self.app_mood
        if self._shake > 0:  # angry tremble
            self._shake -= 1
            self._tilt = 0.14 * (1 if self._shake % 2 == 0 else -1)
            if self._shake == 0 and not self._dragging:
                self._tilt = 0.0
        if self._wave > 0:
            self._wave -= 1
        if self._spin > 0:  # 360 spin trick
            self._spin = max(0.0, self._spin - 30.0)
        self.phase += 0.35
        if self.blink > 0:
            self.blink -= 1
        # jump physics
        if self.jump_y < 0 or self.jump_v != 0:
            self.jump_y += self.jump_v
            self.jump_v += 0.9
            if self.jump_y >= 0:
                self.jump_y = 0
                self.jump_v = 0
        # walk (frozen while dragged — you hold it mid-air)
        if not self._dragging and not self.paused:
            g = self._screen_rect()
            nx = self.x() + self.dir * self.speed
            if nx <= g.left() + 4:
                nx, self.dir = g.left() + 4, 1
            elif nx + self.width() >= g.right() - 4:
                nx, self.dir = g.right() - 4 - self.width(), -1
            hop = abs(math.sin(self.phase)) * -7 if self.speed > 0 else 0
            if self.mood == "SPEAKING":
                # extra bounce while talking so the mouth sync reads clearly
                hop += abs(math.sin(self.phase * 1.6)) * -5
            if self.mood == "HUNGRY":
                hop *= 0.3  # too hungry to hop properly
            self.move(int(nx), int(g.bottom() - self.height() - 8 + hop + self.jump_y))
        self._position_bubble()
        self.update()

    def _base_y(self) -> int:
        return self._screen_rect().bottom() - self.height() - 8

    def _snap_y(self):
        if not self._dragging:
            self.move(self.x(), self._base_y())

    def _think(self):
        import time
        now = time.time()
        # ---- hunger engine ----
        self.hunger = min(100.0, self.hunger + HUNGER_PER_TICK)
        if (self.hunger >= HUNGRY_AT and not self._was_hungry
                and now >= self._mood_until):
            self._was_hungry = True
            self.mood = "HUNGRY"
            self.say("I'm hungry… click to feed me!")
        # ---- sleep engine (hunger wins over sleep) ----
        # doze off when ignored for a while; any activity wakes instantly
        # (set_app_mood/poke/surprise refresh _last_active)
        if (self.app_mood == "IDLE" and self.mood != "HUNGRY"
                and now - self._last_active > SLEEP_AFTER_S
                and now >= self._mood_until):
            self.mood = "SLEEPY"
        roll = random.random()
        if roll < 0.18:
            self.dir *= -1                    # turn around
        elif roll < 0.35:
            self.paused = True                # take a breather
            self._pause_ticks = random.randint(2, 6)
        elif roll < 0.45:
            self.jump_v = -7.0                # little hop
        elif roll < 0.52:
            self.blink = 3
        if self.paused:
            self._pause_ticks -= 1
            if self._pause_ticks <= 0:
                self.paused = False
        # occasional show-off trick when idle and content
        if (roll > 0.97 and self.app_mood == "IDLE" and not self._sticky()
                and self.hunger < HUNGRY_AT and self._spin == 0):
            self._spin = 360.0
            self.jump_v = -6.0

    def _look_offset(self) -> tuple[float, float]:
        """Pupil shift toward the mouse cursor (buddy watches you).

        Returns (dx, dy) in paint units. Falls back to walk direction.
        """
        try:
            from PySide6.QtGui import QCursor
            cur = QCursor.pos()
            cx = self.x() + self.width() / 2
            cy = self.y() + self.height() / 2
            dx, dy = cur.x() - cx, cur.y() - cy
            dist = math.hypot(dx, dy)
            if dist < 1:
                return 0.0, 0.0
            reach = min(3.4, dist / 110.0)
            return dx / dist * reach, dy / dist * reach
        except Exception:
            return 0.0, 0.0

    def do_spin_trick(self, shout: bool = True) -> None:
        if self._spin == 0:
            self._spin = 360.0
            self.jump_v = -7.0
            if shout:
                self.say("Wheee!")
            self.update()

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            import time
            self._last_active = time.time()
            self.do_spin_trick()

    # ---------- mouse: drag to move, click to poke ----------
    def mousePressEvent(self, e):
        if e.button() == Qt.RightButton:
            self._right_down = True
            return
        if e.button() == Qt.LeftButton:
            import time
            self._last_active = time.time()
            if self._sticky():  # grabbing wakes it up
                self.mood = self.app_mood
            self._dragging = True
            self._moved = False
            self._drag_off = e.globalPosition().toPoint() - self.pos()
            self._press_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if self._dragging:
            now = e.globalPosition().toPoint()
            if (now - self._press_pos).manhattanLength() > 6:
                self._moved = True
            self._tilt = max(-0.2, min(0.2, (now.x() - self.x()) * 0.002 * self.dir))
            self.move(now - self._drag_off)

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton and self._right_down:
            self._right_down = False
            self._open_menu(e.globalPosition().toPoint())
            return
        self._right_down = False
        was_drag = self._moved
        self._dragging = False
        self._tilt = 0.0
        if not was_drag and e.button() == Qt.LeftButton:
            self._handle_tap()
        else:
            # dropped mid-air: fall with gravity instead of teleporting
            self.jump_y = min(0, self.y() - self._base_y())
            self.jump_v = 0.0

    # ---------- right-click command menu + file drop ----------
    def _open_menu(self, at: QPoint):
        try:
            from PySide6.QtWidgets import QMenu
            menu = QMenu()
            menu.setStyleSheet(
                "QMenu { background:#141B3D; color:#EEF0FF;"
                " border:1px solid #2A3568; border-radius:10px; padding:6px; }"
                "QMenu::item { padding:8px 22px; border-radius:7px; font-size:13px; }"
                "QMenu::item:selected { background:#232C5E; }"
                "QMenu::separator { height:1px; background:#232C5E; margin:5px 8px; }")
            talk = menu.addAction("🎤  Talk now")
            feed = menu.addAction("🍪  Feed treat")
            shot = menu.addAction("📸  Screenshot")
            clock = menu.addAction("🕒  Time")
            menu.addSeparator()
            show = menu.addAction("🪟  Open window")
            nap = menu.addAction("😴  Nap now")
            menu.addSeparator()
            bye = menu.addAction("❌  Quit app")
            pick = menu.exec(at)
            if pick == talk:
                self.talk_requested.emit()
            elif pick == feed:
                self.feed()
            elif pick == shot:
                self.command_requested.emit("take a screenshot")
            elif pick == clock:
                self.command_requested.emit("what time is it")
            elif pick == show:
                self.show_requested.emit()
            elif pick == nap:
                self.force_nap()
            elif pick == bye:
                self.quit_requested.emit()
        except Exception:
            pass

    def force_nap(self) -> None:
        import time
        self._last_active = time.time() - (SLEEP_AFTER_S + 5)
        self.app_mood = "IDLE"
        self.mood = "SLEEPY"
        self.say("Nap time…")
        self.update()

    def dragEnterEvent(self, e):
        try:
            if e.mimeData().hasUrls():
                e.acceptProposedAction()
            else:
                e.ignore()
        except Exception:
            e.ignore()

    def dropEvent(self, e):
        try:
            urls = (e.mimeData().urls() or []) if e.mimeData() else []
            if urls:
                self.file_dropped.emit(urls[0].toLocalFile())
                e.acceptProposedAction()
                return
        except Exception:
            pass
        try:
            e.ignore()
        except Exception:
            pass

    # ---------- speech bubble ----------
    def say(self, text: str, ms: int = 2600, tint: str = "") -> None:
        """Show floating text above the buddy (tap statuses, hunger…).

        tint defaults to the current mood colour (auto mode).
        """
        try:
            if not tint:
                tint = MOOD_COLORS.get(self.mood, "#7C5CFF")
            self.bubble.show_text(text, tint)
            self._bubble_timer.stop()
            self._bubble_timer.start(ms)
            self._position_bubble()
        except Exception:
            pass

    def _position_bubble(self) -> None:
        try:
            if self.bubble.isHidden():
                return
            g = self._screen_rect()
            bw, bh = self.bubble.width(), self.bubble.height()
            x = self.x() + (self.width() - bw) // 2
            y = self.y() - bh - 10
            if y < g.top() + 4:  # dragged near top -> show below instead
                y = self.y() + self.height() + 10
            x = min(max(x, g.left() + 4), g.right() - bw - 4)
            self.bubble.move(int(x), int(y))
        except Exception:
            pass

    def closeEvent(self, event):
        try:
            self.bubble.close()
        except Exception:
            pass
        super().closeEvent(event)

    # ---------- tap routing: feed > grumpy > giggle > happy hello ----------
    def _handle_tap(self) -> None:
        import time
        now = time.time()
        self._last_active = now
        if self._sticky():
            self.mood = self.app_mood
        # 1) hungry? this tap is dinner.
        if self.mood == "HUNGRY" or self.hunger >= HUNGRY_AT:
            self.feed()
            return  # mascot handles it fully (bubble + munch), app stays quiet
        # 2) poked too fast? grumpy!
        self._poke_times = [t for t in self._poke_times if now - t < 2.0]
        self._poke_times.append(now)
        if len(self._poke_times) >= POKE_ANGRY_N:
            self._poke_times.clear()
            self.get_angry()
            return
        # 3) every Nth poke = giggle fit
        self._poke_count += 1
        if self._poke_count % LAUGH_EVERY == 0:
            self.giggle()
            self.clicked.emit()  # app still says hi while it laughs
            return
        # 4) normal happy hello
        self.poke()
        self.clicked.emit()

    # ---------- expressions ----------
    def cry(self) -> None:
        """Tears (called when something fails)."""
        import time
        self._last_active = time.time()
        self.mood = "CRY"
        self._mood_until = time.time() + 3.0
        self.say("Oops… sorry!")
        self.update()

    def hot_flash(self, why: str = "") -> None:
        """Overheated body (CPU cooking). Cools back to app mood."""
        import time
        self._last_active = time.time()
        self.mood = "HOT"
        self._mood_until = time.time() + 4.0
        self.say(why or "Phew, it's getting hot in here!")
        self.update()

    def get_angry(self) -> None:
        import time
        self.mood = "ANGRY"
        self._mood_until = time.time() + 3.0
        self._shake = 10
        self.say("Hey! Gentle!")
        self.update()

    def giggle(self) -> None:
        import time
        import random as _r
        self.mood = "LAUGH"
        self._mood_until = time.time() + 2.5
        self.jump_v = -6.0
        self._wave = 18
        self.say(_r.choice(["Haha!", "Hehehe!", "That tickles!"]))
        self.update()

    def feed(self) -> None:
        """Munch for ~2s, reset hunger, then a grateful bounce."""
        import time
        self.hunger = 0.0
        self._was_hungry = False
        self.mood = "MUNCH"
        self._mood_until = time.time() + 2.2
        self._wave = 12
        self.say("Nom nom… yummy!")
        self.update()
        QTimer.singleShot(2300, self._after_meal)

    def _after_meal(self):
        import time
        if self.mood == "MUNCH":
            self.mood = "HAPPY"
            self._mood_until = time.time() + 2.0
            self.jump_v = -7.0
            self.say("Thank you!")
            self.update()

    # ================= painting =================

    def paintEvent(self, event):
        s = self.width()  # square canvas
        u = s / 100.0     # unit: design on a 100x100 grid
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(self.width() / 2 + self._tilt * s, self.height() / 2)
        p.rotate(self._tilt * 60 + (360.0 - self._spin))

        mood_c = QColor(MOOD_COLORS.get(self.mood, "#7C5CFF"))
        body_c = QColor(self.accent if self.mood == "IDLE" else MOOD_COLORS.get(self.mood))

        # drop shadow
        p.setPen(Qt.NoPen)
        sh = QColor(0, 0, 0, 90)
        p.setBrush(sh)
        p.drawEllipse(int(-30 * u), int(34 * u), int(60 * u), int(12 * u))

        # antenna
        p.setPen(QPen(QColor("#3A4470"), 3 * u))
        p.drawLine(0, int(-34 * u), 0, int(-46 * u))
        glow = QRadialGradient(0, int(-48 * u), 10 * u)
        glow.setColorAt(0, mood_c.lighter(140))
        glow.setColorAt(1, QColor(mood_c.red(), mood_c.green(), mood_c.blue(), 0))
        p.setBrush(glow)
        p.drawEllipse(int(-10 * u), int(-58 * u), int(20 * u), int(20 * u))
        p.setBrush(mood_c)
        p.drawEllipse(int(-4 * u), int(-52 * u), int(8 * u), int(8 * u))

        # body (glossy bot)
        grad = QRadialGradient(int(-12 * u), int(-16 * u), int(52 * u))
        grad.setColorAt(0, QColor("#FFFFFF"))
        grad.setColorAt(0.35, body_c.lighter(125))
        grad.setColorAt(1, body_c.darker(165))
        p.setBrush(grad)
        p.drawRoundedRect(int(-32 * u), int(-34 * u), int(64 * u), int(70 * u),
                          22 * u, 22 * u)

        # arms (right one waves hello while _wave ticks down)
        arm_pen = QPen(body_c.darker(150), 7 * u)
        arm_pen.setCapStyle(Qt.RoundCap)
        p.setPen(arm_pen)
        p.drawLine(int(-30 * u), int(10 * u), int(-38 * u), int(26 * u))
        if self._wave > 0 or self.mood == "LAUGH":
            wag = math.sin(self.phase * 2.2) * 5 * u
            p.drawLine(int(30 * u), int(10 * u),
                       int(40 * u + wag), int(-10 * u))
        else:
            p.drawLine(int(30 * u), int(10 * u), int(38 * u), int(26 * u))

        # sleep cap while dozing
        if self.mood == "SLEEPY":
            cap_c = QColor("#3B4478")
            p.setPen(Qt.NoPen)
            p.setBrush(cap_c)
            p.drawPolygon([
                QPoint(int(-28 * u), int(-28 * u)),
                QPoint(int(-4 * u), int(-54 * u)),
                QPoint(int(10 * u), int(-26 * u))])
            p.setBrush(QColor("#E8EBFF"))
            p.drawEllipse(int(-8 * u), int(-58 * u), int(9 * u), int(9 * u))
            p.setBrush(QColor("#E8EBFF"))
            p.drawRoundedRect(int(-30 * u), int(-32 * u), int(44 * u), int(7 * u),
                              3 * u, 3 * u)

        # face visor
        p.setBrush(QColor("#0C1130"))
        p.drawRoundedRect(int(-24 * u), int(-20 * u), int(48 * u), int(34 * u),
                          12 * u, 12 * u)

        # eyes (blink = flat line; pupils watch YOUR cursor)
        if self._dragging:
            lx, ly = 0.0, 0.0
        else:
            lx, ly = self._look_offset()
            lx += 1.5 * self.dir  # slight walk-direction bias
        M = self.mood
        sleepy = M == "SLEEPY"
        surprised = M == "SURPRISED"
        laugh = M == "LAUGH"
        munch = M == "MUNCH"
        angry = M == "ANGRY"
        cry = M == "CRY"
        hungry = M == "HUNGRY"
        if self.blink > 0 or sleepy:
            p.setPen(QPen(QColor("#9FE8FF"), 3 * u))
            p.drawLine(int(-16 * u), int(-4 * u), int(-6 * u), int(-4 * u))
            p.drawLine(int(6 * u), int(-4 * u), int(16 * u), int(-4 * u))
        elif laugh or munch:
            # happy ^^ arcs (also gentle CARE eyes)
            p.setPen(QPen(QColor("#EAFBFF"), 3 * u))
            p.setBrush(Qt.NoBrush)
            p.drawArc(int(-18 * u), int(-10 * u), int(13 * u), int(12 * u), 30 * 16, 120 * 16)
            p.drawArc(int(5 * u), int(-10 * u), int(13 * u), int(12 * u), 30 * 16, 120 * 16)
        elif self.mood == "CARE":
            # soft sympathetic eyes
            p.setPen(QPen(QColor("#FFE9C4"), 3 * u))
            p.setBrush(Qt.NoBrush)
            p.drawArc(int(-18 * u), int(-9 * u), int(13 * u), int(11 * u), 30 * 16, 120 * 16)
            p.drawArc(int(5 * u), int(-9 * u), int(13 * u), int(11 * u), 30 * 16, 120 * 16)
        elif hungry:
            # droopy half-mast eyes + tiny pupils
            p.setBrush(QColor("#EAFBFF"))
            p.drawEllipse(int(-17 * u), int(-8 * u), int(13 * u), int(8 * u))
            p.drawEllipse(int(4 * u), int(-8 * u), int(13 * u), int(8 * u))
            p.setBrush(QColor("#10163A"))
            p.drawEllipse(int(-12 * u), int(-5 * u), int(4 * u), int(4 * u))
            p.drawEllipse(int(9 * u), int(-5 * u), int(4 * u), int(4 * u))
            p.setPen(QPen(QColor("#9FE8FF"), 2.4 * u))
            p.drawLine(int(-17 * u), int(-9 * u), int(-4 * u), int(-9 * u))
            p.drawLine(int(4 * u), int(-9 * u), int(17 * u), int(-9 * u))
        else:
            grow = 1.25 if surprised else 1.0
            ew, eh = 13 * u * grow, 15 * u * grow
            ex0, ey0 = -17 * u, -11 * u
            p.setBrush(QColor("#EAFBFF"))
            p.drawEllipse(int(ex0 - (ew - 13 * u) / 2), int(ey0 - (eh - 15 * u) / 2),
                          int(ew), int(eh))
            p.drawEllipse(int(ex0 + 21 * u - (ew - 13 * u) / 2), int(ey0 - (eh - 15 * u) / 2),
                          int(ew), int(eh))
            pr = 0.55 if surprised else 1.0  # tiny pupils = shock
            p.setBrush(QColor("#10163A"))
            p.drawEllipse(int(-13 * u + lx * u), int(-7 * u + ly * u), int(7 * u * pr + 2 * u), int(9 * u * pr + 2 * u))
            p.drawEllipse(int(8 * u + lx * u), int(-7 * u + ly * u), int(7 * u * pr + 2 * u), int(9 * u * pr + 2 * u))
            p.setBrush(QColor("#FFFFFF"))
            p.drawEllipse(int(-12 * u + lx * u), int(-6 * u + ly * u), int(2.6 * u), int(3.4 * u))
            p.drawEllipse(int(9 * u + lx * u), int(-6 * u + ly * u), int(2.6 * u), int(3.4 * u))
        if angry:
            # slanted brows
            p.setPen(QPen(QColor("#FFB4B4"), 3.4 * u))
            p.drawLine(int(-19 * u), int(-17 * u), int(-5 * u), int(-11 * u))
            p.drawLine(int(19 * u), int(-17 * u), int(5 * u), int(-11 * u))
        if cry:
            # animated tears
            drop = (abs(math.sin(self.phase * 1.2)) * 6 + 3) * u
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#7CC4FF"))
            p.drawEllipse(int(-14 * u), int(2 * u), int(6 * u), int(drop))
            p.drawEllipse(int(8 * u), int(2 * u), int(6 * u), int(drop))
        if self.mood == "HOT":
            # sweat bead rolling down + heat waves
            slide = (self.phase * 3 % 14) * u
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#9FE8FF"))
            p.drawEllipse(int(14 * u), int(-14 * u + slide), int(5 * u), int(7 * u))
            p.setPen(QPen(QColor("#FF9F43"), 2.2 * u))
            p.setBrush(Qt.NoBrush)
            for kx in (-30, -36):
                p.drawArc(int(kx * u), int(-6 * u), int(7 * u), int(16 * u),
                          60 * 16, 120 * 16)
        if hungry:
            # floating cookie craving (thought bubble + cookie)
            bob = math.sin(self.phase * 0.9) * 2.5 * u
            p.setPen(QPen(QColor("#8B93C9"), 1.6 * u))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(24 * u), int(-34 * u + bob), int(16 * u), int(16 * u))
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#D9A066"))
            p.drawEllipse(int(25.5 * u), int(-32.5 * u + bob), int(13 * u), int(13 * u))
            p.setBrush(QColor("#6B4226"))
            for cx, cy in ((28, -29), (33, -27), (30, -24)):
                p.drawEllipse(int(cx * u), int((cy) * u + bob), int(2.2 * u), int(2.2 * u))
        if sleepy:
            # floating Z's
            p.setPen(QPen(QColor("#8B93C9"), int(3 * u)))
            from PySide6.QtGui import QFont
            f = QFont("Segoe UI", int(11 * u))
            f.setBold(True)
            p.setFont(f)
            bob = math.sin(self.phase * 0.7) * 3 * u
            p.drawText(int(20 * u), int(-26 * u + bob), "z")
            f2 = QFont("Segoe UI", int(8 * u))
            f2.setBold(True)
            p.setFont(f2)
            p.drawText(int(29 * u), int(-34 * u + bob), "z")

        # mouth by mood (SPEAKING chomps wide so talking reads clearly)
        pen = QPen(mood_c.lighter(130), 2.6 * u)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        if self.mood == "SPEAKING":
            open_h = (abs(math.sin(self.phase * 1.6)) * 10 + 3) * u
            p.setBrush(mood_c.darker(120))
            p.drawEllipse(int(-6 * u), int(19 * u), int(12 * u), int(open_h))
        elif self.mood == "MUNCH":
            # fast chomp while eating
            chomp = (abs(math.sin(self.phase * 3.2)) * 8 + 1.5) * u
            p.setBrush(mood_c.darker(120))
            p.drawEllipse(int(-6 * u), int(19 * u), int(12 * u), int(chomp))
        elif self.mood == "HOT":
            # panting tongue
            pant = (abs(math.sin(self.phase * 2.4)) * 5 + 3) * u
            p.setBrush(QColor("#FF8A8A"))
            p.drawRoundedRect(int(-4 * u), int(21 * u), int(8 * u), int(pant),
                              3 * u, 3 * u)
        elif self.mood == "LAUGH":
            # big open giggle smile
            p.setBrush(mood_c.darker(110))
            p.drawEllipse(int(-9 * u), int(17 * u), int(18 * u), int(13 * u))
        elif self.mood == "CRY":
            # wavy sob
            p.setPen(QPen(mood_c.lighter(130), 2.4 * u))
            pts = [(-9, 24), (-4.5, 21), (0, 24), (4.5, 21), (9, 24)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                p.drawLine(int(x1 * u), int(y1 * u), int(x2 * u), int(y2 * u))
        elif self.mood == "ANGRY":
            # deep frown
            p.drawArc(int(-9 * u), int(20 * u), int(18 * u), int(13 * u), 35 * 16, 110 * 16)
        elif self.mood == "HUNGRY":
            # small wavy empty-belly line
            p.setPen(QPen(mood_c.lighter(130), 2.2 * u))
            pts = [(-7, 23), (-3.5, 25), (0, 23), (3.5, 25), (7, 23)]
            for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
                p.drawLine(int(x1 * u), int(y1 * u), int(x2 * u), int(y2 * u))
        elif self.mood == "SURPRISED":
            p.setBrush(mood_c.darker(120))
            p.drawEllipse(int(-5 * u), int(19 * u), int(10 * u), int(11 * u))
        elif self.mood == "SLEEPY":
            p.drawLine(int(-7 * u), int(24 * u), int(7 * u), int(24 * u))
        elif self.mood == "HAPPY":
            p.drawArc(int(-9 * u), int(16 * u), int(18 * u), int(14 * u), 200 * 16, 140 * 16)
        elif self.mood == "CARE":
            # small warm smile
            p.drawArc(int(-7 * u), int(18 * u), int(14 * u), int(10 * u), 205 * 16, 130 * 16)
        elif self.mood == "ERROR":
            p.drawLine(int(-8 * u), int(24 * u), int(8 * u), int(24 * u))
        elif self.mood == "THINKING":
            # spinning dots above visor
            for k in range(3):
                a = self.phase + k * 2.09
                dx, dy = math.cos(a) * 26 * u, -30 * u + math.sin(a) * 6 * u
                p.setBrush(mood_c)
                p.drawEllipse(int(dx - 2.4 * u), int(dy - 2.4 * u),
                              int(4.8 * u), int(4.8 * u))
            p.drawArc(int(-8 * u), int(18 * u), int(16 * u), int(10 * u), 210 * 16, 120 * 16)
        else:
            p.drawArc(int(-8 * u), int(18 * u), int(16 * u), int(10 * u), 210 * 16, 120 * 16)

        # listening headband
        if self.mood == "LISTENING":
            p.setPen(QPen(mood_c, 4 * u))
            p.drawArc(int(-30 * u), int(-38 * u), int(60 * u), int(30 * u), 20 * 16, 140 * 16)
            p.setBrush(mood_c)
            p.drawEllipse(int(22 * u), int(-22 * u), int(10 * u), int(14 * u))
            p.drawEllipse(int(-32 * u), int(-22 * u), int(10 * u), int(14 * u))

        # feet nubs
        p.setPen(Qt.NoPen)
        p.setBrush(body_c.darker(150))
        bounce = abs(math.sin(self.phase)) * 3 * u if not self.paused else 0
        p.drawEllipse(int(-22 * u), int(32 * u - bounce), int(16 * u), int(9 * u))
        p.drawEllipse(int(6 * u), int(32 * u - bounce), int(16 * u), int(9 * u))
        p.end()
