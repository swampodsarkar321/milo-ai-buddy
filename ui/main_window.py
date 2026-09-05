"""Main window: slim buddy-first shell (Home / Buddy / Settings / About)."""
from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QMessageBox,
                               QStackedWidget, QVBoxLayout, QWidget, QMainWindow)

from core.assistant import Assistant
from core.awareness import Awareness
from core.health import ScreenTime, fmt_dur, idle_seconds, today_stats
from core.state import AssistantState
from voice.listener import Listener
from voice.speech_to_text import SpeechToText
from voice.text_to_speech import TextToSpeech
from voice.wake_word import WakeWordListener

from .buddy import BuddyPage
from .home import HomePage
from .mascot import Mascot
from .settings import SettingsPage
from .theme import ACCENT, app_icon, base_qss


# ---------------- background workers (never freeze GUI) ----------------

class EngineWarmUpWorker(QThread):
    """Startup job, fully silent: refresh catalogue + speed-test top
    candidates and lock in the fastest working node. Emits best id."""
    done = Signal(str)     # best model id ("" when offline/all failed)
    failed = Signal(str)

    def __init__(self, model_manager, api_key="", base_url=""):
        super().__init__()
        self.model_manager = model_manager
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        try:
            best = self.model_manager.warm_up(self.api_key, self.base_url)
            self.done.emit(best or "")
        except Exception as e:
            self.failed.emit(str(e)[:200])


class PipelineWorker(QThread):
    transcript_ready = Signal(str)
    reply_ready = Signal(str, object, object, object)  # reply, tool, tool_result, mood_hint
    progress = Signal(str)  # e.g. "Trying nemotron-3-ultra... (2)"
    failed = Signal(str)

    def __init__(self, mode="voice", text="", listener=None, stt=None, assistant=None):
        super().__init__()
        self.mode = mode
        self.text = text
        self.listener = listener
        self.stt = stt
        self.assistant = assistant

    def run(self):
        try:
            if self.mode == "voice":
                pcm = self.listener.record_utterance()
                if not pcm:
                    self.failed.emit("I didn't hear anything. Try again.")
                    return
                try:
                    text = self.stt.transcribe_pcm16(pcm)
                except RuntimeError as e:
                    self.failed.emit(str(e))
                    return
                if not text.strip():
                    self.failed.emit("I couldn't understand that. Try again.")
                    return
                self.transcript_ready.emit(text)
            else:
                text = self.text

            def _on_try(mid: str, n: int):
                short = mid.split("/")[-1][:40]
                self.progress.emit(f"Trying {short}... ({n})")

            result = self.assistant.handle_text(text, on_model_try=_on_try)
            try:
                if Assistant.is_thanks(text):
                    result["mood_hint"] = "happy"
                elif Assistant.sense_mood(text):
                    result["mood_hint"] = "care"
            except Exception:
                pass
            self.reply_ready.emit(result["reply"], result.get("tool"),
                                  result.get("tool_result"), result.get("mood_hint"))
        except Exception as e:  # never crash the GUI
            self.failed.emit(f"Something went wrong: {e}")


# ---------------- main window ----------------

NAV_ICONS = ["◆", "●", "⚙", "ℹ"]


