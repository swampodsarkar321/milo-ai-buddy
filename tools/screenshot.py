"""Screenshots via Pillow (ImageGrab, Windows) with graceful fallback."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path


def take_screenshot(save_dir: str | Path = "data") -> dict:
    try:
        from PIL import ImageGrab
    except ImportError:
        return {"ok": False, "message": "Screenshots are unavailable right now."}
    try:
        save_dir = Path(save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)
        name = "shot_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".png"
        out = save_dir / name
        img = ImageGrab.grab()
        img.save(out)
        return {"ok": True, "message": "Screenshot saved.", "path": str(out)}
    except Exception as e:
        return {"ok": False, "message": f"Screenshot failed: {e}"}
