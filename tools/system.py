"""Safe system info + time (psutil-based, all functions never raise)."""
from __future__ import annotations

from datetime import datetime


def get_current_time() -> dict:
    now = datetime.now()
    return {"ok": True,
            "message": now.strftime("%I:%M %p on %A, %B %d, %Y.")}


def get_system_info(detail: str = "all") -> dict:
    d = (detail or "all").lower()
    try:
        import psutil
    except ImportError:
        return {"ok": False, "message": "System info is unavailable right now."}
    try:
        parts = []
        if d in ("cpu", "all"):
            parts.append(f"CPU {psutil.cpu_percent(interval=0.5):.0f}% ({psutil.cpu_count()} cores)")
        if d in ("ram", "all"):
            m = psutil.virtual_memory()
            parts.append(f"RAM {m.percent:.0f}% used ({m.used/1e9:.1f}/{m.total/1e9:.1f} GB)")
        if d in ("disk", "all"):
            du = psutil.disk_usage("C:\\")
            parts.append(f"Disk C: {du.percent:.0f}% used ({du.free/1e9:.1f} GB free)")
        if d in ("battery", "all"):
            try:
                b = psutil.sensors_battery()
                parts.append(f"Battery {b.percent:.0f}%{' charging' if b.power_plugged else ''}."
                             if b else "Battery info unavailable.")
            except Exception:
                parts.append("Battery info unavailable.")
        if d in ("ip", "all"):
            import socket
            try:
                ip = socket.gethostbyname(socket.gethostname())
                parts.append(f"Local IP {ip}.")
            except Exception:
                parts.append("IP unavailable.")
        return {"ok": True, "message": " ".join(parts)}
    except Exception as e:
        return {"ok": False, "message": f"Could not read system info: {e}"}
