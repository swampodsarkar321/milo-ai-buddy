"""Short-term conversation buffer (last N turns) for prompt context."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class Turn:
    role: str   # "user" | "assistant"
    text: str


class Conversation:
    def __init__(self, max_turns: int = 12):
        self._turns: deque[Turn] = deque(maxlen=max_turns * 2)

    def add_user(self, text: str) -> None:
        self._turns.append(Turn("user", text.strip()))

    def add_assistant(self, text: str) -> None:
        self._turns.append(Turn("assistant", text.strip()))

    def clear(self) -> None:
        self._turns.clear()

    def __len__(self) -> int:
        return len(self._turns)

    def all(self) -> list[Turn]:
        return list(self._turns)

    def as_prompt_text(self, limit: int = 10) -> str:
        lines = []
        for t in list(self._turns)[-limit:]:
            who = "User" if t.role == "user" else "Nova"
            lines.append(f"{who}: {t.text}")
        return "\n".join(lines)

    def export_text(self) -> str:
        lines = []
        for t in self._turns:
            who = "YOU" if t.role == "user" else "NOVA"
            lines.append(f"{who}: {t.text}\n")
        return "\n".join(lines)
