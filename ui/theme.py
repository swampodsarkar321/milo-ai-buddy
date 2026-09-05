"""Premium theme: palette + global QSS (glass cards, gradients, polish).

Single source of truth for the product look. Pages keep small local
tweaks; everything structural lives here so rebranding = one file.
"""
from __future__ import annotations


ACCENT = "#7C5CFF"
ACCENT2 = "#38BDF8"

DARK = {
    "bg": "#070B16",
    "bg2": "#0C1226",
    "panel": "#111834",
    "panel2": "#161E3D",
    "card": "#131A36",
    "line": "#26305A",
    "line_soft": "#1C2447",
    "text": "#F2F4FF",
    "sub": "#A6AED6",
    "muted": "#626B9B",
    "accent": ACCENT,
    "accent2": ACCENT2,
    "good": "#34D399",
    "warn": "#FBBF24",
    "bad": "#F87171",
    "sidebar": "#0A0F22",
    "input": "#0D1330",
}

LIGHT = {
    "bg": "#EEF1FA",
    "bg2": "#E3E8F7",
    "panel": "#FFFFFF",
    "panel2": "#F4F6FD",
    "card": "#FFFFFF",
    "line": "#D5DBF0",
    "line_soft": "#E4E9F8",
    "text": "#141A33",
    "sub": "#4A5478",
    "muted": "#8B93B8",
    "accent": ACCENT,
    "accent2": "#0EA5E9",
    "good": "#059669",
    "warn": "#D97706",
    "bad": "#DC2626",
    "sidebar": "#E2E7F7",
    "input": "#FFFFFF",
}


def base_qss(theme: str = "dark", accent: str = ACCENT) -> str:
    """App-wide stylesheet. Inline page styles layer on top of this."""
    p = DARK if theme != "light" else LIGHT
    return f"""
* {{ font-family: "Segoe UI", "Nirmala UI", sans-serif; }}
QMainWindow, QWidget#central {{ background: {p['bg']}; }}
QWidget#leftbar {{ background: {p['sidebar']}; border-right: 1px solid {p['line_soft']}; }}
QLabel {{ color: {p['text']}; background: transparent; }}

/* ---------- sidebar ---------- */
QListWidget#sidebar {{
    background: transparent; border: none; color: {p['sub']};
    font-size: 14px; font-weight: 600; outline: none;
}}
QListWidget#sidebar::item {{
    padding: 11px 14px; margin: 2px 10px; border-radius: 12px;
    border-left: 3px solid transparent;
}}
QListWidget#sidebar::item:hover {{ background: {p['panel']}; color: {p['text']}; }}
QListWidget#sidebar::item:selected {{
    background: {p['panel2']}; color: {p['text']};
    border-left: 3px solid {accent};
}}

/* ---------- inputs ---------- */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{
    background: {p['input']}; color: {p['text']};
    border: 1px solid {p['line']}; border-radius: 12px;
    padding: 8px 12px; font-size: 13px; selection-background-color: {accent};
}}
QLineEdit:focus, QComboBox:focus {{ border: 1px solid {accent}; }}
QComboBox QAbstractItemView {{
    background: {p['panel']}; color: {p['text']};
    border: 1px solid {p['line']}; selection-background-color: {accent};
    outline: none;
}}

/* ---------- buttons ---------- */
QPushButton {{
    background: {p['panel2']}; color: {p['text']};
    border: 1px solid {p['line']}; border-radius: 12px;
    padding: 9px 18px; font-size: 13px; font-weight: 600;
}}
QPushButton:hover {{ border-color: {accent}; }}
QPushButton:pressed {{ background: {p['line_soft']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['panel']}; border-color: {p['line_soft']}; }}
QPushButton#primary {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1,
        stop:0 {accent}, stop:1 {p['accent2']});
    color: white; border: none; font-weight: 700;
}}
QPushButton#primary:hover {{ background: {accent}; }}
QPushButton#ghost {{ background: transparent; border: 1px solid {p['line']}; color: {p['sub']}; }}
QPushButton#danger {{ background: transparent; border: 1px solid {p['bad']}; color: {p['bad']}; }}

/* ---------- lists & tables ---------- */
QListWidget {{
    background: {p['input']}; color: {p['text']};
    border: 1px solid {p['line_soft']}; border-radius: 14px; padding: 8px;
    outline: none;
}}
QListWidget::item {{ padding: 9px 10px; border-radius: 9px; }}
QListWidget::item:selected {{ background: {p['panel2']}; color: {p['text']}; }}
QTableWidget {{
    background: {p['input']}; color: {p['text']};
    alternate-background-color: {p['panel']};
    gridline-color: {p['line_soft']}; border: 1px solid {p['line_soft']};
    border-radius: 14px; outline: none;
}}
QHeaderView::section {{
    background: {p['panel2']}; color: {p['sub']}; padding: 9px;
    border: none; font-weight: 700;
}}

/* ---------- scrollbars ---------- */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 4px 2px 4px 0;
}}
QScrollBar::handle:vertical {{
    background: {p['line']}; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {accent}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{
    background: transparent; height: 10px; margin: 0 4px 2px 4px;
}}
QScrollBar::handle:horizontal {{
    background: {p['line']}; border-radius: 5px; min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}
QScrollArea {{ border: none; background: transparent; }}
QScrollArea > QWidget {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}

/* ---------- groups, misc ---------- */
QGroupBox {{
    color: {p['text']}; font-weight: 700; font-size: 13px;
    border: 1px solid {p['line_soft']}; border-radius: 16px;
    margin-top: 14px; padding-top: 30px; background: {p['panel']};
}}
QGroupBox::title {{ subcontrol-origin: margin; left: 16px; padding: 0 8px; color: {p['sub']}; }}
QCheckBox {{ color: {p['sub']}; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px; border-radius: 6px;
    border: 1px solid {p['line']}; background: {p['input']};
}}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QSplitter::handle {{ background: {p['line_soft']}; }}
QSplitter::handle:horizontal {{ width: 2px; }}
QToolTip {{
    background: {p['panel2']}; color: {p['text']};
    border: 1px solid {p['line']}; padding: 6px;
}}
QLabel#eyebrow {{
    color: {p['muted']}; font-size: 11px; font-weight: 700; letter-spacing: 4px;
}}
QLabel#card {{
    background: {p['card']}; border: 1px solid {p['line_soft']};
    border-radius: 16px; padding: 14px;
}}
QLabel#pageTitle {{ font-size: 20px; font-weight: 800; }}
QLabel#pageSub {{ color: {p['sub']}; font-size: 12px; }}
"""


def grad_button(accent: str = ACCENT, accent2: str = ACCENT2) -> str:
    return (f"background: qlineargradient(x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 {accent}, stop:1 {accent2}); color: white; border: none;")


def app_icon():
    """Product icon (buddy face). Returns QIcon or None — never raises."""
    try:
        from pathlib import Path
        from PySide6.QtGui import QIcon
        for cand in (Path(__file__).resolve().parent.parent / "assets" / "icon.ico",
                     Path(__file__).resolve().parent.parent / "assets" / "icon.png"):
            if cand.exists():
                icon = QIcon(str(cand))
                if not icon.isNull():
                    return icon
    except Exception:
        pass
    return None
