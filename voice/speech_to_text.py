"""Speech-to-Text via faster-whisper (lazy-loaded, background friendly)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


class SpeechToText:
    def __init__(self, model_size: str = "small", language: str = "en"):
        self.model_size = model_size
        self.language = language
        self._model = None
        self.last_error = ""

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError("Speech recognition is unavailable right now.") from e
        # int8 = fast + low RAM on CPU; first run downloads the model.
        self._model = WhisperModel(self.model_size, device="cpu", compute_type="int8")
        return self._model

    def transcribe_pcm16(self, pcm: bytes) -> str:
        """Transcribe raw 16kHz mono int16 PCM bytes -> text."""
        if not pcm:
            return ""
        try:
            model = self._ensure_model()
            audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
            segments, _ = model.transcribe(audio, language=self.language, beam_size=1,
                                           vad_filter=True)
            text = " ".join(s.text.strip() for s in segments).strip()
            self.last_error = ""
            return text
        except Exception as e:
            self.last_error = f"Transcription failed: {e}"
            raise RuntimeError(self.last_error) from e

    def transcribe_wav(self, wav_path: str | Path) -> str:
        model = self._ensure_model()
        segments, _ = model.transcribe(str(wav_path), language=self.language, beam_size=1)
        return " ".join(s.text.strip() for s in segments).strip()


def write_wav_debug(pcm: bytes, path: str | Path) -> None:
    """Utility: dump PCM to wav for debugging."""
    import wave
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm)
