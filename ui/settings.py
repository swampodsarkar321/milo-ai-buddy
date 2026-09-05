"""Settings page (premium): centered column, section cards, swatches, segmented controls."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QFrame,
                               QHBoxLayout, QLabel, QLineEdit, QMessageBox,
                               QPushButton, QScrollArea, QVBoxLayout, QWidget)

from voice.listener import list_microphones
from voice.text_to_speech import EDGE_VOICES

ACCENT_SWATCHES = ["#7C5CFF", "#38BDF8", "#34D399", "#FBBF24", "#F87171", "#EC4899"]
LABEL_W = 168


class SettingsPage(QWidget):
    save_requested = Signal(dict)   # full settings dict (no AI/engine keys)
    test_voice_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._theme = "dark"
        self._anim = "medium"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- header ----
        head = QWidget()
        hl = QVBoxLayout(head)
        hl.setContentsMargins(26, 20, 26, 6)
        hl.setSpacing(2)
        t = QLabel("Settings")
        t.setObjectName("pageTitle")
        hl.addWidget(t)
        s = QLabel("Tune voice, look and privacy.")
        s.setObjectName("pageSub")
        hl.addWidget(s)
        outer.addWidget(head)

        # ---- scroll body, centered narrow column ----
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 8, 0, 8)
        cl.addStretch()
        self.col = QVBoxLayout()
        self.col.setSpacing(14)
        colwrap = QWidget()
        colwrap.setLayout(self.col)
        colwrap.setMaximumWidth(700)
        cl.addWidget(colwrap, 1)
        cl.addStretch()
        scroll.setWidget(center)
        outer.addWidget(scroll, 1)

        self._build_engine()
        self._build_voice()
        self._build_appearance()
        self._build_personality()
        self._build_privacy()
        # segmented state wiring (connected once)
        self.theme_grp.buttonClicked.connect(
            lambda b: setattr(self, "_theme",
                              "dark" if self.theme_grp.id(b) == 0 else "light"))
        self.anim_grp.buttonClicked.connect(
            lambda b: setattr(self, "_anim",
                              {0: "low", 1: "medium", 2: "high"}[self.anim_grp.id(b)]))

        # ---- sticky save bar ----
        bar = QWidget()
        bar.setObjectName("savebar")
        bar.setStyleSheet(
            "#savebar { border-top: 1px solid #1C2447; background: transparent; }")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(26, 12, 26, 14)
        bl.addStretch()
        hint = QLabel("Changes apply instantly after save.")
        hint.setStyleSheet("color:#626B9B; font-size:12px;")
        bl.addWidget(hint)
        save = QPushButton("  Save settings  ")
        save.setObjectName("primary")
        save.setMinimumSize(200, 48)
        save.setCursor(Qt.PointingHandCursor)
        save.setStyleSheet("font-size:14px; border-radius:14px;")
        save.clicked.connect(self._collect)
        bl.addWidget(save)
        outer.addWidget(bar)

    # ================= builders =================

    def _section(self, icon: str, title: str, desc: str) -> QVBoxLayout:
        card = QFrame()
        card.setObjectName("setcard")
        card.setStyleSheet(
            "#setcard { background:#111834; border:1px solid #1C2447; border-radius:18px; }")
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(12)
        h = QHBoxLayout()
        h.setSpacing(12)
        ic = QLabel(icon)
        ic.setFixedSize(40, 40)
        ic.setAlignment(Qt.AlignCenter)
        ic.setStyleSheet(
            "background:rgba(124,92,255,30); border:1px solid rgba(124,92,255,80);"
            "border-radius:12px; font-size:19px;")
        h.addWidget(ic)
        tt = QVBoxLayout()
        tt.setSpacing(1)
        name = QLabel(title)
        name.setStyleSheet("font-size:15px; font-weight:800; color:#F2F4FF;")
        tt.addWidget(name)
        dd = QLabel(desc)
        dd.setStyleSheet("font-size:12px; color:#8B93C9;")
        dd.setWordWrap(True)
        tt.addWidget(dd)
        h.addLayout(tt, 1)
        lay.addLayout(h)
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet("background:#1C2447; border:none;")
        lay.addWidget(div)
        self.col.addWidget(card)
        return lay

    def _row(self, parent_lay: QVBoxLayout, label: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        lab = QLabel(label)
        lab.setFixedWidth(LABEL_W)
        lab.setStyleSheet("color:#A6AED6; font-size:13px; font-weight:600;")
        lab.setWordWrap(True)
        row.addWidget(lab)
        parent_lay.addLayout(row)
        return row

    def _checkrow(self, parent_lay: QVBoxLayout, title: str, desc: str) -> QCheckBox:
        box = QCheckBox(title)
        box.setStyleSheet("font-size:13.5px; font-weight:600; color:#EEF0FF;")
        parent_lay.addWidget(box)
        d = QLabel(desc)
        d.setStyleSheet("color:#626B9B; font-size:12px; margin-left:30px; margin-top:-8px;")
        d.setWordWrap(True)
        parent_lay.addWidget(d)
        return box

    # ================= sections =================

    def _build_engine(self):
        lay = self._section("✦", "Engine", "The brain behind the app. Fully automatic.")
        row = QHBoxLayout()
        row.setSpacing(10)
        dot = QLabel("●")
        dot.setObjectName("engineDot")
        dot.setStyleSheet("font-size:16px; color:#FBBF24;")
        row.addWidget(dot)
        self.engine_status = QLabel("Checking…")
        self.engine_status.setStyleSheet("font-weight:700; font-size:13.5px;")
        row.addWidget(self.engine_status, 1)
        lay.addLayout(row)
        self.engine_dot = dot

    def _build_voice(self):
        lay = self._section("◉", "Voice", "How I sound and how I listen.")
        # TTS voice + test
        row = self._row(lay, "Assistant voice")
        self.voice = QComboBox()
        self.voice.setMinimumHeight(42)
        for vid, label in EDGE_VOICES:
            self.voice.addItem(label, vid)
        row.addWidget(self.voice, 1)
        test = QPushButton("Test")
        test.setObjectName("ghost")
        test.setMinimumSize(86, 42)
        test.clicked.connect(self.test_voice_requested.emit)
        row.addWidget(test)
        # speed
        row = self._row(lay, "Speaking speed")
        self.rate = QComboBox()
        self.rate.setMinimumHeight(42)
        self.rate.addItems(["Slower  −20%", "Slow  −10%", "Normal", "Fast  +10%",
                            "Faster  +20%", "Fastest  +30%"])
        row.addWidget(self.rate, 1)
        # mic
        row = self._row(lay, "Microphone")
        self.mic = QComboBox()
        self.mic.setMinimumHeight(42)
        try:
            self.mic.addItems(list_microphones())
        except Exception:
            self.mic.addItem("default")
        row.addWidget(self.mic, 1)
        # wake word
        row = self._row(lay, "Wake word")
        self.wake_word = QLineEdit()
        self.wake_word.setPlaceholderText("hey nova")
        self.wake_word.setMinimumHeight(42)
        row.addWidget(self.wake_word, 1)
        # toggles
        self.wake_enabled = self._checkrow(
            lay, "Wake-word listening",
            "Start listening when you say the wake word.")
        self.push_to_talk = self._checkrow(
            lay, "Push-to-talk mode",
            "Turn wake-word off; use the Talk button instead.")
        self.speak_reminders = self._checkrow(
            lay, "Speak reminders aloud",
            "Voice announcements when a reminder becomes due.")

    def _segmented(self, parent, options: list[str]) -> tuple[QHBoxLayout, QButtonGroup, list[QPushButton]]:
        row = QHBoxLayout()
        row.setSpacing(8)
        grp = QButtonGroup(parent)
        grp.setExclusive(True)
        btns: list[QPushButton] = []
        for i, opt in enumerate(options):
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setMinimumHeight(42)
            b.setStyleSheet(
                "QPushButton { border-radius:12px; }"
                "QPushButton:checked { background: rgba(124,92,255,40);"
                " border:1px solid #7C5CFF; color:white; }")
            grp.addButton(b, i)
            row.addWidget(b, 1)
            btns.append(b)
        btns[0].setChecked(True)
        return row, grp, btns

    def _build_appearance(self):
        lay = self._section("◐", "Appearance", "Make it yours.")
        # theme segmented
        trow = self._row(lay, "Theme")
        seg, self.theme_grp, _ = self._segmented(lay, ["🌙  Dark", "☀  Light"])
        trow.addLayout(seg, 1)
        # accent swatches
        arow = self._row(lay, "Accent color")
        sw = QHBoxLayout()
        sw.setSpacing(10)
        self.swatch_grp = QButtonGroup(self)
        self.swatch_grp.setExclusive(True)
        self.swatch_btns: list[QPushButton] = []
        for i, color in enumerate(ACCENT_SWATCHES):
            b = QPushButton("")
            b.setCheckable(True)
            b.setFixedSize(34, 34)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(color)
            b.setStyleSheet(
                f"QPushButton {{ background:{color}; border-radius:17px; border:2px solid transparent; }}"
                f"QPushButton:checked {{ border:2px solid white; }}")
            b.clicked.connect(lambda _=False, c=color: self._set_accent(c))
            self.swatch_grp.addButton(b, i)
            sw.addWidget(b)
            self.swatch_btns.append(b)
        self.swatch_btns[0].setChecked(True)
        self.accent = QLineEdit("#7C5CFF")
        self.accent.setMinimumHeight(42)
        self.accent.setMaximumWidth(110)
        self.accent.textChanged.connect(self._accent_typed)
        sw.addWidget(self.accent)
        sw.addStretch()
        arow.addLayout(sw, 1)
        # animation segmented
        nrow = self._row(lay, "Animation")
        nseg, self.anim_grp, _ = self._segmented(lay, ["Calm", "Normal", "Lively"])
        nrow.addLayout(nseg, 1)

    def _build_personality(self):
        lay = self._section("✎", "Personality", "Name and character.")
        row = self._row(lay, "Assistant name")
        self.pname = QLineEdit()
        self.pname.setPlaceholderText("NOVA")
        self.pname.setMinimumHeight(42)
        row.addWidget(self.pname, 1)
        row = self._row(lay, "Traits")
        self.ptraits = QLineEdit()
        self.ptraits.setPlaceholderText("Friendly, helpful, slightly playful…")
        self.ptraits.setMinimumHeight(42)
        row.addWidget(self.ptraits, 1)
        row = self._row(lay, "Reply style")
        self.pstyle = QLineEdit()
        self.pstyle.setPlaceholderText("Short and natural…")
        self.pstyle.setMinimumHeight(42)
        row.addWidget(self.pstyle, 1)

    def _build_privacy(self):
        lay = self._section("⚠", "Privacy", "Your data stays on this device.")
        row = self._row(lay, "Long-term memory")
        self.memory_enabled = QCheckBox("Remember preferences and notes")
        self.memory_enabled.setStyleSheet("font-size:13.5px; font-weight:600; color:#EEF0FF;")
        row.addWidget(self.memory_enabled, 1)
        row = self._row(lay, "Routines")
        self.routines_enabled = QCheckBox("Suggest repeated commands on time")
        self.routines_enabled.setStyleSheet("font-size:13.5px; font-weight:600; color:#EEF0FF;")
        row.addWidget(self.routines_enabled, 1)
        brow = QHBoxLayout()
        brow.setSpacing(10)
        clear_chat = QPushButton("Clear chat history")
        clear_chat.setObjectName("danger")
        clear_chat.setMinimumHeight(42)
        clear_chat.clicked.connect(lambda: self.save_requested.emit({"__clear_chat__": True}))
        brow.addWidget(clear_chat, 1)
        clear_mem = QPushButton("Clear all memories")
        clear_mem.setObjectName("danger")
        clear_mem.setMinimumHeight(42)
        clear_mem.clicked.connect(lambda: self.save_requested.emit({"__clear_mem__": True}))
        brow.addWidget(clear_mem, 1)
        lay.addLayout(brow)

    # ================= data =================

    def _set_accent(self, color: str):
        self.accent.setText(color)

    def _accent_typed(self, text: str):
        t = text.strip()
        for i, c in enumerate(ACCENT_SWATCHES):
            if c.lower() == t.lower():
                self.swatch_btns[i].setChecked(True)
                return

    def set_engine_status(self, ok: bool) -> None:
        """Read-only engine indicator — no technical detail exposed."""
        if ok:
            self.engine_status.setText("Connected — everything automatic")
            self.engine_status.setStyleSheet("font-weight:700; font-size:13.5px; color:#34D399;")
            self.engine_dot.setStyleSheet("font-size:16px; color:#34D399;")
        else:
            self.engine_status.setText("Offline — check connection")
            self.engine_status.setStyleSheet("font-weight:700; font-size:13.5px; color:#FBBF24;")
            self.engine_dot.setStyleSheet("font-size:16px; color:#FBBF24;")

    def load_config(self, cfg) -> None:
        self.set_engine_status(bool(getattr(cfg.ai, "api_key", "")))
        idx = self.voice.findData(cfg.voice.tts_voice)
        self.voice.setCurrentIndex(idx if idx >= 0 else 0)
        rate_map = {"-20%": 0, "-10%": 1, "+0%": 2, "+10%": 3, "+20%": 4, "+30%": 5}
        self.rate.setCurrentIndex(rate_map.get(cfg.voice.rate, 2))
        self.wake_word.setText(cfg.voice.wake_word)
        self.wake_enabled.setChecked(cfg.voice.wake_word_enabled)
        self.push_to_talk.setChecked(cfg.voice.push_to_talk)
        self.speak_reminders.setChecked(cfg.privacy.speak_reminders)
        # theme segmented
        self._theme = cfg.appearance.theme if cfg.appearance.theme in ("dark", "light") else "dark"
        self.theme_grp.button(0 if self._theme == "dark" else 1).setChecked(True)
        # accent
        acc = (cfg.appearance.accent or "#7C5CFF").strip()
        self.accent.setText(acc)
        for i, c in enumerate(ACCENT_SWATCHES):
            if c.lower() == acc.lower():
                self.swatch_btns[i].setChecked(True)
        # animation segmented
        anim_map = {"low": 0, "medium": 1, "high": 2}
        self._anim = cfg.appearance.animation_intensity if cfg.appearance.animation_intensity in anim_map else "medium"
        self.anim_grp.button(anim_map[self._anim]).setChecked(True)
        self.pname.setText("" if cfg.personality.name == "NOVA" else cfg.personality.name)
        self.ptraits.setText(cfg.personality.traits)
        self.pstyle.setText(cfg.personality.style)
        self.memory_enabled.setChecked(cfg.privacy.memory_enabled)
        self.routines_enabled.setChecked(bool(getattr(cfg.privacy, "routines", True)))

    def _collect(self):
        mic_text = self.mic.currentText()
        try:
            mic_index = int(mic_text.split(":")[0])
        except Exception:
            mic_index = -1
        rate_rev = ["-20%", "-10%", "+0%", "+10%", "+20%", "+30%"]
        data = {
            # NOTE: no "ai" section — engine config lives in the background
            # (.env) and can never be viewed or changed from this UI.
            "voice": {"tts_voice": self.voice.currentData(),
                      "rate": rate_rev[self.rate.currentIndex()],
                      "microphone_index": mic_index,
                      "wake_word": self.wake_word.text().strip() or "hey nova",
                      "wake_word_enabled": self.wake_enabled.isChecked(),
                      "push_to_talk": self.push_to_talk.isChecked()},
            "appearance": {"theme": self._theme,
                           "accent": self.accent.text().strip() or "#7C5CFF",
                           "animation_intensity": self._anim},
            "privacy": {"memory_enabled": self.memory_enabled.isChecked(),
                        "speak_reminders": self.speak_reminders.isChecked(),
                        "routines": self.routines_enabled.isChecked()},
            "personality": {"name": self.pname.text().strip() or "NOVA",
                            "traits": self.ptraits.text().strip(),
                            "style": self.pstyle.text().strip()},
        }
        self.save_requested.emit(data)
        QMessageBox.information(self, "Settings", "Settings saved.")
