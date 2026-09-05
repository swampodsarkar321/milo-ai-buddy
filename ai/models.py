"""OpenRouter free-model discovery + ordering (no Qt dependency).

- Fetches the LIVE model list from OpenRouter (free models change often,
  so hardcoding alone goes stale).
- Filters to free models (`:free` id suffix or zero pricing).
- Orders them by a preference list (strong models first), then the rest.
- Caches to data/models_cache.json; refresh runs in a background thread
  so the GUI never freezes.

Used by: Settings "Load free models" button, startup background refresh,
and the LLM auto-switch chain in ai/llm.py.
"""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Strong free models first (checked against the live list at runtime —
# entries missing from OpenRouter are simply skipped).
PREFERRED_FREE = [
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
    "minimax/minimax-m3:free",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-ultra-550b-a55b:free",
    "google/gemma-4-31b-it:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "google/gemma-4-26b-a4b-it:free",
    "thinkingmachines/inkling:free",
    "thinkingmachines/inkling-small:free",
    "poolside/laguna-s-2.1:free",
    "inclusionai/ling-3.0-flash-fin:free",
    "nvidia/nemotron-3.5-lightning:free",
    "minimax/minimax-m2.7:free",
    "poolside/laguna-xs-2.1:free",
    "liquid/lfm-2.5-2.6b:free",
    "dots-studio/dots-3-note-preview:free",
    "cohere/north-mini-code:free",
    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
]

# Non-chat models (audio/music, routers) — usable only as last resort.
DEPRIORITIZED = [
    "google/lyria-3-pro-preview",
    "google/lyria-3-clip-preview",
    "nvidia/nemotron-3.5-content-safety:free",
    "openrouter/free",
]


def _is_free(m: dict) -> bool:
    mid = str(m.get("id", ""))
    if mid.endswith(":free"):
        return True
    try:
        pricing = m.get("pricing") or {}
        vals = [float(pricing.get(k, 1) or 0)
                for k in ("prompt", "completion")]
        return all(v == 0 for v in vals)
    except Exception:
        return False


def fetch_openrouter_models(api_key: str = "", timeout: int = 12) -> list[dict]:
    """Live GET /models. Returns [{'id','name'}] for free models. Raises on failure."""
    import requests
    headers = {"User-Agent": "NOVA-Voice-Partner/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=timeout)
    r.raise_for_status()
    data = r.json().get("data", [])
    out = []
    for m in data:
        if _is_free(m):
            out.append({"id": m.get("id", ""),
                        "name": m.get("name") or m.get("id", "")})
    # de-dupe, keep order
    seen, uniq = set(), []
    for m in out:
        if m["id"] and m["id"] not in seen:
            seen.add(m["id"])
            uniq.append(m)
    return uniq


def order_free_models(live: list[dict]) -> list[dict]:
    """Preference-list order first, then remaining chat models alphabetically,
    deprioritized (audio/router) models last."""
    by_id = {m["id"]: m for m in live}
    ordered = [by_id[i] for i in PREFERRED_FREE if i in by_id]
    used = {m["id"] for m in ordered} | set(DEPRIORITIZED)
    rest = sorted([m for m in live if m["id"] not in used],
                  key=lambda m: m["id"])
    tail = [by_id[i] for i in DEPRIORITIZED if i in by_id]
    return ordered + rest + tail


# ---------------- vision-capable free models ----------------

VISION_CACHE = "vision_models.json"


def fetch_vision_models(api_key: str = "", timeout: int = 12) -> list[dict]:
    """Free models whose input modality includes images. Raises on failure."""
    import requests
    headers = {"User-Agent": "NOVA-Voice-Partner/1.0"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    r = requests.get(OPENROUTER_MODELS_URL, headers=headers, timeout=timeout)
    r.raise_for_status()
    out = []
    for m in r.json().get("data", []):
        if not _is_free(m):
            continue
        try:
            arch = m.get("architecture") or {}
            mods = arch.get("input_modalities") or arch.get("modality") or ""
            if "image" not in str(mods).lower():
                continue
        except Exception:
            continue
        out.append({"id": m.get("id", ""), "name": m.get("name") or m.get("id", "")})
    seen, uniq = set(), []
    for x in out:
        if x["id"] and x["id"] not in seen:
            seen.add(x["id"])
            uniq.append(x)
    # prefer small/fast vision models first
    def _rank(mid: str) -> int:
        low = mid.lower()
        for i, key in enumerate(("flash", "mini", "haiku", "4o-mini", "gemma",
                                 "qwen", "llama", "mistral", "kimi")):
            if key in low:
                return i
        return 99
    return sorted(uniq, key=lambda m: _rank(m["id"]))


# ---------------- startup best-node probe ----------------

PROBE_MESSAGE = "Reply with exactly: OK"
PROBE_TIMEOUT = 10      # seconds per candidate (free tier: slow = skip)
PROBE_TOP_N = 4         # only speed-test the top candidates (cheap)
CACHE_FRESH_S = 1800    # skip re-probe if cache newer than 30 min


def probe_latency(model_id: str, api_key: str,
                  base_url: str = "https://openrouter.ai/api/v1",
                  timeout: int = PROBE_TIMEOUT) -> float | None:
    """One tiny chat call. Returns seconds on success, None on failure.

    Uses plain `requests` (no heavy deps). Burns ~10 tokens per probe.
    """
    import requests
    t0 = time.time()
    try:
        r = requests.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {api_key}",
                     "HTTP-Referer": "https://github.com/nova-voice-partner",
                     "X-Title": "NOVA Voice Partner",
                     "Content-Type": "application/json"},
            json={"model": model_id, "max_tokens": 5, "temperature": 0,
                  "messages": [{"role": "user", "content": PROBE_MESSAGE}]},
            timeout=timeout)
        if r.status_code != 200:
            return None
        text = ((r.json().get("choices") or [{}])[0].get("message", {})
                .get("content", "") or "")
        if "OK" not in text.upper():
            return None
        return time.time() - t0
    except Exception:
        return None


def probe_best(candidate_ids: list[str], api_key: str,
               base_url: str = "https://openrouter.ai/api/v1",
               timeout: int = PROBE_TIMEOUT) -> list[tuple[str, float]]:
    """Speed-test candidates CONCURRENTLY. Returns [(model_id, seconds)]
    for workers that answered, fastest first. Silent background use."""
    from concurrent.futures import ThreadPoolExecutor
    if not candidate_ids:
        return []
    results: dict[str, float] = {}

    def _one(mid: str):
        lat = probe_latency(mid, api_key, base_url, timeout)
        if lat is not None:
            results[mid] = lat

    with ThreadPoolExecutor(max_workers=min(6, len(candidate_ids))) as ex:
        list(ex.map(_one, candidate_ids))
    return sorted(results.items(), key=lambda kv: kv[1])


class ModelManager:
    """Cache + background refresh for the free-model list."""

    COOLDOWN_S = 300  # recently-failed models go last for 5 minutes

    def __init__(self, cache_path: str | Path):
        self.cache_path = Path(cache_path)
        self._lock = threading.Lock()
        self.models: list[dict] = []
        self.best: str = ""          # last probed best-node id
        self.latencies: dict[str, float] = {}
        self.updated_at: float = 0.0
        self._load_all()
        if not self.models:
            self.models = [{"id": i, "name": i} for i in PREFERRED_FREE[:4]]
        self._fail_until: dict[str, float] = {}

    # ----- cache -----
    def _load_all(self) -> None:
        """Load models + best-node + latencies (accepts old bare-list format)."""
        try:
            raw = json.loads(self.cache_path.read_text(encoding="utf-8"))
            items = raw.get("models") if isinstance(raw, dict) else raw
            if isinstance(items, list):
                self.models = [m for m in items
                               if isinstance(m, dict) and m.get("id")]
            if isinstance(raw, dict):
                self.best = str(raw.get("best", "") or "")
                self.updated_at = float(raw.get("updated_at", 0) or 0)
                lat = raw.get("latencies", {})
                if isinstance(lat, dict):
                    self.latencies = {k: float(v) for k, v in lat.items()}
        except Exception:
            pass

    def load_cached(self) -> list[dict]:
        with self._lock:
            return list(self.models)

    def _save(self, models: list[dict] | None = None) -> None:
        try:
            with self._lock:
                payload = {"updated_at": time.time(),
                           "best": self.best,
                           "latencies": self.latencies,
                           "models": models if models is not None else self.models}
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.cache_path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        except Exception:
            pass

    # ----- refresh -----
    def refresh(self, api_key: str = "") -> list[dict]:
        """Blocking refresh (call from a worker thread, never the GUI thread)."""
        live = fetch_openrouter_models(api_key)
        ordered = order_free_models(live)
        with self._lock:
            self.models = ordered
            if self.best and self.best not in {m["id"] for m in ordered}:
                self.best = ""  # cached best no longer free
        self._save(ordered)
        return ordered

    def cache_is_fresh(self) -> bool:
        """True when we probed recently — reuse best instantly, skip network."""
        return bool(self.best) and (time.time() - self.updated_at) < CACHE_FRESH_S

    # ----- startup warm-up: pick the actual best node -----
    def warm_up(self, api_key: str = "",
                base_url: str = "https://openrouter.ai/api/v1",
                top_n: int = PROBE_TOP_N,
                timeout: int = PROBE_TIMEOUT) -> str:
        """Refresh list + speed-test top candidates concurrently.

        Reorders the catalogue so the fastest WORKING node is first,
        remembers it as `best` (persisted). Returns best id or "".
        Skips the probe entirely when the cache is fresh (<30 min).
        Blocking — always call from a background thread.
        """
        if self.cache_is_fresh():
            return self.best
        try:
            self.refresh(api_key)
        except Exception:
            pass  # offline: fall back to cached list below
        with self._lock:
            candidates = [m["id"] for m in self.models[:top_n]]
        ranked = probe_best(candidates, api_key, base_url, timeout)
        with self._lock:
            if ranked:
                self.latencies.update(dict(ranked))
                winners = [mid for mid, _ in ranked]
                by_id = {m["id"]: m for m in self.models}
                rest = [m for m in self.models if m["id"] not in set(winners)]
                self.models = [by_id[w] for w in winners if w in by_id] + rest
                self.best = winners[0]
                self._save()
                return self.best
            # all probes failed: keep previous best if still listed
            if self.best and self.best in {m["id"] for m in self.models}:
                return self.best
            return ""

    def refresh_background(self, api_key: str = "",
                           on_done=None, on_error=None) -> threading.Thread:
        """Fetch in a daemon thread; callbacks receive (models) / (error str)."""
        def _run():
            try:
                models = self.refresh(api_key)
                if on_done:
                    on_done(models)
            except Exception as e:
                if on_error:
                    on_error(str(e)[:200])
        t = threading.Thread(target=_run, daemon=True)
        t.start()
        return t

    def ordered_ids(self) -> list[str]:
        with self._lock:
            return [m["id"] for m in self.models]

    # ----- failure cooldown (session-only) -----
    def note_failure(self, model_id: str) -> None:
        with self._lock:
            self._fail_until[model_id] = time.time() + self.COOLDOWN_S

    def note_success(self, model_id: str) -> None:
        with self._lock:
            self._fail_until.pop(model_id, None)

    def in_cooldown(self, model_id: str) -> bool:
        with self._lock:
            until = self._fail_until.get(model_id, 0)
            if until and until > time.time():
                return True
            self._fail_until.pop(model_id, None)
            return False

    def build_chain(self, primary: str = "") -> list[str]:
        """Auto-switch order: primary first (unless cooling down),
        then healthy cached models, recently-failed ones last."""
        ids = self.ordered_ids()
        chain = []
        if primary:
            chain.append(primary)
        for i in ids:
            if i not in chain:
                chain.append(i)
        healthy = [m for m in chain if not self.in_cooldown(m)]
        cooled = [m for m in chain if m not in healthy]
        return healthy + cooled
