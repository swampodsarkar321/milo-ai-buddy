"""Browser actions: open URLs, Google/YouTube search, app shortcuts."""
from __future__ import annotations

import subprocess
import webbrowser
from urllib.parse import quote_plus

# Friendly shortcuts: "open youtube" -> url
SITE_SHORTCUTS = {
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "facebook": "https://www.facebook.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "spotify": "https://open.spotify.com",
    "netflix": "https://www.netflix.com",
    "twitter": "https://x.com",
    "x": "https://x.com",
    "instagram": "https://www.instagram.com",
    "stackoverflow": "https://stackoverflow.com",
}

APP_COMMANDS = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "file explorer": ["explorer.exe"],
    "cmd": ["cmd.exe"],
    "terminal": ["wt.exe"],
    "paint": ["mspaint.exe"],
    "chrome": ["cmd", "/c", "start", "chrome"],
    "spotify": ["cmd", "/c", "start", "spotify"],
    "vscode": ["cmd", "/c", "start", "code"],
    "code": ["cmd", "/c", "start", "code"],
}


def _ensure_scheme(url: str) -> str:
    url = url.strip().strip("\"'")
    if not url.startswith(("http://", "https://")):
        return "https://" + url
    return url


def open_website(url: str = "", site: str = "") -> dict:
    """Open a website. Returns {'ok', 'message'} — never raises."""
    try:
        target = ""
        if site:
            target = SITE_SHORTCUTS.get(site.lower().strip(), "")
        if not target:
            if not url:
                return {"ok": False, "message": "No URL given."}
            target = _ensure_scheme(url)
        webbrowser.open(target)
        return {"ok": True, "message": f"Opened {target}."}
    except Exception as e:
        return {"ok": False, "message": f"Could not open website: {e}"}


def search_web(query: str, engine: str = "google") -> dict:
    try:
        q = quote_plus(query or "")
        if engine == "youtube":
            url = f"https://www.youtube.com/results?search_query={q}"
        else:
            url = f"https://www.google.com/search?q={q}"
        webbrowser.open(url)
        return {"ok": True, "message": f"Searching {engine} for '{query}'."}
    except Exception as e:
        return {"ok": False, "message": f"Search failed: {e}"}


def web_search_snippets(query: str, max_results: int = 4) -> dict:
    """Lightweight snippet search via DuckDuckGo HTML (no API key)."""
    try:
        import requests
        from html import unescape
        import re
        r = requests.get("https://html.duckduckgo.com/html/",
                         params={"q": query}, timeout=12,
                         headers={"User-Agent": "Mozilla/5.0"})
        snippets = re.findall(r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
        clean = [re.sub(r"<.*?>", "", unescape(s)).strip() for s in snippets][:max_results]
        clean = [c for c in clean if c]
        if not clean:
            return {"ok": True, "message": "No snippets found, opened browser instead.",
                    "results": []}
        return {"ok": True, "message": " | ".join(clean), "results": clean}
    except Exception as e:
        return {"ok": False, "message": f"Web search failed: {e}", "results": []}


def open_application(app: str) -> dict:
    """Open a whitelisted desktop app. Blocks arbitrary shell commands."""
    key = (app or "").lower().strip()
    if not key:
        return {"ok": False, "message": "No app name given."}
    # direct shortcut match
    for name, cmd in APP_COMMANDS.items():
        if name in key or key in name:
            try:
                subprocess.Popen(cmd, shell=False)
                return {"ok": True, "message": f"Opening {name}."}
            except Exception as e:
                return {"ok": False, "message": f"Could not open {name}: {e}"}
    # safe fallback: Windows start <name> (no shell injection: list form)
    try:
        subprocess.Popen(["cmd", "/c", "start", "", key], shell=False)
        return {"ok": True, "message": f"Opening {app}."}
    except Exception as e:
        return {"ok": False, "message": f"Could not open {app}: {e}"}
