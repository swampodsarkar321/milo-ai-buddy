"""OpenAI-compatible LLM client (OpenAI, OpenRouter, Ollama, LM Studio...).

Uses the `openai` python package (>=1.0) which supports custom base_url.
Falls back to a local echo responder when no API key is configured so the
GUI still works offline for demo purposes.
"""
from __future__ import annotations


class LLMClient:
    def __init__(self, api_key="", base_url="https://api.openai.com/v1",
                 model="gpt-4o-mini", temperature=0.7, max_tokens=500,
                 provider="openai"):
        self.api_key = api_key or ""
        self.base_url = (base_url or "https://api.openai.com/v1").rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.provider = (provider or "openai").lower()
        self.last_error = ""
        self.active_model = model  # last model that actually answered

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def reconfigure(self, api_key="", base_url="", model="",
                    temperature=None, max_tokens=None, provider=None) -> None:
        if api_key is not None:
            self.api_key = api_key
        if base_url:
            self.base_url = base_url.rstrip("/")
        if model:
            self.model = model
        if temperature is not None:
            self.temperature = temperature
        if max_tokens is not None:
            self.max_tokens = max_tokens
        if provider:
            self.provider = provider.lower()

    # ---------- client ----------
    def _require_deps(self) -> None:
        if not self.api_key:
            raise RuntimeError("AI engine is offline. Please check your connection.")
        try:
            import requests  # noqa: F401
        except ImportError as e:
            raise RuntimeError("AI engine is not installed correctly.") from e

    def _headers(self) -> dict:
        h = {"Authorization": f"Bearer {self.api_key}",
             "Content-Type": "application/json"}
        if self.provider == "openrouter" or "openrouter" in self.base_url:
            # OpenRouter recommends these; harmless for other providers.
            h["HTTP-Referer"] = "https://github.com/nova-voice-partner"
            h["X-Title"] = "NOVA Voice Partner"
        return h

    # ---------- single-model call (plain requests: timeout ALWAYS enforced) ----------
    def _chat_once(self, model: str, system: str,
                   messages: list[dict], timeout: int) -> str:
        import requests
        try:
            r = requests.post(
                self.base_url + "/chat/completions",
                headers=self._headers(),
                json={"model": model,
                      "messages": [{"role": "system", "content": system}] + messages,
                      "temperature": float(self.temperature),
                      "max_tokens": int(self.max_tokens)},
                timeout=max(5, int(timeout)))
        except requests.Timeout as e:
            raise RuntimeError(f"Engine timeout after {timeout}s.") from e
        except requests.ConnectionError as e:
            raise RuntimeError(f"Engine connection failed: {e}.") from e
        except Exception as e:
            raise RuntimeError(f"Engine request failed: {e}.") from e
        if r.status_code == 200:
            try:
                text = ((r.json().get("choices") or [{}])[0]
                        .get("message", {}).get("content", "") or "").strip()
            except Exception:
                text = ""
            if not text:
                raise RuntimeError("Engine returned an empty response.")
            return text
        body = (r.text or "")[:200]
        raise RuntimeError(f"HTTP {r.status_code}: {body}")

    # ---------- main call (primary model only) ----------
    def chat(self, system: str, messages: list[dict], timeout: int = 60) -> str:
        """Blocking call. Raises RuntimeError with friendly message on failure."""
        self._require_deps()
        try:
            text = self._chat_once(self.model, system, messages, timeout)
            self.active_model = self.model
            self.last_error = ""
            return text
        except Exception as e:
            friendly = self._friendly_error(e)
            self.last_error = friendly
            raise RuntimeError(friendly) from e

    # ---------- vision call (screenshot understanding) ----------
    def chat_vision(self, model: str, system: str, question: str,
                    image_b64: str, timeout: int = 90) -> str:
        """Single vision attempt. Raises RuntimeError (retryable unless 401)."""
        self._require_deps()
        import requests
        try:
            r = requests.post(
                self.base_url + "/chat/completions",
                headers=self._headers(),
                json={"model": model,
                      "max_tokens": 400,
                      "temperature": 0.3,
                      "messages": [
                          {"role": "system", "content": system},
                          {"role": "user", "content": [
                              {"type": "text", "text": question},
                              {"type": "image_url", "image_url": {
                                  "url": f"data:image/jpeg;base64,{image_b64}"}}]}]},
                timeout=max(10, int(timeout)))
        except Exception as e:
            raise RuntimeError(f"Vision request failed: {e}.") from e
        if r.status_code == 200:
            try:
                text = ((r.json().get("choices") or [{}])[0]
                        .get("message", {}).get("content", "") or "").strip()
            except Exception:
                text = ""
            if not text:
                raise RuntimeError("Vision returned an empty response.")
            return text
        raise RuntimeError(f"HTTP {r.status_code}: {(r.text or '')[:150]}")

    # ---------- auto-switch call ----------
    def chat_with_fallback(self, system: str, messages: list[dict],
                           models: list[str], timeout: int = 60,
                           max_attempts: int = 4, on_try=None) -> tuple[str, str]:
        """Try models in order (up to max_attempts); return (reply, used_model).

        on_try(model_id, attempt_no) is called before each attempt so the
        GUI can show live progress instead of a frozen "Thinking...".
        401/invalid-key fails fast (switching models won't help).
        Rate limits / missing / overloaded models auto-switch to next.
        Raises RuntimeError if every tried model failed.
        """
        self._require_deps()
        tried: list[str] = []
        last_err: Exception | None = None
        queue = list(dict.fromkeys(
            [x for x in (models or [self.model]) if x]))[:max(1, max_attempts)]
        for n, m in enumerate(queue, 1):
            if on_try:
                try:
                    on_try(m, n)
                except Exception:
                    pass
            try:
                text = self._chat_once(m, system, messages, timeout)
                self.active_model = m
                self.model = m  # remember the working model
                self.last_error = ""
                return text, m
            except Exception as e:
                last_err = e
                tried.append(f"{m} ({self._short_error(e)})")
                if not self._retryable(e):
                    break
        friendly = self._friendly_error(last_err) if last_err else "AI request failed."
        # Production: keep model names/technical detail out of user messages.
        self.last_error = friendly
        raise RuntimeError(self.last_error)

    # ---------- error helpers ----------
    @staticmethod
    def _retryable(e: Exception) -> bool:
        msg = str(e).lower()
        if "401" in msg or "invalid" in msg or "unauthorized" in msg or "forbidden" in msg:
            return False  # bad key — fail fast
        return True  # 404/429/402/5xx/timeout/connect → try next model

    @staticmethod
    def _short_error(e: Exception) -> str:
        msg = str(e)
        for code in ("429", "404", "402", "400", "500", "502", "503", "529"):
            if code in msg:
                return f"HTTP {code}"
        low = msg.lower()
        if "timeout" in low or "timed out" in low:
            return "timeout"
        if "connect" in low:
            return "connect error"
        if "rate" in low and "limit" in low:
            return "rate-limited"
        return msg[:80]

    def _friendly_error(self, e: Exception | None) -> str:
        # Production: never expose providers, keys, or technical detail.
        msg = str(e) if e else ""
        low = msg.lower()
        if "401" in msg or "invalid" in low or "unauthorized" in low:
            friendly = "AI engine authentication failed. Please restart the app."
        elif "connect" in low or "timeout" in low or "timed out" in low or "dns" in low:
            friendly = "I couldn't reach the AI engine. Please check your internet connection."
        elif "429" in msg or "rate" in low:
            friendly = "The AI engine is busy right now. Please try again in a bit."
        else:
            friendly = "Something went wrong with the AI engine. Please try again."
        return friendly

    # ---------- offline fallback ----------
    @staticmethod
    def offline_reply(user_text: str) -> str:
        """Used when the engine is unreachable — generic, no tech detail."""
        low = user_text.lower().strip()
        if low in ("hi", "hello", "hey", "hey nova"):
            return "Hey! I'm listening."
        if "what can you do" in low:
            return ("I can chat, remember things, open apps and websites, "
                    "search the web, take screenshots, check system info, "
                    "and manage reminders.")
        if "time" in low:
            from datetime import datetime
            return datetime.now().strftime("It's %I:%M %p on %A, %B %d.")
        return "I'm having trouble thinking right now. Please try again in a moment."
