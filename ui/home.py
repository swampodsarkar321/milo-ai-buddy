"""Home page — Alexa-style: greeting hero + activity feed (buddy is the face)."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget, QFrame)

from .theme import ACCENT
from .widgets import StateBadge

CARD_STYLE = ("QFrame#feedcard { background:#111834; border:1px solid #1C2447;"
              " border-radius:18px; }")


class HomePage(QWidget):
    mic_pressed = Signal()
    stop_pressed = Signal()
    text_sent = Signal(str)
    quick_requested = Signal(str)      # natural-language command

    def __init__(self, accent=ACCENT, app_name="NOVA",
                 tagline="Your personal voice partner", parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(28, 20, 28, 12)
        lay.setSpacing(14)

        # ---------- hero card ----------
        hero = QFrame()
        hero.setObjectName("feedcard")
        hero.setStyleSheet(CARD_STYLE)
        hl = QVBoxLayout(hero)
        hl.setContentsMargins(24, 20, 24, 20)
        hl.setSpacing(8)

        self.greeting = QLabel("Hello")
        self.greeting.setStyleSheet("font-size:22px; font-weight:800; color:#F2F4FF;")
        hl.addWidget(self.greeting)
        self.dateline = QLabel("")
        self.dateline.setStyleSheet("color:#8B93C9; font-size:12.5px;")
        hl.addWidget(self.dateline)

        mid = QVBoxLayout()
        mid.setSpacing(8)
        self.badge = StateBadge()
        mid.addWidget(self.badge, alignment=Qt.AlignLeft)
        self.transcript = QLabel("Press the mic and speak…")
        self.transcript.setWordWrap(True)
        self.transcript.setStyleSheet("color:#C6CBF0; font-size:13.5px; font-style:italic;")
        mid.addWidget(self.transcript)
        self.response = QLabel("")
        self.response.setWordWrap(True)
        self.response.setStyleSheet("color:#FFFFFF; font-size:14.5px; font-weight:600;")
        mid.addWidget(self.response)
        btnrow = QHBoxLayout()
        btnrow.setSpacing(10)
        self.mic_btn = QPushButton("  ●  Talk  ")
        self.mic_btn.setObjectName("primary")
        self.mic_btn.setCursor(Qt.PointingHandCursor)
        self.mic_btn.setMinimumSize(150, 48)
        self.mic_btn.setStyleSheet("font-size:15px; border-radius:24px;")
        self.mic_btn.clicked.connect(self.mic_pressed.emit)
        btnrow.addWidget(self.mic_btn)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.setObjectName("ghost")
        self.stop_btn.setMinimumSize(96, 48)
        self.stop_btn.setStyleSheet("border-radius:24px;")
        self.stop_btn.clicked.connect(self.stop_pressed.emit)
        btnrow.addWidget(self.stop_btn)
        btnrow.addStretch()
        mid.addLayout(btnrow)
        hl.addLayout(mid)
        lay.addWidget(hero)

        # ---------- quick chips ----------
        lay.addWidget(self._label("Try saying"))
        chips = QHBoxLayout()
        chips.setSpacing(8)
        for label, cmd in (("⏰ Remind me", "Remind me in 1 hour to stretch"),
                           ("▶ YouTube", "open youtube"),
                           ("🕒 Time", "what time is it"),
                           ("📸 Screenshot", "take a screenshot")):
            c = QPushButton(label)
            c.setCursor(Qt.PointingHandCursor)
            c.setMinimumHeight(38)
            c.clicked.connect(lambda _=False, x=cmd: self.quick_requested.emit(x))
            chips.addWidget(c)
        chips.addStretch()
        chipwrap = QWidget()
        chipwrap.setLayout(chips)
        lay.addWidget(chipwrap)

        # ---------- activity cards (filled by refresh) ----------
        self.rem_card = self._card(lay, "⏰", "Up next")
        self.rem_body = self._card_body(self.rem_card)
        self.mem_card = self._card(lay, "🧠", "Remembered")
        self.mem_body = self._card_body(self.mem_card)
        self.recent_card = self._card(lay, "💬", "Recent chat")
        self.recent_body = self._card_body(self.recent_card)

        # ---------- typed fallback ----------
        trow = QHBoxLayout()
        trow.setSpacing(10)
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("…or type a message and press Enter")
        self.text_input.setMinimumHeight(46)
        self.text_input.returnPressed.connect(self._send_text)
        trow.addWidget(self.text_input, 1)
        send = QPushButton("Send")
        send.setObjectName("primary")
        send.setMinimumSize(100, 46)
        send.setStyleSheet("border-radius:14px;")
        send.clicked.connect(self._send_text)
        trow.addWidget(send)
        lay.addLayout(trow)
        lay.addStretch()

        scroll.setWidget(body)
        outer.addWidget(scroll)

    # ---------- builders ----------
    @staticmethod
    def _label(text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet("font-size:13px; font-weight:800; color:#A6AED6; letter-spacing:1px;")
        return l

    def _card(self, parent_lay, icon: str, title: str) -> QFrame:
        card = QFrame()
        card.setObjectName("feedcard")
        card.setStyleSheet(CARD_STYLE + "QFrame#feedcard:hover { border:1px solid #2A3568; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(20, 14, 20, 14)
        lay.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel(f"{icon}  {title}")
        t.setStyleSheet("font-size:14px; font-weight:800; color:#F2F4FF;")
        head.addWidget(t)
        head.addStretch()
        lay.addLayout(head)
        parent_lay.addWidget(card)
        return card

    @staticmethod
    def _card_body(card: QFrame) -> QVBoxLayout:
        body = QVBoxLayout()
        body.setSpacing(6)
        card.layout().addLayout(body)
        return body

    @staticmethod
    def _clear(lay: QVBoxLayout):
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def _line(self, text: str, sub: str = "") -> QLabel:
        l = QLabel(f"<div style='color:#EEF0FF; font-size:13px'>{text}</div>"
                   + (f"<div style='color:#626B9B; font-size:11.5px'>{sub}</div>" if sub else ""))
        l.setWordWrap(True)
        l.setStyleSheet("background:transparent; padding:2px 0;")
        return l

    def _empty(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet("color:#565E96; font-size:12.5px; font-style:italic;")
        return l

    # ---------- data (called by MainWindow) ----------
    def refresh(self, feed: dict) -> None:
        self.greeting.setText(feed.get("greeting", "Hello"))
        self.dateline.setText(feed.get("dateline", ""))
        # reminders
        self._clear(self.rem_body)
        rems = feed.get("reminders", [])[:3]
        if rems:
            for r in rems:
                self.rem_body.addWidget(self._line(f"⏰ {r['text']}", r["when"]))
        else:
            self.rem_body.addWidget(self._empty("Nothing scheduled. Say “remind me…”."))
        # memories
        self._clear(self.mem_body)
        mems = feed.get("memories", [])[:3]
        if mems:
            for m in mems:
                self.mem_body.addWidget(self._line(f"• {m['value']}", m.get("category", "")))
        else:
            self.mem_body.addWidget(self._empty("Nothing remembered yet."))
        # recent chat
        self._clear(self.recent_body)
        recent = feed.get("recent", [])[-2:]
        if recent:
            for who, text in recent:
                short = (text[:90] + "…") if len(text) > 90 else text
                self.recent_body.addWidget(
                    self._line(f"<b>{who}:</b> {short}"))
        else:
            self.recent_body.addWidget(self._empty("No conversation yet."))

    # ---------- voice state (called by MainWindow) ----------
    def _send_text(self):
        t = self.text_input.text().strip()
        if t:
            self.text_input.clear()
            self.text_sent.emit(t)

    def set_state(self, state: str):
        self.badge.set_state(state)
        self.mic_btn.setDisabled(state in ("LISTENING", "THINKING"))

    def show_transcript(self, text: str):
        self.transcript.setText(f"“{text}”" if text else "Press the mic and speak…")

    def show_response(self, text: str):
        self.response.setText(text or "")
