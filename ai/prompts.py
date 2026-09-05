"""Small prompt helpers (kept separate so personality stays editable)."""
from __future__ import annotations


def short_reply_instruction() -> str:
    return (
        "Reply in 1-2 short sentences for simple commands. "
        "Only elaborate when the user asks for detail."
    )
