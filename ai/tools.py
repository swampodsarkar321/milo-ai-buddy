"""Tool definitions exposed to the LLM (JSON contract) + dispatcher helpers."""
from __future__ import annotations

# name -> {description, args}
TOOL_SCHEMAS: dict[str, dict] = {
    "open_website": {
        "description": "Open a website URL in the browser.",
        "args": {"url": "https://... (required)", "site": "optional nickname"},
    },
    "search_web": {
        "description": "Search the web (google/youtube) and open results.",
        "args": {"query": "search text (required)", "engine": "google|youtube"},
    },
    "open_application": {
        "description": "Open a desktop app: chrome, notepad, spotify, explorer, cmd, calculator, ...",
        "args": {"app": "app name (required)"},
    },
    "take_screenshot": {
        "description": "Capture the screen to a PNG file.",
        "args": {},
    },
    "get_system_info": {
        "description": "CPU/RAM/disk/battery/IP info.",
        "args": {"detail": "cpu|ram|disk|battery|ip|all"},
    },
    "get_current_time": {
        "description": "Current date and time.",
        "args": {},
    },
    "create_reminder": {
        "description": "Save a reminder. minutes_from_now OR due_at 'YYYY-MM-DD HH:MM'.",
        "args": {"text": "reminder text", "minutes_from_now": 60, "due_at": ""},
    },
    "web_search": {
        "description": "Return web result snippets as text (for knowledge questions).",
        "args": {"query": "search text"},
    },
    # ---- PC control ----
    "close_application": {
        "description": "Close/quit a running desktop app.",
        "args": {"app": "app name (required)"},
    },
    "lock_pc": {"description": "Lock the Windows screen.", "args": {}},
    "shutdown_pc": {"description": "CONFIRM-FIRST: shut the PC down.", "args": {}},
    "restart_pc": {"description": "CONFIRM-FIRST: restart the PC.", "args": {}},
    "sleep_pc": {"description": "CONFIRM-FIRST: put the PC to sleep.", "args": {}},
    "sign_out": {"description": "CONFIRM-FIRST: sign out of Windows.", "args": {}},
    "volume_up": {"description": "Volume up one step.", "args": {}},
    "volume_down": {"description": "Volume down one step.", "args": {}},
    "volume_mute": {"description": "Mute/unmute toggle.", "args": {}},
    "media_next": {"description": "Next song/track.", "args": {}},
    "media_prev": {"description": "Previous song/track.", "args": {}},
    "media_play_pause": {"description": "Play/pause media.", "args": {}},
    # ---- files (scoped to user profile, no delete in V1) ----
    "search_files": {
        "description": "Find files by name under the user profile.",
        "args": {"query": "name fragment (required)", "folder": "optional folder"},
    },
    "create_folder": {
        "description": "Create a folder.",
        "args": {"name": "folder name (required)", "where": "optional parent"},
    },
    "rename_path": {
        "description": "Rename a file/folder.",
        "args": {"src": "current path (required)", "new_name": "new name (required)"},
    },
    "copy_path": {
        "description": "Copy a file/folder somewhere.",
        "args": {"src": "path (required)", "dest_folder": "folder (required)"},
    },
    "move_path": {
        "description": "Move a file/folder somewhere.",
        "args": {"src": "path (required)", "dest_folder": "folder (required)"},
    },
    "list_large_files": {
        "description": "Biggest files under a folder.",
        "args": {"folder": "optional folder", "top": 10},
    },
    "organize_downloads": {
        "description": "Sort Downloads into PDFs/Images/Videos/Music/Docs/Zips.",
        "args": {},
    },
    "read_text_file": {
        "description": "Read a .txt/.md/.log file (capped).",
        "args": {"path": "file path (required)"},
    },
    # ---- vision ----
    "look_at_screen": {
        "description": "See the current screen (for 'what's wrong here?' questions).",
        "args": {"question": "what to look for (required)"},
    },
    # ---- todo / timer / status ----
    "todo_add": {"description": "Add a to-do item.", "args": {"text": "item (required)"}},
    "todo_list": {"description": "List open to-do items.", "args": {}},
    "todo_done": {"description": "Finish the Nth to-do.", "args": {"num": 1}},
    "create_timer": {
        "description": "Countdown timer that announces at the end.",
        "args": {"seconds": 600, "label": "optional label"},
    },
    "system_status": {
        "description": "Self-diagnostics: engine/voice/mic/memory/net/PC health.",
        "args": {},
    },
}


def tools_prompt_text() -> str:
    lines = []
    for name, spec in TOOL_SCHEMAS.items():
        lines.append(f"- {name}{spec['args']}: {spec['description']}")
    return "\n".join(lines)


def parse_tool_call(text: str) -> dict | None:
    """Return {'tool', 'args', 'reply'} if the model emitted a tool JSON, else None."""
    import json

    t = text.strip()
    # allow ```json fences
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    if not t.startswith("{"):
        return None
    try:
        obj = json.loads(t)
    except Exception:
        return None
    if isinstance(obj, dict) and "tool" in obj and obj["tool"] in TOOL_SCHEMAS:
        obj.setdefault("args", {})
        obj.setdefault("reply", "")
        return obj
    return None
