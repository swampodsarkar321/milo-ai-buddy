"""Microphone capture with simple energy-based VAD.

Uses `sounddevice` + `numpy`. Records until silence is detected
(or max seconds), then returns 16kHz mono int16 bytes for Whisper.
"""
from __future__ import annotations

import queue
import time

import numpy as np

SAMPLE_RATE = 16000
CHANNELS = 1


class MicrophoneError(RuntimeError):
    pass


def list_microphones() -> list[str]:
    try:
        import sounddevice as sd
        names = []
        for i, d in enumerate(sd.query_devices()):
            if d.get("max_input_channels", 0) > 0:
                names.append(f"{i}: {d['name']}")
        return names or ["default"]
    except Exception:
        return ["default (sounddevice missing)"]


class Listener:
    def __init__(self, device: int | None = None,
                 silence_ms: int = 900, max_seconds: int = 15,
                 energy_threshold: float = 0.008):
        self.device = device  # None = default
        self.silence_ms = silence_ms
        self.max_seconds = max_seconds
        self.energy_threshold = energy_threshold

    def record_utterance(self) -> bytes:
        """Block until one utterance is captured. Raises MicrophoneError."""
        try:
            import sounddevice as sd
        except ImportError as e:
            raise MicrophoneError("Microphone is unavailable right now.") from e

        q: queue.Queue = queue.Queue()
        block = int(SAMPLE_RATE * 0.1)  # 100ms blocks

        def cb(indata, frames, t, status):
            q.put(indata.copy())

        frames: list[np.ndarray] = []
        silent_since: float | None = None
        started = time.time()
        speech_started = False
        try:
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                                dtype="float32", device=self.device,
                                blocksize=block, callback=cb):
                while True:
                    try:
                        chunk = q.get(timeout=1.0)
                    except queue.Empty:
                        if time.time() - started > self.max_seconds + 5:
                            break
                        continue
                    frames.append(chunk)
                    rms = float(np.sqrt(np.mean(chunk ** 2)))
                    talking = rms > self.energy_threshold
                    if talking:
                        speech_started = True
                        silent_since = None
                    elif speech_started:
                        if silent_since is None:
                            silent_since = time.time()
                        elif (time.time() - silent_since) * 1000 > self.silence_ms:
                            break
                    if time.time() - started > self.max_seconds:
                        break
        except Exception as e:
            raise MicrophoneError(f"Microphone unavailable: {e}") from e

        if not frames or not speech_started:
            return b""
        audio = np.concatenate(frames, axis=0).flatten()
        audio = np.clip(audio, -1.0, 1.0)
        pcm16 = (audio * 32767).astype(np.int16)
        return pcm16.tobytes()

    @staticmethod
    def check_available() -> tuple[bool, str]:
        try:
            import sounddevice as sd
            devs = sd.query_devices()
            ok = any(d.get("max_input_channels", 0) > 0 for d in devs)
            return ok, "Microphone ready." if ok else "No input device found."
        except Exception as e:
            return False, f"Microphone check failed: {e}"