class MainWindow(QMainWindow):
    def __init__(self, config, db):
        super().__init__()
        self.config = config
        self.db = db
        self.brand = config.brand.app_name
        self.setWindowTitle(f"{self.brand} - Voice Partner")
        try:
            _icon = app_icon()
            if _icon is not None:
                self.setWindowIcon(_icon)
        except Exception:
            pass
        self.resize(1080, 720)

        # --- services ---
        self.assistant = Assistant(config, db)
        self.aware = Awareness()  # proactive buddy watchers (bubble alerts)
        try:
            self.aware.db = db  # enables mood follow-ups (same SQLite)
        except Exception:
            pass
        self.screen = ScreenTime(
            db,
            break_minutes=int(getattr(config.health, "break_minutes", 60) or 60),
            enabled=bool(getattr(config.health, "enabled", True)))
        mic_idx = config.voice.microphone_index
        self.listener = Listener(device=None if mic_idx is None or mic_idx < 0 else mic_idx)
        self.stt = SpeechToText(model_size=config.voice.stt_model,
                                language=config.voice.language)
        self.tts = TextToSpeech(voice=config.voice.tts_voice,
                                rate=config.voice.rate, volume=config.voice.volume)
        self.worker: PipelineWorker | None = None
        self.mascot: Mascot | None = None

        # --- layout ---
        central = QWidget()
        central.setObjectName("central")
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.pages_names = ["Home", "Buddy", "Settings", "About"]
        for icon, n in zip(NAV_ICONS, self.pages_names):
            self.sidebar.addItem(f"  {icon}   {n}")
        self.sidebar.setCurrentRow(0)
        self.sidebar.currentRowChanged.connect(self._switch_page)

        # premium left rail: brand mark + nav + version footer
        leftbar = QWidget()
        leftbar.setObjectName("leftbar")
        leftbar.setFixedWidth(216)
        left_lay = QVBoxLayout(leftbar)
        left_lay.setContentsMargins(6, 18, 6, 14)
        left_lay.setSpacing(6)
        mark = QLabel("◆")
        mark.setAlignment(Qt.AlignCenter)
        mark.setStyleSheet(
            f"font-size:26px; color:{ACCENT}; background:transparent;")
        left_lay.addWidget(mark)
        brand_lbl = QLabel(self.brand.upper())
        brand_lbl.setAlignment(Qt.AlignCenter)
        brand_lbl.setStyleSheet(
            "font-size:15px; font-weight:800; letter-spacing:5px; background:transparent;")
        left_lay.addWidget(brand_lbl)
        ver = QLabel("v1.0")
        ver.setAlignment(Qt.AlignCenter)
        ver.setStyleSheet("font-size:10px; color:#626B9B; background:transparent;")
        left_lay.addWidget(ver)
        left_lay.addSpacing(10)
        left_lay.addWidget(self.sidebar, 1)
        foot = QLabel("● Engine ready")
        foot.setObjectName("engineFoot")
        foot.setAlignment(Qt.AlignCenter)
        foot.setStyleSheet("font-size:11px; color:#34D399; background:transparent;")
        left_lay.addWidget(foot)
        self.engine_foot = foot
        root.addWidget(leftbar)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        self.status = QLabel("Starting…")
        self.status.setObjectName("statusbar")
        self.status.setStyleSheet(
            "color:#626B9B; padding:10px 22px; font-size:11.5px;"
            "border-top: 1px solid #1C2447; background: transparent;")
        self.stack = QStackedWidget()

        self.home = HomePage(accent=config.appearance.accent,
                              app_name=self.brand,
                              tagline=config.brand.tagline)
        self.home.mic_pressed.connect(self.start_voice)
        self.home.stop_pressed.connect(self.stop_speaking)
        self.home.text_sent.connect(lambda t: self.submit_text(t))
        self.home.quick_requested.connect(lambda c: self.submit_text(c))

        self.buddy_page = BuddyPage()
        self.buddy_page.changed.connect(self._on_buddy_changed)
        self.buddy_page.feed_requested.connect(self._feed_buddy)

        self.settings_page = SettingsPage()
        self.settings_page.save_requested.connect(self.save_settings)
        self.settings_page.test_voice_requested.connect(
            lambda: self.tts.speak_async(f"Hello! I am {self.config.personality.name}."))

        self.about_page = QLabel(
            f"<div style='text-align:center'>"
            f"<div style='font-size:52px; color:#7C5CFF'>◆</div>"
            f"<h1 style='color:#F2F4FF; letter-spacing:6px; margin:6px'>{self.brand.upper()}</h1>"
            f"<p style='color:#A6AED6; font-size:14px'>{config.brand.tagline}</p>"
            "<p style='color:#626B9B; font-size:12px'>Talk naturally — I listen, "
            "remember, and help with your daily tasks.<br>Version 1.0<br>"
            "Tip: press Ctrl+Alt+B anywhere to talk.</p></div>")
        self.about_page.setAlignment(Qt.AlignCenter)
        self.about_page.setWordWrap(True)

        for w in (self.home, self.buddy_page,
                  self.settings_page, self.about_page):
            self.stack.addWidget(w)

        right.addWidget(self.stack, 1)
        right.addWidget(self.status)
        root.addLayout(right, 1)

        self.apply_theme()
        self.settings_page.load_config(config)
        self.buddy_page.load_config(config)
        self.refresh_feed()

        # --- background: engine warm-up (silent best-node probe) ---
        self._model_worker: EngineWarmUpWorker | None = None
        if self.assistant.llm.configured:
            QTimer.singleShot(1500, self.refresh_models)

        # --- startup sequence (generic, no technical detail) ---
        self._startup_steps = [
            "Loading...", "Preparing memory...",
            "Starting engine...",
            "Checking microphone...",
        ]
        ok, _mic_msg = Listener.check_available()
        self._startup_steps.append(
            "Microphone ready." if ok else "Microphone unavailable.")
        self._startup_steps.append("Ready.")
        self._step_idx = 0
        self._startup_timer = QTimer(self)
        self._startup_timer.timeout.connect(self._next_startup_step)
        self._startup_timer.start(450)

        # --- reminder checker ---
        self._rem_timer = QTimer(self)
        self._rem_timer.timeout.connect(self.check_reminders)
        self._rem_timer.start(15000)
        QTimer.singleShot(4000, self.check_reminders)

        # --- awareness poll (battery / time / downloads / gmail) ---
        self._aware_busy = False
        self._aware_tick_n = 0
        self._aware_timer = QTimer(self)
        self._aware_timer.timeout.connect(self._aware_tick)
        self._aware_timer.start(60000)
        QTimer.singleShot(20000, self._aware_tick)  # first sweep shortly after launch

        # --- routine nudges (learned habits, bubble suggestion) ---
        self._routine_timer = QTimer(self)
        self._routine_timer.timeout.connect(self._routine_tick)
        self._routine_timer.start(600000)
        QTimer.singleShot(120000, self._routine_tick)

        # --- screen-time health guard (local, 60s steps) ---
        self._health_timer = QTimer(self)
        self._health_timer.timeout.connect(self._health_tick)
        self._health_timer.start(60000)

        # --- buddy small-talk (time-aware idle chatter, bubble only) ---
        self._chat_timer = QTimer(self)
        self._chat_timer.timeout.connect(self._chitchat_tick)
        self._chat_timer.start(1200000)

        # --- wake word ---
        self.wake = WakeWordListener(wake_word=config.voice.wake_word,
                                     on_wake=self._on_wake,
                                     check_fn=self._wake_transcribe)
        if config.voice.wake_word_enabled and not config.voice.push_to_talk:
            self.wake.start_listening()
        self._set_state(AssistantState.IDLE)
        self._set_engine_foot(bool(self.assistant.llm.configured))

        # --- desktop buddy (roams the screen, reacts to voice states) ---
        self.mascot = None
        if getattr(config.mascot, "enabled", True):
            self._spawn_mascot()
        # buddy-first hello shortly after launch
        QTimer.singleShot(6000, self._buddy_hello)

        # --- tray: closing hides to buddy, app keeps running ---
        self._quitting = False
        self.tray = None
        try:
            from PySide6.QtWidgets import QSystemTrayIcon, QMenu
            from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
            if QSystemTrayIcon.isSystemTrayAvailable():
                tray_icon = app_icon()
                if tray_icon is None:
                    pm = QPixmap(64, 64)
                    pm.fill(Qt.transparent)
                    pt = QPainter(pm)
                    pt.setRenderHint(QPainter.Antialiasing)
                    pt.setBrush(QColor(self.config.appearance.accent or ACCENT))
                    pt.setPen(Qt.NoPen)
                    pt.drawEllipse(4, 4, 56, 56)
                    f = QFont("Segoe UI", 34)
                    f.setBold(True)
                    pt.setFont(f)
                    pt.setPen(QColor("white"))
                    pt.drawText(pm.rect(), Qt.AlignCenter,
                                (self.brand[:1] or "N").upper())
                    pt.end()
                    from PySide6.QtGui import QIcon as _QIcon
                    tray_icon = _QIcon(pm)
                self.tray = QSystemTrayIcon(tray_icon, self)
                self.tray.setToolTip(f"{self.brand} — running with your buddy")
                menu = QMenu()
                show_a = menu.addAction(f"Show {self.brand}")
                show_a.triggered.connect(self._tray_show)
                talk_a = menu.addAction("Talk now")
                talk_a.triggered.connect(self._tray_talk)
                menu.addSeparator()
                quit_a = menu.addAction("Quit")
                quit_a.triggered.connect(self._tray_quit)
                self.tray.setContextMenu(menu)
                self.tray.activated.connect(self._tray_activated)
                self.tray.show()
        except Exception:
            self.tray = None
        try:
            from PySide6.QtWidgets import QApplication as _QA
            _inst = _QA.instance()
            # with tray: closing the window must NOT quit (buddy stays);
            # without tray: normal quit-on-close behaviour.
            if _inst is not None:
                _inst.setQuitOnLastWindowClosed(self.tray is None)
        except Exception:
            pass

        # --- global hotkey: Ctrl+Alt+B talks from anywhere (Windows) ---
        self._hotkey_id = 7
        self._hotkey_ok = False
        try:
            import sys as _sys
            if _sys.platform == "win32":
                import ctypes
                _user32 = ctypes.windll.user32
                MOD_CONTROL, MOD_ALT, VK_B = 0x0002, 0x0001, 0x42
                self._hotkey_ok = bool(_user32.RegisterHotKey(
                    int(self.winId()), self._hotkey_id,
                    MOD_CONTROL | MOD_ALT, VK_B))
        except Exception:
            self._hotkey_ok = False

    def nativeEvent(self, eventType, message):
        # WM_HOTKEY -> talk (works even when the window is hidden)
        try:
            if bytes(eventType) == b"windows_generic_MSG":
                import ctypes
                from ctypes import wintypes
                msg = ctypes.cast(int(message),
                                  ctypes.POINTER(wintypes.MSG)).contents
                if msg.message == 0x0312 and msg.wParam == getattr(self, "_hotkey_id", -1):
                    QTimer.singleShot(0, self._mascot_talk_now)
                    return True, 0
        except Exception:
            pass
        try:
            return super().nativeEvent(eventType, message)
        except Exception:
            return False, 0

    # ---------- state / status ----------
    def _set_state(self, state: AssistantState | str):
        s = str(state.value if isinstance(state, AssistantState) else state)
        self.home.set_state(s)
        self._state = s
        try:
            if self.mascot:
                self.mascot.set_app_mood(s)
        except Exception:
            pass

    # ---------- desktop buddy ----------
    def _spawn_mascot(self):
        """Classic painted buddy (the one and only). Never raises."""
        try:
            if self.mascot:
                self.mascot.close()
                self.mascot = None
        except Exception:
            pass
        try:
            self.mascot = Mascot(accent=self.config.appearance.accent or ACCENT,
                                 size_name=getattr(self.config.mascot, "size", "medium"))
        except Exception:
            self.mascot = None
            return
        try:
            self.mascot.clicked.connect(self._on_mascot_clicked)
            self.mascot.talk_requested.connect(self._mascot_talk_now)
            self.mascot.command_requested.connect(lambda c: self.submit_text(c))
            self.mascot.file_dropped.connect(self._read_dropped)
            self.mascot.show_requested.connect(self._tray_show)
            self.mascot.quit_requested.connect(self._tray_quit)
            self.mascot.set_app_mood(getattr(self, "_state", "IDLE"))
            self.mascot.set_bubble_style(getattr(self.config.mascot, "bubble", "auto"),
                                         self.config.appearance.accent or ACCENT)
            self.mascot.show()
        except Exception:
            self.mascot = None

    def _mascot_talk_now(self):
        """Buddy menu / hotkey: talk right now (window stays as-is)."""
        if self._busy():
            try:
                if self.mascot:
                    self.mascot.say("One sec…")
            except Exception:
                pass
            return
        self.start_voice()

    def _read_dropped(self, path: str):
        """Drop a .txt file on the buddy -> it reads aloud."""
        import os as _os
        name = _os.path.basename(path or "")
        ext = _os.path.splitext(name)[1].lower()
        if ext not in (".txt", ".md", ".log"):
            try:
                if self.mascot:
                    self.mascot.say("I can only read text files (for now).")
            except Exception:
                pass
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                text = f.read(900).strip()
        except Exception:
            text = ""
        if not text:
            try:
                if self.mascot:
                    self.mascot.say("That file seems empty.")
            except Exception:
                pass
            return
        try:
            if self.mascot:
                self.mascot.say(f"Reading {name[:40]}…")
                self.mascot.set_app_mood("SPEAKING")
        except Exception:
            pass
        self.tts.speak_async(text)

    def _on_mascot_clicked(self):
        # Buddy-first UX: a tap means "talk to me" (feed/angry taps are
        # already consumed inside the mascot and never reach here).
        if self._busy():
            try:
                if self.mascot:
                    self.mascot.say("One sec…")
            except Exception:
                pass
            return
        try:
            self.show()
            self.raise_()
        except Exception:
            pass
        self.start_voice()

    @staticmethod
    def _short_bubble(text: str, limit: int = 140) -> str:
        """First sentence, capped — replies readable above the buddy."""
        t = (text or "").strip().replace("\n", " ")
        for sep in (". ", "! ", "? ", "। "):
            if sep in t:
                t = t.split(sep)[0] + sep.strip()
                break
        return t if len(t) <= limit else t[: limit - 1].rstrip() + "…"

    def _feed_buddy(self):
        try:
            if self.mascot:
                self.mascot.feed()
        except Exception:
            pass

    def _apply_mascot_prefs(self):
        want = bool(getattr(self.config.mascot, "enabled", True))
        if want and not self.mascot:
            self._spawn_mascot()
        elif not want and self.mascot:
            try:
                self.mascot.close()
            finally:
                self.mascot = None
        if self.mascot:
            try:
                self.mascot.set_accent(self.config.appearance.accent or ACCENT)
            except Exception:
                pass
            try:
                self.mascot.set_bubble_style(getattr(self.config.mascot, "bubble", "auto"),
                                             self.config.appearance.accent or ACCENT)
            except Exception:
                pass
            self.mascot.set_size_name(getattr(self.config.mascot, "size", "medium"))

    def _on_buddy_changed(self, data: dict):
        """Buddy page changes: persist + apply instantly (no Save needed)."""
        try:
            for k in ("enabled", "tray", "size", "bubble"):
                if k in data:
                    setattr(self.config.mascot, k, data[k])
            if isinstance(data.get("health"), dict):
                h = data["health"]
                if "enabled" in h:
                    self.config.health.enabled = bool(h["enabled"])
                if "break_minutes" in h:
                    try:
                        self.config.health.break_minutes = int(h["break_minutes"])
                    except Exception:
                        pass
            self.config.save()
        except Exception:
            pass
        try:
            self.screen.enabled = bool(getattr(self.config.health, "enabled", True))
            self.screen.break_minutes = int(
                getattr(self.config.health, "break_minutes", 60) or 60)
        except Exception:
            pass
        self._apply_mascot_prefs()
        self._refresh_buddy()

    def _tray_show(self):
        try:
            self.show()
            self.raise_()
            self.activateWindow()
        except Exception:
            pass

    def _tray_talk(self):
        self._tray_show()
        if not self._busy():
            self.start_voice()

    def _tray_quit(self):
        self._quitting = True
        self.close()

    def _tray_activated(self, reason):
        try:
            from PySide6.QtWidgets import QSystemTrayIcon
            if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
                self._tray_show()
        except Exception:
            pass

    def _buddy_hello(self):
        try:
            if self.mascot and self.mascot.isVisible():
                try:
                    who = self.assistant.get_user_name()
                except Exception:
                    who = ""
                self.mascot.say(
                    f"Hey {who}! Click me and just talk." if who
                    else "Hey! Click me and just talk.")
        except Exception:
            pass

    def _say_status(self, msg: str):
        self.status.setText(f"{datetime.now().strftime('%H:%M:%S')}  -  {msg}")

    def _next_startup_step(self):
        if self._step_idx < len(self._startup_steps):
            self._say_status(self._startup_steps[self._step_idx])
            self._step_idx += 1
        else:
            self._startup_timer.stop()

    def _switch_page(self, i: int):
        self.stack.setCurrentIndex(i)
        if self.pages_names[i] == "Home":
            self.refresh_feed()
        elif self.pages_names[i] == "Buddy":
            self._refresh_buddy()
        elif self.pages_names[i] == "Settings":
            self.settings_page.load_config(self.config)

    def _refresh_buddy(self):
        """Push live buddy state (hunger/mood/health) into the Buddy page."""
        try:
            hunger, mood = 0.0, "IDLE"
            if self.mascot:
                hunger = float(getattr(self.mascot, "hunger", 0.0) or 0.0)
                mood = getattr(self.mascot, "mood", "IDLE") or "IDLE"
            try:
                s, b = today_stats(self.db)
                health_line = f"Today: {fmt_dur(s)} screen time • {b} breaks"
            except Exception:
                health_line = ""
            self.buddy_page.refresh(hunger, mood, health_line)
        except Exception:
            pass

    # ---------- screen-time health tick (fast local work, GUI thread OK) ----------
    def _health_tick(self):
        try:
            msg = self.screen.tick()
        except Exception:
            msg = None
        if msg and self.mascot:
            try:
                self.mascot.say(msg[:160], ms=8000)
                try:
                    if self.mascot.jump_v == 0 and self.mascot.jump_y == 0:
                        self.mascot.jump_v = -5.0
                except Exception:
                    pass
            except Exception:
                pass

    def _chitchat_tick(self):
        try:
            if not self.mascot or self._busy():
                return
            try:
                idle = idle_seconds()
            except Exception:
                idle = None
            self.mascot.chitchat(idle)
        except Exception:
            pass

    # ---------- Alexa-style activity feed ----------
    def refresh_feed(self):
        from datetime import datetime as _dt
        try:
            now = _dt.now()
            hour = now.hour
            day = ("morning" if hour < 12 else "afternoon" if hour < 17
                   else "evening" if hour < 21 else "night")
            try:
                who = self.assistant.get_user_name()
            except Exception:
                who = ""
            hello = f"Good {day}" + (f", {who} 👋" if who else " 👋")
            feed = {
                "greeting": hello,
                "dateline": now.strftime("%A, %B %d  •  %I:%M %p"),
                "reminders": [],
                "memories": [],
                "recent": [],
            }
            try:
                for r in self.assistant.reminders.upcoming(10)[:3]:
                    feed["reminders"].append({
                        "text": r["text"],
                        "when": _dt.fromtimestamp(r["due_at"]).strftime("%b %d, %I:%M %p")})
            except Exception:
                pass
            try:
                for m in self.assistant.memory.all_memories(10)[:3]:
                    feed["memories"].append(
                        {"value": m.get("value", ""), "category": m.get("category", "")})
            except Exception:
                pass
            try:
                for t in self.assistant.conversation.all()[-4:]:
                    feed["recent"].append(
                        ("YOU" if t.role == "user" else "NOVA", t.text))
            except Exception:
                pass
            self.home.refresh(feed)
        except Exception:
            pass

    def apply_theme(self):
        self.setStyleSheet(base_qss(self.config.appearance.theme,
                                    self.config.appearance.accent or ACCENT))

    # ---------- voice pipeline ----------
    def _busy(self) -> bool:
        return self.worker is not None and self.worker.isRunning()

    def start_voice(self):
        if self._busy():
            return
        self.tts.stop()
        self._set_state(AssistantState.LISTENING)
        self.home.show_transcript("Listening... speak now.")
        self._say_status("Listening...")
        if self.wake:
            self.wake.enabled = False
        self.worker = PipelineWorker(mode="voice", listener=self.listener,
                                     stt=self.stt, assistant=self.assistant)
        self.worker.transcript_ready.connect(
            lambda t: (self.home.show_transcript(t),
                       self._set_state(AssistantState.THINKING),
                       self._say_status("Thinking...")))
        self.worker.reply_ready.connect(self._on_reply)
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_fail)
        self.worker.finished.connect(self._worker_done)
        self.worker.start()

    def submit_text(self, text: str):
        if self._busy() or not text.strip():
            return
        self.tts.stop()
        self._set_state(AssistantState.THINKING)
        self.home.show_transcript(text)
        self._say_status("Thinking...")
        if self.wake:
            self.wake.enabled = False
        self.worker = PipelineWorker(mode="text", text=text, assistant=self.assistant)
        self.worker.reply_ready.connect(self._on_reply)
        self.worker.progress.connect(self._on_progress)
        self.worker.failed.connect(self._on_fail)
        self.worker.finished.connect(self._worker_done)
        self.worker.start()

    def _on_progress(self, msg: str):
        # live auto-switch feedback — generic wording, no model names.
        self._say_status("Thinking...")

    def _on_reply(self, reply: str, tool, tool_result, mood_hint=None):
        self.home.show_response(reply)
        try:
            self.refresh_feed()
        except Exception:
            pass
        # countdown timers execute here (assistant only returns the marker)
        try:
            tr = tool_result or {}
            if tool == "create_timer" and tr.get("timer_seconds"):
                self._start_timer(int(tr["timer_seconds"]),
                                  str(tr.get("timer_label", "Timer")))
            elif tool == "cancel_timer" or (isinstance(tr, dict) and tr.get("cancel_timer")):
                self._cancel_timers()
        except Exception:
            pass
        # buddy-first: the answer also pops above the buddy
        try:
            if self.mascot:
                self.mascot.say(self._short_bubble(reply), ms=5000)
        except Exception:
            pass
        # sentiment reaction: thanks -> cheerful bounce (bubble stays)
        try:
            if mood_hint == "happy" and self.mascot:
                self.mascot.cheer()
            elif mood_hint == "care" and self.mascot:
                self.mascot.care()
        except Exception:
            pass
        self._say_status("Speaking...")
        self._set_state(AssistantState.SPEAKING)
        self.tts.speak_async(reply)
        # return to idle after estimated speech time (non-blocking)
        words = max(1, len(reply.split()))
        QTimer.singleShot(min(12000, 1500 + words * 380), self._back_to_idle)

    def _back_to_idle(self):
        if not self.tts.speaking and not self._busy():
            self._set_state(AssistantState.IDLE)
            self._say_status("Ready.")

    def _on_fail(self, msg: str):
        self.home.show_response(msg)
        self._set_state(AssistantState.ERROR)
        self._say_status(msg)
        try:
            if self.mascot:
                self.mascot.cry()
        except Exception:
            pass
        self.tts.speak_async(msg)
        QTimer.singleShot(2500, lambda: self._set_state(AssistantState.IDLE))

    def _worker_done(self):
        if self.wake and self.config.voice.wake_word_enabled \
                and not self.config.voice.push_to_talk:
            self.wake.enabled = True

    def stop_speaking(self):
        self.tts.stop()
        self._set_state(AssistantState.IDLE)
        self._say_status("Stopped.")

    # ---------- wake word ----------
    def _wake_transcribe(self, pcm: bytes) -> str:
        try:
            # reuse STT but never let wake errors surface
            if self._busy():
                return ""
            return self.stt.transcribe_pcm16(pcm)
        except Exception:
            return ""

    def _on_wake(self, heard: str):
        # called from wake thread -> hop to GUI thread
        try:
            if self.mascot:
                self.mascot.surprise()
        except Exception:
            pass
        QTimer.singleShot(0, lambda: (
            self._say_status("Wake word heard - listening..."),
            self.start_voice()))

    # ---------- engine warm-up (fully silent, background) ----------
    def refresh_models(self):
        """Startup best-node probe. Never shows anything technical."""
        if self._model_worker is not None and self._model_worker.isRunning():
            return
        if not self.assistant.llm.configured:
            return  # offline — nothing to warm up, no message needed
        self._model_worker = EngineWarmUpWorker(
            self.assistant.models,
            self.assistant.llm.api_key,
            self.assistant.llm.base_url)
        self._model_worker.done.connect(self._on_models)
        self._model_worker.failed.connect(self._on_models_error)
        self._model_worker.start()

    def _on_models(self, best: str):
        # silent success: lock in the probed best node for this session
        if best:
            self.assistant.llm.model = best
            self.config.ai.model = best
        self.settings_page.set_engine_status(True)
        self._set_engine_foot(True)
        if self._state == "IDLE":
            self._say_status("Ready.")

    def _on_models_error(self, msg: str):
        # silent: engine keeps working with the cached list
        self.settings_page.set_engine_status(
            bool(self.assistant.llm.configured))
        self._set_engine_foot(bool(self.assistant.llm.configured))

    def _set_engine_foot(self, ok: bool) -> None:
        try:
            if ok:
                self.engine_foot.setText("● Engine ready")
                self.engine_foot.setStyleSheet(
                    "font-size:11px; color:#34D399; background:transparent;")
            else:
                self.engine_foot.setText("● Offline")
                self.engine_foot.setStyleSheet(
                    "font-size:11px; color:#FBBF24; background:transparent;")
        except Exception:
            pass

    # ---------- conversation ----------
    def clear_conversation(self):
        self.assistant.conversation.clear()
        self.assistant.conv_memory.clear()
        self.home.show_transcript("")
        self.home.show_response("")
        self.refresh_feed()
        self._say_status("Conversation cleared.")

    # ---------- memories (voice-driven; Home feed shows highlights) ----------
    def refresh_memories(self):
        try:
            self.refresh_feed()
        except Exception:
            pass

    def clear_memories(self):
        self.assistant.memory.clear_all()
        self.refresh_memories()

    # ---------- reminders (voice-driven; Home feed shows upcoming) ----------
    def refresh_reminders(self):
        try:
            self.refresh_feed()
        except Exception:
            pass

    def check_reminders(self):
        try:
            due = self.assistant.reminders.due()
        except Exception:
            due = []
        try:
            due += self.assistant.reminders.due_schedules()
        except Exception:
            pass
        for r in due:
            self.assistant.reminders.mark_done(r["id"])
            msg = f"Reminder: {r['text']}"
            self.home.show_response(msg)
            self._say_status(msg)
            try:
                if self.mascot:
                    self.mascot.say(msg)
            except Exception:
                pass
            if self.config.privacy.speak_reminders:
                self.tts.speak_async(msg)
        if due:
            self.refresh_reminders()

    # ---------- countdown timers (buddy announces at zero) ----------
    def _start_timer(self, seconds: int, label: str):
        if not hasattr(self, "_timers"):
            self._timers = {}
            self._timer_n = 0
        self._timer_n += 1
        tid = self._timer_n
        t = QTimer(self)
        t.setSingleShot(True)
        t.timeout.connect(lambda _tid=tid: self._timer_done(_tid))
        self._timers[tid] = (t, label)
        t.start(max(1000, seconds * 1000))
        self._say_status(f"Timer '{label}' running.")

    def _cancel_timers(self):
        for _tid, (t, _label) in list(getattr(self, "_timers", {}).items()):
            try:
                t.stop()
            except Exception:
                pass
        self._timers = {}

    def _timer_done(self, tid: int):
        label = "Timer"
        try:
            _t, label = self._timers.pop(tid, (None, "Timer"))
        except Exception:
            pass
        msg = f"Time's up! {label} finished."
        self.home.show_response(f"⏰ {msg}")
        self._say_status(msg)
        try:
            if self.mascot:
                self.mascot.say(msg)
                try:
                    self.mascot.poke()
                except Exception:
                    pass
        except Exception:
            pass
        self.tts.speak_async(msg)

    # ---------- buddy awareness (background poll -> bubble) ----------
    def _aware_tick(self):
        if self._aware_busy:
            return
        self._aware_busy = True
        import threading

        def _poll():
            msgs: list[str] = []
            hot: str | None = None
            try:
                for fn in (self.aware.check_battery, self.aware.check_time,
                           self.aware.check_downloads, self.aware.check_mood_followup):
                    try:
                        m = fn()
                    except Exception:
                        m = None
                    if m:
                        msgs.append(m)
                try:
                    hot = self.aware.check_system_load()
                except Exception:
                    hot = None
                self._aware_tick_n += 1
                if self._aware_tick_n % 3 == 0:  # gmail: every ~3 min, gentle
                    try:
                        for subj in self.aware.check_mail():
                            msgs.append(f"New mail — {subj}")
                    except Exception:
                        pass
            finally:
                self._aware_busy = False
            if hot:
                QTimer.singleShot(0, lambda h=hot: self._show_hot(h))
            if msgs:
                QTimer.singleShot(0, lambda ms=msgs: self._show_aware(ms))

        threading.Thread(target=_poll, daemon=True).start()

    def _show_hot(self, msg: str):
        try:
            if self.mascot:
                self.mascot.hot_flash(msg[:160])
        except Exception:
            pass

    def _show_aware(self, msgs: list[str]):
        try:
            if not self.mascot:
                return
            text = msgs[0] if len(msgs) == 1 else " • ".join(msgs[:2])
            self.mascot.say(text[:160], ms=6000)
            try:
                if self.mascot.jump_v == 0 and self.mascot.jump_y == 0:
                    self.mascot.jump_v = -5.0  # little hop for attention
            except Exception:
                pass
        except Exception:
            pass

    # ---------- routine nudge (SQLite queries are instant; GUI thread OK) ----------
    def _routine_tick(self):
        try:
            sug = self.assistant.routines.should_suggest()
        except Exception:
            return
        if not sug or not self.mascot:
            return
        try:
            self.mascot.say(sug["say"][:160], ms=7000)
            try:
                if self.mascot.jump_v == 0 and self.mascot.jump_y == 0:
                    self.mascot.jump_v = -5.0
            except Exception:
                pass
        except Exception:
            pass

    # ---------- settings ----------
    def save_settings(self, data: dict):
        try:
            if data.get("__clear_chat__"):
                self.clear_conversation()
                return
            if data.get("__clear_mem__"):
                self.clear_memories()
                return
            for section, values in data.items():
                if hasattr(self.config, section):
                    self.config.update_section(section, values)
            # push to live services
            self.assistant.reload_config(self.config)
            mic_idx = self.config.voice.microphone_index
            self.listener.device = None if mic_idx < 0 else mic_idx
            self.tts.configure(voice=self.config.voice.tts_voice,
                               rate=self.config.voice.rate)
            self.stt.model_size = self.config.voice.stt_model
            self.stt.language = self.config.voice.language
            self.setWindowTitle(f"{self.config.brand.app_name} - Voice Partner")
            self.apply_theme()
            self._apply_mascot_prefs()
            # wake word rewire
            if self.wake:
                self.wake.set_wake_word(self.config.voice.wake_word)
                want = self.config.voice.wake_word_enabled and not self.config.voice.push_to_talk
                if want and not self.wake.is_alive():
                    self.wake.start_listening()
                self.wake.enabled = want
            self._say_status("Settings saved.")
        except Exception:
            QMessageBox.warning(self, "Settings", "Could not save settings.")

    def closeEvent(self, event):
        # buddy-first: X hides the window, buddy + tray keep running
        try:
            if (not self._quitting and self.tray is not None
                    and bool(getattr(self.config.mascot, "tray", True))):
                event.ignore()
                self.hide()
                try:
                    if self.mascot:
                        self.mascot.say("I'm still here — click me to talk!")
                except Exception:
                    pass
                try:
                    self.tray.showMessage(
                        self.brand, "Minimized — your buddy is still here.",
                        self.tray.NoIcon if hasattr(self.tray, "NoIcon") else 0, 2500)
                except Exception:
                    pass
                return
        except Exception:
            pass
        try:
            if self.wake:
                self.wake.stop_listening()
            self.tts.stop()
            if self.mascot:
                self.mascot.close()
            if self.tray:
                self.tray.hide()
            try:
                import sys as _sys
                if _sys.platform == "win32" and getattr(self, "_hotkey_ok", False):
                    import ctypes
                    ctypes.windll.user32.UnregisterHotKey(
                        int(self.winId()), getattr(self, "_hotkey_id", 7))
            except Exception:
                pass
        finally:
            event.accept()
