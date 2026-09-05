"""Safe file tools, scoped to the user profile (no system dirs, no delete).

Allowed roots: USERPROFILE (Documents, Downloads, Desktop, …).
- search_files: find by name fragment (capped walk, skips AppData noise).
- create_folder / rename_path / copy_path / move_path: guarded writes.
- list_large_files: top-N biggest under a folder.
- organize_downloads: sort Downloads into PDFs/Images/Videos/Music/Docs/Zips.
- read_text_file: capped read (also powers buddy drop-to-read).

Every function returns {'ok', 'message', ...} and never raises.
There is intentionally NO delete tool in V1 (use Recycle Bin yourself).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

HOME = Path.home()
MAX_WALK_FILES = 20000
MAX_RESULTS = 15
READ_CHARS = 4000

GROUPS = {
    "PDFs": {".pdf"},
    "Images": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico"},
    "Videos": {".mp4", ".mkv", ".avi", ".mov", ".webm"},
    "Music": {".mp3", ".wav", ".flac", ".ogg", ".m4a"},
    "Docs": {".docx", ".doc", ".txt", ".md", ".pptx", ".xlsx", ".csv"},
    "Zips": {".zip", ".rar", ".7z", ".tar", ".gz"},
}


def _inside_home(p: Path) -> bool:
    try:
        return Path(p).resolve().is_relative_to(HOME.resolve())
    except Exception:
        return False


def _resolve(name: str, base: Path | None = None) -> Path | None:
    """Resolve a user-given name to an absolute path (or None)."""
    name = (name or "").strip().strip("\"'")
    if not name:
        return None
    p = Path(name)
    if not p.is_absolute():
        p = (base or HOME) / p
    return p


def search_files(query: str, folder: str = "", limit: int = MAX_RESULTS) -> dict:
    root = _resolve(folder) if folder else HOME
    if root is None or not root.exists():
        return {"ok": False, "message": "That folder doesn't exist."}
    q = query.lower().strip()
    if not q:
        return {"ok": False, "message": "What should I search for?"}
    hits: list[str] = []
    seen = 0
    skip = {"AppData", "Application Data", ".git", "node_modules", "__pycache__"}
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for fn in filenames:
                seen += 1
                if seen > MAX_WALK_FILES:
                    break
                if q in fn.lower():
                    hits.append(str(Path(dirpath) / fn))
                    if len(hits) >= limit:
                        break
            if len(hits) >= limit or seen > MAX_WALK_FILES:
                break
    except Exception as e:
        return {"ok": False, "message": f"Search failed: {e}"}
    if not hits:
        return {"ok": True, "message": f"No files matching '{query}'.", "results": []}
    return {"ok": True, "message": f"Found {len(hits)}: {'; '.join(hits[:5])}",
            "results": hits}


def create_folder(name: str, where: str = "") -> dict:
    base = _resolve(where) if where else HOME / "Documents"
    if base is None:
        return {"ok": False, "message": "Where should I create it?"}
    target = base / name.strip().strip("\"'")
    if not _inside_home(target):
        return {"ok": False, "message": "I only create folders inside your profile."}
    try:
        target.mkdir(parents=True, exist_ok=True)
        return {"ok": True, "message": f"Folder created: {target.name}."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't create it: {e}"}


def rename_path(src: str, new_name: str) -> dict:
    s = _resolve(src)
    if s is None or not s.exists():
        return {"ok": False, "message": "I couldn't find that file."}
    if not _inside_home(s):
        return {"ok": False, "message": "Only files inside your profile."}
    try:
        dest = s.parent / new_name.strip().strip("\"'")
        if dest.exists():
            return {"ok": False, "message": "That name is already taken."}
        s.rename(dest)
        return {"ok": True, "message": f"Renamed to {dest.name}."}
    except Exception as e:
        return {"ok": False, "message": f"Rename failed: {e}"}


def _safe_copy_move(src: str, dest_folder: str, move: bool) -> dict:
    s = _resolve(src)
    d = _resolve(dest_folder)
    if s is None or not s.exists():
        return {"ok": False, "message": "I couldn't find that file."}
    if d is None:
        return {"ok": False, "message": "Which folder should it go to?"}
    if not _inside_home(s) or not _inside_home(d):
        return {"ok": False, "message": "Only inside your profile."}
    try:
        d.mkdir(parents=True, exist_ok=True)
        target = d / s.name
        if target.exists():  # never overwrite: uniquify
            stem, suf = s.stem, s.suffix
            i = 2
            while (d / f"{stem} ({i}){suf}").exists():
                i += 1
            target = d / f"{stem} ({i}){suf}"
        if move:
            shutil.move(str(s), str(target))
            return {"ok": True, "message": f"Moved to {d.name}."}
        if s.is_dir():
            shutil.copytree(str(s), str(target))
        else:
            shutil.copy2(str(s), str(target))
        return {"ok": True, "message": f"Copied to {d.name}."}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't do it: {e}"}


def copy_path(src: str, dest_folder: str) -> dict:
    return _safe_copy_move(src, dest_folder, move=False)


def move_path(src: str, dest_folder: str) -> dict:
    return _safe_copy_move(src, dest_folder, move=True)


def list_large_files(folder: str = "", top: int = 10) -> dict:
    root = _resolve(folder) if folder else HOME
    if root is None or not root.exists():
        return {"ok": False, "message": "That folder doesn't exist."}
    found: list[tuple[float, str]] = []
    seen = 0
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            if "AppData" in dirpath.split(os.sep):
                dirnames[:] = []
                continue
            for fn in filenames:
                seen += 1
                if seen > MAX_WALK_FILES:
                    break
                fp = Path(dirpath) / fn
                try:
                    found.append((fp.stat().st_size, str(fp)))
                except OSError:
                    pass
            if seen > MAX_WALK_FILES:
                break
    except Exception as e:
        return {"ok": False, "message": f"Scan failed: {e}"}
    found.sort(reverse=True)
    top = max(1, min(int(top or 10), 20))
    lines = [f"{mb / 1e6:.0f} MB — {Path(p).name}" for mb, p in found[:top]]
    if not lines:
        return {"ok": True, "message": "No files found there.", "results": []}
    return {"ok": True, "message": "Biggest files: " + " | ".join(lines[:5]),
            "results": [p for _, p in found[:top]]}


def organize_downloads() -> dict:
    dl = HOME / "Downloads"
    if not dl.exists():
        return {"ok": False, "message": "No Downloads folder found."}
    moved = 0
    try:
        for item in dl.iterdir():
            if not item.is_file() or item.suffix.lower() in {".crdownload", ".part", ".tmp"}:
                continue
            group = next((g for g, exts in GROUPS.items()
                          if item.suffix.lower() in exts), "Others")
            dest = dl / group
            dest.mkdir(exist_ok=True)
            target = dest / item.name
            if target.exists():
                stem, suf = item.stem, item.suffix
                i = 2
                while (dest / f"{stem} ({i}){suf}").exists():
                    i += 1
                target = dest / f"{stem} ({i}){suf}"
            shutil.move(str(item), str(target))
            moved += 1
        if not moved:
            return {"ok": True, "message": "Downloads is already tidy."}
        return {"ok": True, "message": f"Organized {moved} files into folders."}
    except Exception as e:
        return {"ok": False, "message": f"Organize failed: {e}"}


def read_text_file(path: str, max_chars: int = READ_CHARS) -> dict:
    p = _resolve(path)
    if p is None or not p.is_file():
        return {"ok": False, "message": "I couldn't find that file."}
    if p.suffix.lower() not in {".txt", ".md", ".log", ".csv", ".json"}:
        return {"ok": False, "message": "I can only read text files (for now)."}
    try:
        text = p.read_text(encoding="utf-8", errors="replace")[:max_chars].strip()
        if not text:
            return {"ok": False, "message": "That file seems empty."}
        return {"ok": True, "message": text, "path": str(p)}
    except Exception as e:
        return {"ok": False, "message": f"Couldn't read it: {e}"}
