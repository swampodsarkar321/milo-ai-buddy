"""Extended PC control: apps, power, volume, media keys (Windows).

Safety tiers (per product spec):
- SAFE (no confirm): close_app whitelisted, lock, volume, media keys, info.
- CONFIRM (voice "yes"): shutdown, restart, sign out, sleep.
- BLOCKED: system processes, arbitrary shell.

All functions return {'ok', 'message'} and never raise.
"""
from __future__ import annotations

import subprocess

# friendly name -> exe image name
APP_EXES = {
    "chrome": "chrome.exe",
    "discord": "Discord.exe",
    "vscode": "Code.exe",
    "vs code": "Code.exe",
    "code": "Code.exe",
    "spotify": "Spotify.exe",
    "notepad": "notepad.exe",
    "vlc": "vlc.exe",
    "firefox": "firefox.exe",
    "edge": "msedge.exe",
    "telegram": "Telegram.exe",
    "whatsapp": "WhatsApp.exe",
    "zoom": "Zoom.exe",
    "teams": "ms-teams.exe",
    "explorer": "explorer.exe",
}

# never touch these
BLOCKED_EXES = {
    "explorer.exe", "csrss.exe", "smss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "svchost.exe", "dwm.exe", "taskhostw.exe", "sihost.exe",
    "RuntimeBroker.exe", "System",
}

# virtual-key codes for keybd_event (no new dependencies)
VK_VOLUME_MUTE, VK_VOLUME_DOWN, VK_VOLUME_UP = 0xAD, 0xAE, 0xAF
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY_PAUSE = 0xB0, 0xB1, 0xB3


