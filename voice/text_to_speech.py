"""High-quality TTS via edge-tts + pygame playback (non-blocking stop).

Falls back to Windows SAPI (via PowerShell System.Speech) when offline
or when edge-tts is missing, so 'Speak' never crashes.
"""
from __future__ import annotations

import asyncio
import tempfile
import threading
import time
from pathlib import Path

# Popular edge voices for the Settings dropdown.
EDGE_VOICES = [
    ("en-US-AriaNeural", "English (US) - Aria (female)"),
    ("en-US-JennyNeural", "English (US) - Jenny (female)"),
    ("en-US-GuyNeural", "English (US) - Guy (male)"),
    ("en-US-DavisNeural", "English (US) - Davis (male)"),
    ("en-GB-SoniaNeural", "English (UK) - Sonia (female)"),
    ("en-GB-RyanNeural", "English (UK) - Ryan (male)"),
    ("en-IN-NeerjaNeural", "English (IN) - Neerja (female)"),
    ("en-IN-PrabhatNeural", "English (IN) - Prabhat (male)"),
    ("bn-BD-NabanitaNeural", "Bangla (BD) - Nabanita (female)"),
    ("bn-IN-TanishaaNeural", "Bangla (IN) - Tanishaa (female)"),
    ("hi-IN-SwaraNeural", "Hindi - Swara (female)"),
    ("hi-IN-MadhurNeural", "Hindi - Madhur (male)"),
]


class TextToSpeech:
    def __init__(self, voice="en-US-AriaNeural", rate="+0%", volume="+0%"):
        self.voice = voice
        self.rate = rate
        self.volume = volume
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.speaking = False
        self.last_error = ""

    # ---------- public ----------
    def configure(self, voice="", rate="", volume="") -> None:
        if voice:
            self.voice = voice
        if rate:
            self.rate = rate
        if volume:
            self.volume = volume

    def speak_blocking(self, text: str) -> None:
        text = (text or "").strip()
        if not text:
            return
        self._stop.clear()
        self.speaking = True
        try:
            if self._try_edge(text):
                return
            self._fallback_sapi(text)
        finally:
            self.speaking = False

    def speak_async(self, text: str) -> None:
        self.stop()
        self._thread = threading.Thread(target=self.speak_blocking, args=(text,), daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            import pygame
            if pygame.mixer.get_init():
                pygame.mixer.music.stop()
        except Exception:
            pass
        self.speaking = False

    # ---------- edge-tts ----------
    def _try_edge(self, text: str) -> bool:
        try:
            import edge_tts  # noqa
            import pygame
        except ImportError:
            self.last_error = "edge-tts/pygame not installed"
            return False
        tmp = Path(tempfile.gettempdir()) / f"nova_{int(time.time()*1000)}.mp3"
        try:
            asyncio.run(self._edge_save(text, str(tmp)))
            if self._stop.is_set():
                return True
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            pygame.mixer.music.load(str(tmp))
            pygame.mixer.music.play()
            while pygame.mixer.music.get_busy():
                if self._stop.is_set():
                    pygame.mixer.music.stop()
                    break
                time.sleep(0.05)
            return True
        except Exception as e:
            self.last_error = f"edge-tts failed ({e}); using offline voice."
            return False
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass

    async def _edge_save(self, text: str, out: str) -> None:
        import edge_tts
        comm = edge_tts.Communicate(self._humanize(text), voice=self.voice,
                                    rate=self.rate, volume=self.volume)
        await comm.save(out)

    def _humanize(self, text: str) -> str:
        """SSML breathing room: pauses after sentences/commas, slightly
        warmer prosody. Plain text passes through untouched when it
        already looks like SSML. edge-tts sends <speak> as SSML."""
        t = (text or "").strip()
        if not t or t.lstrip().startswith("<speak"):
            return t
        # escape XML specials outside tags (there are no tags here)
        t = (t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
        t = t.replace(". ", ".<break time='350ms'/> ")
        t = t.replace("! ", "!<break time='350ms'/> ")
        t = t.replace("? ", "?<break time='400ms'/> ")
        t = t.replace(", ", ",<break time='180ms'/> ")
        t = t.replace("। ", "।<break time='350ms'/> ")
        lang = "-".join((self.voice or "en-US").split("-")[:2])
        return (f"<speak version='1.0' xml:lang='{lang}'>"
                f"<prosody rate='medium' pitch='+2%'>{t}</prosody></speak>")

    # ---------- offline fallback: Windows SAPI via PowerShell ----------
    def _fallback_sapi(self, text: str) -> None:
        import subprocess
        safe = text.replace("'", "''")[:600]
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            f"$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            f"$s.Speak('{safe}');"
        )
        try:
            subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           timeout=60, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.last_error = f"Offline TTS failed: {e}"
