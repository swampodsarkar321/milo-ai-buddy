"""NOVA configuration — loads .env + settings.json, single source of truth."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Project root = nova_assistant/
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

ENV_PATH = BASE_DIR / ".env"
load_dotenv(ENV_PATH)

SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "nova.db"


@dataclass
class AISettings:
    provider: str = "openai"          # openai | openrouter | ollama | custom
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    temperature: float = 0.7
    max_tokens: int = 300             # smaller = faster voice replies
    auto_switch: bool = True          # try fallback free models on failure
    fallback_models: str = ""         # comma-separated extra models (optional)
    max_attempts: int = 3             # max models tried per message (fast fail)
    request_timeout: int = 20         # seconds per model attempt, then switch


@dataclass
class VoiceSettings:
    tts_voice: str = "en-US-AriaNeural"   # edge-tts voice id
    rate: str = "+0%"                      # edge-tts rate, e.g. -10% .. +30%
    volume: str = "+0%"
    microphone_index: int = -1             # -1 = default device
    wake_word: str = "hey milo"
    wake_word_enabled: bool = True
    push_to_talk: bool = False
    stt_model: str = "small"               # faster-whisper model: tiny/base/small/medium
    language: str = "en"


@dataclass
class AppearanceSettings:
    theme: str = "dark"                    # dark | light
    accent: str = "#7c5cff"
    animation_intensity: str = "medium"    # low | medium | high


@dataclass
class PrivacySettings:
    memory_enabled: bool = True
    speak_reminders: bool = True
    routines: bool = True              # learn repeated commands, suggest them


@dataclass
class PersonalitySettings:
    name: str = "Milo"
    traits: str = "Friendly, helpful, slightly playful, calm, intelligent."
    style: str = (
        "Natural conversational style. Concise for simple commands "
        "(1-2 sentences). Detailed only when asked."
    )


@dataclass
class BrandSettings:
    """Your product identity (shown in the app; tech stays hidden)."""
    app_name: str = "Milo"
    tagline: str = "Your personal voice partner"


@dataclass
class MascotSettings:
    """Desktop buddy overlay (roams the screen, reacts to voice states)."""
    enabled: bool = True
    size: str = "medium"              # small | medium | large
    bubble: str = "auto"              # bubble colour: auto | white | accent
    tray: bool = True                 # closing the window hides to buddy+tray


@dataclass
class AppConfig:
    ai: AISettings = field(default_factory=AISettings)
    voice: VoiceSettings = field(default_factory=VoiceSettings)
    appearance: AppearanceSettings = field(default_factory=AppearanceSettings)
    privacy: PrivacySettings = field(default_factory=PrivacySettings)
    personality: PersonalitySettings = field(default_factory=PersonalitySettings)
    brand: BrandSettings = field(default_factory=BrandSettings)
    mascot: MascotSettings = field(default_factory=MascotSettings)

    # ---------- load / save ----------

    @classmethod
    def load(cls) -> "AppConfig":
        cfg = cls()
        # 1) API key always prefers environment (never hardcode).
        env_key = (
            os.getenv("OPENAI_API_KEY")
            or os.getenv("LLM_API_KEY")
            or ""
        )
        if env_key:
            cfg.ai.api_key = env_key
        if os.getenv("LLM_BASE_URL"):
            cfg.ai.base_url = os.getenv("LLM_BASE_URL", cfg.ai.base_url)
        if os.getenv("LLM_MODEL"):
            cfg.ai.model = os.getenv("LLM_MODEL", cfg.ai.model)
        if os.getenv("LLM_PROVIDER"):
            cfg.ai.provider = os.getenv("LLM_PROVIDER", cfg.ai.provider)
        # Production branding (optional): APP_NAME="My Partner"
        if os.getenv("APP_NAME"):
            cfg.brand.app_name = os.getenv("APP_NAME", cfg.brand.app_name)

        # 2) Overlay persisted settings.json
        if SETTINGS_PATH.exists():
            try:
                raw = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
                for section in ("ai", "voice", "appearance", "privacy",
                                "personality", "brand", "mascot"):
                    if section in raw and isinstance(raw[section], dict):
                        target = getattr(cfg, section)
                        for k, v in raw[section].items():
                            if hasattr(target, k) and k != "api_key":
                                # api_key stays from env; saved key only as fallback
                                setattr(target, k, v)
                        # saved api key is only used when env has none
                        if section == "ai" and not cfg.ai.api_key:
                            cfg.ai.api_key = raw["ai"].get("api_key", "")
            except Exception:
                pass  # corrupt settings -> fall back to defaults
        return cfg

    def save(self) -> None:
        data = asdict(self)
        # Production rule: the API key is NEVER written to disk.
        # It lives only in the .env file / environment.
        try:
            data["ai"]["api_key"] = ""
        except Exception:
            pass
        SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def update_section(self, section: str, values: dict) -> None:
        target = getattr(self, section)
        for k, v in values.items():
            if hasattr(target, k):
                setattr(target, k, v)
        self.save()
