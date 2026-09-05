"""Reusable widgets: voice orb, status pill, chat bubbles (premium)."""
from __future__ import annotations

import math
from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QRadialGradient, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from .theme import ACCENT


STATE_COLORS = {
    "IDLE": "#7C5CFF",
    "LISTENING": "#34D399",
    "THINKING": "#FBBF24",
    "SPEAKING": "#38BDF8",
    "ERROR": "#F87171",
}


class VoiceOrb(QWidget):
    """Glowing orb with orbit ring; motion character changes per state."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 240)
        self.state = "IDLE"
        self.level = 0.0
        self.intensity = 1.0
        self._t = QTimer(self)
        self._t.timeout.connect(self._tick)
        self._t.start(50)

    def set_state(self, state: str):
        self.state = state

    def set_intensity(self, name: str):
        self.intensity = {"low": 0.4, "medium": 1.0, "high": 1.8}.get(name, 1.0)

    def _tick(self):
        speed = {"IDLE": 0.03, "LISTENING": 0.12, "THINKING": 0.22,
                 "SPEAKING": 0.15, "ERROR": 0.05}.get(self.state, 0.05)
        self.level = (self.level + speed * self.intensity) % (2 * math.pi)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        base = QColor(STATE_COLORS.get(self.state, ACCENT))
        pulse = (math.sin(self.level) + 1) / 2
        r = 66 + pulse * 16 * self.intensity

        # outer halo
        halo = QRadialGradient(cx, cy, r + 52)
        halo.setColorAt(0, base)
        fade = QColor(base)
        fade.setAlpha(0)
        halo.setColorAt(1, fade)
        p.setBrush(halo)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - r - 52), int(cy - r - 52),
                      int((r + 52) * 2), int((r + 52) * 2))

        # orbit ring (rotating dashes feel via moving arc)
        pen = QPen(QColor(base))
        pen.setWidth(2)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        start = int(-self.level * 180 / math.pi * 16)
        p.drawArc(int(cx - r - 22), int(cy - r - 22),
                  int((r + 22) * 2), int((r + 22) * 2), start, 70 * 16)
        p.drawArc(int(cx - r - 22), int(cy - r - 22),
                  int((r + 22) * 2), int((r + 22) * 2), start + 180 * 16, 40 * 16)

        # glass core
        core = QRadialGradient(cx - 16, cy - 22, 92)
        core.setColorAt(0, QColor("#FFFFFF"))
        core.setColorAt(0.32, base.lighter(135))
        core.setColorAt(1, base.darker(160))
        p.setBrush(core)
        p.setPen(Qt.NoPen)
        p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))

        # specular highlight
        hi = QColor(255, 255, 255, 90)
        p.setBrush(hi)
        p.drawEllipse(int(cx - r * 0.55), int(cy - r * 0.62),
                      int(r * 0.5), int(r * 0.34))
        p.end()


class StateBadge(QLabel):
    """Rounded status pill, e.g. '● LISTENING'."""

    def __init__(self, parent=None):
        super().__init__("IDLE", parent)
        self.setAlignment(Qt.AlignCenter)
        self.set_state("IDLE")

    def set_state(self, state: str):
        color = STATE_COLORS.get(state, ACCENT)
        self.setText(f"  ●  {state}  ")
        self.setStyleSheet(
            f"color:{color}; background:rgba(124,92,255,26);"
            "border:1px solid rgba(124,92,255,70); border-radius:14px;"
            "font-weight:700; font-size:12px; letter-spacing:3px; padding:7px 6px;"
        )


class ChatBubble(QWidget):
    """Message row: avatar + glass bubble + timestamp."""

    def __init__(self, who: str, text: str, parent=None):
        super().__init__(parent)
        mine = who.upper() != "NOVA"
        outer = QHBoxLayout(self)
        outer.setContentsMargins(4, 3, 4, 3)
        outer.setSpacing(10)

        avatar = QLabel("Y" if mine else "N")
        avatar.setFixedSize(34, 34)
        avatar.setAlignment(Qt.AlignCenter)
        if mine:
            avatar.setStyleSheet(
                "background:#2B3358; color:#C9D1FF; border-radius:17px;"
                "font-weight:800; font-size:14px;")
        else:
            avatar.setStyleSheet(
                f"background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 {ACCENT}, stop:1 #38BDF8); color:white;"
                "border-radius:17px; font-weight:800; font-size:14px;")

        bubble = QFrame()
        bubble.setStyleSheet(
            "QFrame { border-radius:14px; padding:2px; %s }" % (
                "background:#1B2347; border:1px solid #2A3568;" if mine
                else "background:#151C3D; border:1px solid #232C5E;"))
        lay = QVBoxLayout(bubble)
        lay.setContentsMargins(13, 9, 13, 9)
        lay.setSpacing(3)
        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        title = QLabel(who.upper())
        title.setStyleSheet("color:#8B93C9; font-size:10px; font-weight:800; letter-spacing:2px;")
        head.addWidget(title)
        head.addStretch()
        ts = QLabel(datetime.now().strftime("%I:%M %p"))
        ts.setStyleSheet("color:#565E96; font-size:10px;")
        head.addWidget(ts)
        lay.addLayout(head)
        body = QLabel(text)
        body.setWordWrap(True)
        body.setTextInteractionFlags(Qt.TextSelectableByMouse)
        body.setStyleSheet("color:#EEF0FF; font-size:13.5px; line-height: 1.4;")
        lay.addWidget(body)

        if mine:
            outer.addStretch()
            outer.addWidget(bubble, 0)
            outer.addWidget(avatar, 0, Qt.AlignTop)
        else:
            outer.addWidget(avatar, 0, Qt.AlignTop)
            outer.addWidget(bubble, 1)


def wrap_center(widget: QWidget) -> QWidget:
    outer = QWidget()
    lay = QHBoxLayout(outer)
    lay.addStretch()
    lay.addWidget(widget)
    lay.addStretch()
    return outer
