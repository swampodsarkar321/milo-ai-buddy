# Milo — AI Voice Partner (Windows, Python)

Friendly voice-first desktop assistant: talk → Whisper STT → LLM → edge-tts voice,
with SQLite memory, reminders, and safe computer control. Dark modern PySide6 GUI.

## Quick start (Windows)

```bat
cd nova_assistant
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
:: edit .env and put your OPENAI_API_KEY=
python main.py
```

> First run downloads a Whisper model (~500MB for `small`) — needs internet once.
> Without an API key NOVA still runs in **offline mode** (local commands +
> memory Q&A work; chat answers are limited).

For OpenRouter / Ollama / LM Studio, set `LLM_BASE_URL` / `LLM_MODEL` /
`LLM_PROVIDER` in `.env` (engine config lives outside the UI by design).

## OpenRouter free models + auto-switch (built in, silent)

`.env` already points at OpenRouter (`https://openrouter.ai/api/v1`).
In background after startup, NOVA will:

1. Fetch the **live free-model list** (`GET /models`, cached to
   `data/models_cache.json`) — free models rotate, so this is live, not hardcoded.
2. Speed-test the top candidates and lock in the fastest working node.
3. On every chat, try best → next free model on 404/429/overload/timeout
   (**auto-switch**, max 3 tries, 20s each; bad-key 401 fails fast).
4. Recently-failed models cool down for 5 minutes; the UI never shows
   model names — only a generic "Thinking…".

`ai/models.py` (`ModelManager`) and `LLMClient.chat_with_fallback()`
hold the logic — reusable without the GUI.

## What it does

- 🎤 Push-to-talk + wake word ("Hey Milo", configurable) + typed fallback
- 🗣️ Continued conversation: follow-ups without the wake word (max 2, silence ends it)
- 🧠 OpenAI-compatible LLM with tool calling (JSON contract in `ai/tools.py`)
- 💾 SQLite long-term memory (`Remember that I like football` → recall later)
- ⏰ Reminders + recurring schedules ("protodin sokal 9 tay office",
  "every 2 hours") + countdown timers + to-do list + routine learning
- ♥ Health guard: screen-time tracking, break nudges, Buddy health card
- 🗣️ Bangla/English/Banglish commands ("chrome kholo", "৩০ সেকেন্ড টাইমার")
- 🖥️ Safe tools: open/close apps, lock, volume, media keys, brightness,
  window min/max/switch, Google/YouTube search, screenshot, CPU/RAM/disk/battery/IP,
  time (shutdown family = voice confirm)
- 📁 File tools (profile-scoped, no delete): search, create/rename/copy/move,
  zip/unzip, duplicates, large files, organize Downloads, read text
- 👁️ Screen understanding: "ekhane samasya ki?" → free vision models read
  your screen and answer (tools/vision.py)
- 🧩 Multi-step agent: chains up to 3 tool calls per request automatically
- 🌐 Web snippets via DuckDuckGo (no key) for current info
- 🎨 Dark/light theme, accent colour, multiple TTS voices + Test button
- 👾 Desktop buddy with 13 expressions, hunger engine, speech bubble —
  cursor-tracking eyes, waving arms, sleep cap, 360° spin tricks
  (double-click it), double-click idle show-offs included
- 🧭 Buddy smarts: learns your repeated commands and suggests them at the
  right hour (`memory/routines.py`, toggle in Settings → Privacy)
- 🔔 Buddy awareness: battery / time-of-day / Downloads / Gmail bubbles
  (`core/awareness.py`; Gmail needs `GMAIL_ADDRESS` + `GMAIL_APP_PASSWORD`
  in `.env` — Google app password, never committed)
- 🥇 Buddy-first UX: tap buddy to talk, answers pop in its bubble,
  closing hides to tray while the buddy keeps running

## Project structure

```
main.py  config.py  requirements.txt  .env.example
core/      assistant.py  conversation.py  personality.py  state.py
           awareness.py
ai/        llm.py  prompts.py  tools.py  models.py
voice/     listener.py  speech_to_text.py  text_to_speech.py  wake_word.py
memory/    database.py  memory_manager.py  conversation_memory.py
           routines.py
tools/     browser.py  system.py  screenshot.py  reminders.py
ui/        main_window.py  home.py (activity feed)  buddy.py
           settings.py  widgets.py  theme.py  mascot.py
data/      nova.db  settings.json   (created on first run)
```

Buddy-first product: the visible UI is only Home / Buddy / Settings /
About. Everything else (memory manager, reminders list, tools, history)
is voice- and buddy-driven: say "remember …", "forget …",
"remind me at 8 PM to …", tap the buddy to talk.

## Production mode (white-label)

The product UI exposes **no API/AI details** — no keys, providers, models,
or technical errors anywhere on screen:

- Settings has Voice / Appearance / Personality / Privacy + a read-only
  Engine status dot. All AI config (provider, key, model chain, auto-switch)
  lives in the background via `.env` and `data/models_cache.json`.
- The API key is **never written to `settings.json`** (see `config.save()`),
  never shown, never spoken. Rotate keys server-side as needed.
- All user-facing errors are generic ("AI engine is busy…").
- Branding: set `APP_NAME="My Product"` in `.env` (or `brand.app_name`
  in settings) — window title, home screen, and About update automatically.
- App icon ships in `assets/` (buddy face, `.png` + `.ico`).

## Publish checklist (exe)

1. **Rotate your API key** if it was ever pasted anywhere (OpenRouter dashboard
   → delete key → new key → put it in `.env`). Never ship your `.env` publicly —
   it holds *your* quota. Personal/friends distribution: include your `.env`.
   Public distribution needs per-user keys or your own backend proxy.
2. Fresh install check: `pip install -r requirements.txt` (voice needs
   `faster-whisper` + model download on first run, ~500MB, one time).
3. Build:
   ```bat
   pip install pyinstaller
   pyinstaller --noconsole --onedir --name NOVA --icon assets\icon.ico
     --add-data "assets;assets" --version-file version_info.txt main.py
   ```
   Ship the `dist\NOVA\` folder + your production `.env` next to the exe.
4. First launch downloads the voice model (internet needed once), then the
   buddy probes the fastest free AI node in background — no setup screens.
- **Desktop buddy** (`ui/mascot.py`): a Shimeji/Desktop-Mate style companion —
  frameless always-on-top overlay, painted in code (no assets), roams the
  bottom of the screen, draggable, clickable, 13 expressions (idle, listening,
  thinking, speaking with moving mouth, happy, surprised, sleepy, cry, angry,
  laugh, hungry, munching…), a hunger engine (gets hungry ~every 18 min —
  click to feed), and a floating speech bubble ("Listening…", "Hungry!…").
  Toggle + size: Settings → Desktop buddy. Zero new dependencies.
- To ship a single-file exe: `pip install pyinstaller` then
  `pyinstaller --noconsole --name MyProduct main.py`, and place your
  production `.env` next to the exe (or bake it via your own build step).

## Notes (developer)

- API keys live in `.env` / Settings only — never hardcoded, never in the UI code.
- Destructive actions are confirmation-first; arbitrary shell commands are blocked
  (`open_application` uses a whitelist + `start` fallback, no `shell=True` strings from the AI).
- Every feature in the GUI works or shows a clear "missing package / offline" message —
  the app never crashes on mic/API/TTS failures.
