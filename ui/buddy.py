"""Buddy page: everything about your companion in one slim place.

- Show/hide, size, bubble colour, stay-on-close
- Hunger meter + Feed now button
- Current mood line
All changes emit `changed(dict)`; MainWindow applies them live.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QHBoxLayout, QLabel,
                               QProgressBar, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget, QFrame)

LABEL_W = 150


class BuddyPage(QWidget):
    changed = Signal(dict)
    feed_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QVBoxLayout()
        head.setContentsMargins(26, 20, 26, 6)
        head.setSpacing(2)
        t = QLabel("Buddy")
        t.setObjectName("pageTitle")
        head.addWidget(t)
        s = QLabel("Your companion, your rules.")
        s.setObjectName("pageSub")
        head.addWidget(s)
        headwrap = QWidget()
        headwrap.setLayout(head)
        outer.addWidget(headwrap)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        center = QWidget()
        cl = QHBoxLayout(center)
        cl.setContentsMargins(0, 8, 0, 8)
        cl.addStretch()
        col = QVBoxLayout()
        col.setSpacing(14)
        colwrap = QWidget()
        colwrap.setLayout(col)
        colwrap.setMaximumWidth(700)
        cl.addWidget(colwrap, 1)
        cl.addStretch()
        scroll.setWidget(center)
        outer.addWidget(scroll, 1)

        # ---- status card ----
        card = self._section(col, "●", "Status", "How your buddy is doing.")
        self.mood_line = QLabel("…")
        self.mood_line.setStyleSheet("font-size:15px; font-weight:800; color:#F2F4FF;")
        card.addWidget(self.mood_line)
        self.hunger_bar = QProgressBar()
        self.hunger_bar.setRange(0, 100)
        self.hunger_bar.setMinimumHeight(14)
        self.hunger_bar.setTextVisible(False)
        self.hunger_bar.setStyleSheet(
            "QProgressBar { background:#0D1330; border:1px solid #26305A; border-radius:7px; }"
            "QProgressBar::chunk { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,"
            "stop:0 #7C5CFF, stop:1 #FBBF24); border-radius:6px; }")
        card.addWidget(self.hunger_bar)
        self.hunger_line = QLabel("")
        self.hunger_line.setStyleSheet("color:#8B93C9; font-size:12.5px;")
        card.addWidget(self.hunger_line)
        feed = QPushButton("Feed now")
        feed.setObjectName("primary")
        feed.setMinimumHeight(44)
        feed.setStyleSheet("border-radius:12px;")
        feed.clicked.connect(self.feed_requested.emit)
        card.addWidget(feed)

        # ---- look card ----
        look = self._section(col, "◐", "Look & behaviour", "Make it yours.")
        self.buddy_enabled = self._checkrow(
            look, "Show desktop buddy",
            "Walks the bottom of the screen. Click it to talk.")
        self.buddy_tray = self._checkrow(
            look, "Stay with buddy on close",
            "Closing hides the app — buddy keeps running in the tray.")
        row = self._row(look, "Buddy size")
        seg, self.buddy_size_grp, _ = self._segmented(look, ["Small", "Medium", "Large"])
        row.addLayout(seg, 1)
        row = self._row(look, "Bubble colour")
        bseg, self.bubble_grp, _ = self._segmented(look, ["Auto tint", "White", "Accent"])
        row.addLayout(bseg, 1)

        # any control change -> emit full buddy dict
        for grp in (self.buddy_size_grp, self.bubble_grp):
            grp.buttonClicked.connect(lambda _b=None: self._emit())
        self.buddy_enabled.toggled.connect(lambda _c=False: self._emit())
        self.buddy_tray.toggled.connect(lambda _c=False: self._emit())

    # ================= builders (compact copies of settings style) =================
    def _section(self, col: QVBoxLayout, icon: str, title: str, desc: str) -> QVBoxLayout:
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
        col.addWidget(card)
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

    def _segmented(self, parent, options: list[str]):
        row = QHBoxLayout()
        row.setSpacing(8)
        grp = QButtonGroup(parent)
        grp.setExclusive(True)
        btns = []
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

    # ================= data =================
    def _emit(self):
        self.changed.emit({
            "enabled": self.buddy_enabled.isChecked(),
            "tray": self.buddy_tray.isChecked(),
            "size": ["small", "medium", "large"][self.buddy_size_grp.checkedId()],
            "bubble": ["auto", "white", "accent"][self.bubble_grp.checkedId()],
        })

    def load_config(self, cfg) -> None:
        self.buddy_enabled.setChecked(bool(getattr(cfg.mascot, "enabled", True)))
        self.buddy_tray.setChecked(bool(getattr(cfg.mascot, "tray", True)))
        size_map = {"small": 0, "medium": 1, "large": 2}
        self.buddy_size_grp.button(size_map.get(cfg.mascot.size, 1)).setChecked(True)
        bub_map = {"auto": 0, "white": 1, "accent": 2}
        self.bubble_grp.button(bub_map.get(getattr(cfg.mascot, "bubble", "auto"), 0)).setChecked(True)

    def refresh(self, hunger: float = 0.0, mood: str = "IDLE") -> None:
        try:
            self.hunger_bar.setValue(int(max(0, min(100, hunger))))
        except Exception:
            pass
        faces = {"HUNGRY": "🍪 Hungry — feed me!", "SLEEPY": "😴 Sleepy",
                 "HAPPY": "😊 Happy", "ANGRY": "😠 Grumpy", "CRY": "😢 Sad",
                 "LAUGH": "🤣 Giggling", "LISTENING": "🎧 Listening",
                 "THINKING": "🤔 Thinking", "SPEAKING": "🗣 Speaking"}
        self.mood_line.setText(f"Feeling  {faces.get(mood, '🙂 Fine')}")
        if hunger >= 70:
            self.hunger_line.setText("Belly is rumbling… tap Feed now (or click buddy).")
        elif hunger >= 40:
            self.hunger_line.setText("Getting a little peckish.")
        else:
            self.hunger_line.setText("Full and happy.")
