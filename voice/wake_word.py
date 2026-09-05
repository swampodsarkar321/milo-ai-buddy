"""Wake-word detection (lightweight, no extra model download).

Strategy: record short 2s windows, transcribe with faster-whisper, and
check whether the wake phrase appears. This keeps the MVP
dependency-free (no openWakeWord / porcupine key).

Runs in a background thread; calls `on_wake` callback when detected.
"""
from __future__ import annotations

import threading
import time

import numpy as np


class WakeWordListener(threading.Thread):
    def __init__(self, wake_word="hey nova", on_wake=None, check_fn=None):
        super().__init__(daemon=True)
        self.wake_word = (wake_word or "hey nova").lower().strip()
        self.on_wake = on_wake
        self.check_fn = check_fn  # fn(pcm_bytes) -> transcribed text
        self._running = threading.Event()
        self.enabled = True

    def run(self):
        try:
            import sounddevice as sd
        except ImportError:
            return
        sr = 16000
        window = int(sr * 2.5)
        while self._running.is_set():
            if not self.enabled or not self.check_fn:
                time.sleep(0.3)
                continue
            try:
                rec = sd.rec(window, samplerate=sr, channels=1, dtype="float32")
                sd.wait()
                pcm = (np.clip(rec.flatten(), -1, 1) * 32767).astype(np.int16).tobytes()
                text = (self.check_fn(pcm) or "").lower()
                wants = [w for w in self.wake_word.split() if w]
                # match if all wake words appear OR "nova" alone appears
                if text and (all(w in text for w in wants) or "nova" in text):
                    if self.on_wake:
                        self.on_wake(text)
                    time.sleep(2.0)  # cooldown so we don't retrigger
            except Exception:
                time.sleep(0.5)

    def start_listening(self):
        self._running.set()
        if not self.is_alive():
            self.start()

    def stop_listening(self):
        self._running.clear()

    def set_wake_word(self, phrase: str):
        self.wake_word = (phrase or "hey nova").lower().strip()
