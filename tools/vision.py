"""Screen understanding: screenshot -> vision LLM -> short spoken answer.

"Buddy, ekhane samasya ki?" -> captures the screen, asks a free
vision model, replies in 1-2 sentences. Tries cached vision models in
order (auto-switch); refreshes the vision list in background rarely.

Never raises to the caller: returns {'ok','message'} like other tools.
Needs internet + configured engine (OpenRouter free vision models).
"""
from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path

VISION_CACHE_FILE = "vision_models.json"
VISION_TTL_S = 86400  # refresh vision list at most daily


def screenshot_b64(max_width: int = 1280) -> str | None:
    """Capture screen, downscale, return base64 JPEG (or None)."""
    try:
        from PIL import ImageGrab
    except ImportError:
        return None
    try:
        img = ImageGrab.grab().convert("RGB")
        if img.width > max_width:
            img = img.resize((max_width, int(img.height * max_width / img.width)))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return None


def _vision_cache_path() -> Path:
    from config import DATA_DIR
    return DATA_DIR / VISION_CACHE_FILE


def vision_model_ids(api_key: str, force: bool = False) -> list[str]:
    """Cached free vision-model ids (refreshes daily / on force)."""
    cache = _vision_cache_path()
    if not force and cache.exists():
        try:
            raw = json.loads(cache.read_text(encoding="utf-8"))
            if time.time() - raw.get("updated_at", 0) < VISION_TTL_S:
                ids = [m["id"] for m in raw.get("models", []) if m.get("id")]
                if ids:
                    return ids
        except Exception:
            pass
    from ai.models import fetch_vision_models
    models = fetch_vision_models(api_key)
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"updated_at": time.time(),
                                     "models": models}, indent=1), encoding="utf-8")
    except Exception:
        pass
    return [m["id"] for m in models]


def ask_screen(question: str, llm, timeout: int = 90) -> dict:
    """Full pipeline: capture -> ask vision models in order -> answer dict."""
    img = screenshot_b64()
    if not img:
        return {"ok": False, "message": "I couldn't capture the screen right now."}
    try:
        ids = vision_model_ids(llm.api_key)
    except Exception as e:
        return {"ok": False, "message": f"Couldn't reach the vision models: {e}"}
    if not ids:
        return {"ok": False, "message": "No vision models available right now."}
    system = ("You see the user's Windows screen. Answer in 1-2 short sentences "
              "for voice. Be concrete: name the app, the visible error or button. "
              "If they ask for a fix and it's a simple safe one, offer it in one line.")
    last_err = ""
    for mid in ids[:4]:
        try:
            text = llm.chat_vision(mid, system, question, img, timeout=timeout)
            llm.active_model = mid
            llm.model = mid
            return {"ok": True, "message": text, "model": mid}
        except Exception as e:
            last_err = str(e)[:120]
            continue
    return {"ok": False, "message": "I looked but couldn't analyse the screen. Try again."}