def _tap_vk(code: int) -> bool:
    try:
        import ctypes
        ctypes.windll.user32.keybd_event(code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(code, 0, 2, 0)
        return True
    except Exception:
        return False


def close_application(app: str) -> dict:
    key = (app or "").lower().strip()
    if not key:
        return {"ok": False, "message": "Which app should I close?"}
    exe = APP_EXES.get(key, "")
    if not exe:
        # try "<name>.exe" guess, still guarded by blocklist
        exe = key if key.endswith(".exe") else key + ".exe"
    if exe.lower() in {b.lower() for b in BLOCKED_EXES}:
        return {"ok": False, "message": f"I can't close {exe} — Windows needs it."}
    try:
        r = subprocess.run(["taskkill", "/IM", exe], capture_output=True,
                           text=True, timeout=15)
        if r.returncode == 0:
            return {"ok": True, "message": f"Closed {app}."}
        return {"ok": False, "message": f"{app} doesn't seem to be running."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't close {app}: {e}"}


def lock_pc() -> dict:
    try:
        import ctypes
        ctypes.windll.user32.LockWorkStation()
        return {"ok": True, "message": "PC locked."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't lock the PC: {e}"}


def _power(cmd: list[str], label: str) -> dict:
    try:
        subprocess.Popen(cmd, shell=False)
        return {"ok": True, "message": f"{label}…"}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't do it: {e}"}


def shutdown_pc() -> dict:
    return _power(["shutdown", "/s", "/t", "5"], "Shutting down in 5 seconds")


def restart_pc() -> dict:
    return _power(["shutdown", "/r", "/t", "5"], "Restarting in 5 seconds")


def sleep_pc() -> dict:
    return _power(["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
                  "Going to sleep…")


def sign_out() -> dict:
    return _power(["shutdown", "/l"], "Signing out…")


# ---------- brightness (needs screen-brightness-control, else graceful) ----------

def _sbc():
    try:
        import screen_brightness_control as sbc
        return sbc
    except ImportError:
        return None


def brightness_get() -> dict:
    sbc = _sbc()
    if sbc is None:
        return {"ok": False, "message": "Brightness control isn't installed yet."}
    try:
        vals = sbc.get_brightness(display=0)
        pct = int(vals[0]) if vals else 0
        return {"ok": True, "message": f"Brightness is {pct}%.", "value": pct}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't read brightness: {e}"}


def brightness_set(level: int) -> dict:
    sbc = _sbc()
    if sbc is None:
        return {"ok": False, "message": "Brightness control isn't installed yet."}
    try:
        level = max(5, min(100, int(level)))
        sbc.set_brightness(level, display=0)
        return {"ok": True, "message": f"Brightness set to {level}%."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't set brightness: {e}"}


def brightness_step(delta: int) -> dict:
    cur = brightness_get()
    if not cur.get("ok"):
        return cur
    return brightness_set(int(cur.get("value", 50)) + int(delta))


# ---------- foreground window control (ctypes only) ----------

SW_MINIMIZE, SW_MAXIMIZE, SW_RESTORE = 6, 3, 9


def _fg_hwnd():
    try:
        import ctypes
        return ctypes.windll.user32.GetForegroundWindow()
    except Exception:
        return 0


def window_minimize() -> dict:
    try:
        import ctypes
        hwnd = _fg_hwnd()
        if not hwnd:
            return {"ok": False, "message": "No active window found."}
        ctypes.windll.user32.ShowWindow(hwnd, SW_MINIMIZE)
        return {"ok": True, "message": "Window minimized."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't minimize: {e}"}


def window_maximize() -> dict:
    try:
        import ctypes
        hwnd = _fg_hwnd()
        if not hwnd:
            return {"ok": False, "message": "No active window found."}
        ctypes.windll.user32.ShowWindow(hwnd, SW_MAXIMIZE)
        return {"ok": True, "message": "Window maximized."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't maximize: {e}"}


def window_restore() -> dict:
    try:
        import ctypes
        hwnd = _fg_hwnd()
        if not hwnd:
            return {"ok": False, "message": "No active window found."}
        ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
        return {"ok": True, "message": "Window restored."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't restore: {e}"}


def _iter_windows() -> list[tuple[int, str]]:
    """[(hwnd, title)] visible top-level windows with titles."""
    out: list[tuple[int, str]] = []
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def _cb(hwnd, _lp):
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                n = user32.GetWindowTextLengthW(hwnd)
                if n <= 0 or n > 200:
                    return True
                buf = ctypes.create_unicode_buffer(n + 1)
                user32.GetWindowTextW(hwnd, buf, n + 1)
                title = buf.value.strip()
                if title:
                    out.append((hwnd, title))
            except Exception:
                pass
            return True

        user32.EnumWindows(_cb, 0)
    except Exception:
        pass
    return out


def window_list(limit: int = 8) -> dict:
    wins = _iter_windows()
    if not wins:
        return {"ok": False, "message": "Couldn't see open windows."}
    names = [t[:50] for _, t in wins[:limit]]
    return {"ok": True, "message": "Open: " + " | ".join(names),
            "results": names}


def window_focus(name: str) -> dict:
    key = (name or "").lower().strip()
    if not key:
        return {"ok": False, "message": "Switch to which window?"}
    wins = _iter_windows()
    hit = next((h for h, t in wins if key in t.lower()), None)
    if hit is None:
        hit = next((h for h, t in wins
                    if any(w in t.lower() for w in key.split())), None)
    if hit is None:
        return {"ok": False, "message": f"No window matching '{name}'."}
    try:
        import ctypes
        ctypes.windll.user32.ShowWindow(hit, SW_RESTORE)
        ctypes.windll.user32.SetForegroundWindow(hit)
        return {"ok": True, "message": f"Switched to {name}."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't switch: {e}"}


# ---------- volume / media (all safe, instant) ----------

def volume_up() -> dict:
    return {"ok": True, "message": "Volume up."} if _tap_vk(VK_VOLUME_UP) \
        else {"ok": False, "message": "Couldn't change volume."}


def volume_down() -> dict:
    return {"ok": True, "message": "Volume down."} if _tap_vk(VK_VOLUME_DOWN) \
        else {"ok": False, "message": "Couldn't change volume."}


def volume_mute_toggle() -> dict:
    if _tap_vk(VK_VOLUME_MUTE):
        return {"ok": True, "message": "Mute toggled."}
    return {"ok": False, "message": "Couldn't change volume."}


def media_next() -> dict:
    return {"ok": True, "message": "Next track."} if _tap_vk(VK_MEDIA_NEXT) \
        else {"ok": False, "message": "No media playing?"}


def media_prev() -> dict:
    return {"ok": True, "message": "Previous track."} if _tap_vk(VK_MEDIA_PREV) \
        else {"ok": False, "message": "No media playing?"}


def media_play_pause() -> dict:
    return {"ok": True, "message": "Play/pause."} if _tap_vk(VK_MEDIA_PLAY_PAUSE) \
        else {"ok": False, "message": "No media playing?"}
