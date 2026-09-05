"""NOVA orchestrator: text in -> (memory + LLM + tools) -> spoken reply.

GUI-agnostic: the GUI runs `handle_text()` inside a QThread worker and
calls `speak()` separately so the interface never freezes.
All public methods return dicts and never raise.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

from ai.llm import LLMClient
from ai.models import ModelManager
from ai.tools import parse_tool_call, tools_prompt_text
from config import DATA_DIR
from core.conversation import Conversation
from core.personality import (IDENTITY_BN, IDENTITY_EN, build_system_prompt,
                                is_bangla)
from memory.conversation_memory import ConversationMemory
from memory.memory_manager import MemoryManager
from memory.routines import RoutineTracker
from voice.listener import Listener
from memory.conversation_memory import ConversationMemory
from memory.memory_manager import MemoryManager
from memory.routines import RoutineTracker
from tools import browser as browser_tools
from tools import files as file_tools
from tools import pc as pc_tools
from tools import system as system_tools
from tools import vision as vision_tools
from tools.reminders import ReminderStore, parse_reminder_time
from tools.screenshot import take_screenshot
from tools.todo import TodoStore


CONFIRM_TOOLS = {"shutdown_pc", "restart_pc", "sleep_pc", "sign_out"}
CONFIRM_LABELS = {
    "shutdown_pc": "shut the PC down",
    "restart_pc": "restart the PC",
    "sleep_pc": "put the PC to sleep",
    "sign_out": "sign out of Windows",
}
YES_WORDS = {"yes", "yeah", "yep", "confirm", "confirmed", "ok", "okay",
             "yes please", "do it", "ha", "haan", "ji", "korun", "koren",
             "thik ache", "thik achhe", "accha", "hmm", "sure"}
NO_WORDS = {"no", "nope", "cancel", "na", "nah", "bad dao", "bad daw",
            "thak", "thakuk", "lagbe na"}


class Assistant:
    def __init__(self, config, db):
        self.config = config
        self.db = db
        self.memory = MemoryManager(db, enabled=config.privacy.memory_enabled)
        self.conv_memory = ConversationMemory(db)
        self.conversation = Conversation()
        self.reminders = ReminderStore(db)
        self.todos = TodoStore(db)
        self.pending = None  # confirm-gated action: {"tool","args","label"}
        self._last_felt = ""  # session sentiment dedupe
        self.routines = RoutineTracker(db, enabled=config.privacy.memory_enabled
                                       and getattr(config.privacy, "routines", True))
        self.llm = LLMClient(
            api_key=config.ai.api_key, base_url=config.ai.base_url,
            model=config.ai.model, temperature=config.ai.temperature,
            max_tokens=config.ai.max_tokens, provider=config.ai.provider,
        )
        # Free-model catalogue for OpenRouter auto-switch (cached; refreshed
        # in background by the GUI so chat never blocks on it).
        self.models = ModelManager(DATA_DIR / "models_cache.json")
        if self._is_openrouter() and self.models.best:
            # instant best-node from last probe until the fresh probe finishes
            self.llm.model = self.models.best
        # restore recent chat log into the short-term buffer
        for row in self.conv_memory.recent(20):
            if row["role"] == "user":
                self.conversation.add_user(row["text"])
            else:
                self.conversation.add_assistant(row["text"])

    # ---------- settings hot-reload ----------
    def reload_config(self, config) -> None:
        self.config = config
        self.memory.enabled = config.privacy.memory_enabled
        self.routines.enabled = config.privacy.memory_enabled \
            and getattr(config.privacy, "routines", True)
        self.llm.reconfigure(api_key=config.ai.api_key, base_url=config.ai.base_url,
                             model=config.ai.model, temperature=config.ai.temperature,
                             max_tokens=config.ai.max_tokens,
                             provider=config.ai.provider)

    # ---------- main entry ----------
    def handle_text(self, user_text: str, on_model_try=None) -> dict:
        """Process one user message. Returns {'reply', 'tool', 'tool_result'}.

        on_model_try(model_id, attempt_no) — optional progress callback
        fired before each LLM attempt (used by the GUI status line).
        """
        user_text = (user_text or "").strip()
        if not user_text:
            return {"reply": "I didn't catch that. Could you say it again?",
                    "tool": None, "tool_result": None}
        try:
            # 0) Pending confirmation first ("Shutting down… say yes")
            if self.pending:
                settled = self._settle_confirm(user_text)
                if settled:
                    return settled
            # 0b) Human touch: remember how they feel (once per mood/session)
            felt = self.sense_mood(user_text)
            if felt and felt != self._last_felt and self.memory.enabled:
                self._last_felt = felt
                try:
                    from datetime import datetime as _dt
                    self.memory.save_memory(
                        f"User seemed {felt} ({_dt.now().strftime('%b %d')}).",
                        key=f"mood-{felt}", category="mood")
                except Exception:
                    pass
            # 1) Fast local paths (no LLM needed, work offline)
            local = self._local_commands(user_text)
            if local:
                self._log_turn(user_text, local["reply"])
                self.routines.log(user_text, local.get("tool"))
                return local

            # 2) Auto-learn "remember ..." statements
            learned = self.memory.maybe_learn(user_text)
            if learned and self._is_pure_memory_statement(user_text):
                reply = "Got it. I'll remember that."
                self._log_turn(user_text, reply)
                return {"reply": reply, "tool": None, "tool_result": None}

            # 3) LLM path (or offline fallback)
            if not self.llm.configured:
                reply = self._offline_answer(user_text)
                self._log_turn(user_text, reply)
                return {"reply": reply, "tool": None, "tool_result": None}

            system = build_system_prompt(
                name=self.config.personality.name,
                traits=f"{self.config.personality.traits} {self.config.personality.style}",
                memories_text=self.memory.format_for_prompt(user_text),
                history_text=self.conversation.as_prompt_text(),
                tools_text=tools_prompt_text(),
            )
            messages = [{"role": t.role, "content": t.text}
                        for t in self.conversation.all()[-10:]]
            messages.append({"role": "user", "content": user_text})
            used_model = self.llm.model
            if self.config.ai.auto_switch and self._is_openrouter():
                # Best-model auto-switch: primary first, then cached free
                # models + any user fallbacks, first success wins.
                chain = self.models.build_chain(self.llm.model)
                for extra in self._extra_fallbacks():
                    if extra not in chain:
                        chain.append(extra)
                timeout = int(getattr(self.config.ai, "request_timeout", 45) or 45)
                attempts = int(getattr(self.config.ai, "max_attempts", 4) or 4)
                tried: list[str] = []

                def _try_cb(mid: str, n: int, _cb=on_model_try):
                    tried.append(mid)
                    if _cb:
                        _cb(mid, n)

                try:
                    raw, used_model = self.llm.chat_with_fallback(
                        system, messages, chain, timeout=timeout,
                        max_attempts=attempts, on_try=_try_cb)
                finally:
                    # cooldown: every tried model except the winner goes
                    # last next time (also covers the all-failed case).
                    for mid in tried:
                        if mid != self.llm.active_model:
                            self.models.note_failure(mid)
                self.models.note_success(used_model)
            else:
                raw = self.llm.chat(system, messages)

            # 4) Tool call? (multi-step agent: up to 3 rounds)
            call = parse_tool_call(raw)
            if call:
                return self._agent_run(user_text, system, messages, call)

            self._log_turn(user_text, raw)
            return {"reply": raw, "tool": None, "tool_result": None,
                    "model": used_model}

            self._log_turn(user_text, raw)
            raw = self.human_filler(user_text, raw)
            return {"reply": raw, "tool": None, "tool_result": None,
                    "model": used_model}
        except RuntimeError as e:
            # friendly LLM/network errors
            reply = str(e)
            self._log_turn(user_text, reply)
            return {"reply": reply, "tool": None, "tool_result": None}
        except Exception as e:
            reply = f"Something went wrong: {e}"
            return {"reply": reply, "tool": None, "tool_result": None}

    # ---------- confirmation gate (dangerous actions) ----------
    def _settle_confirm(self, user_text: str) -> dict | None:
        """Resolve a pending confirm. Returns a result dict, or None to
        treat the text as a brand-new request (pending dropped)."""
        low = " ".join(user_text.lower().strip().split())
        job = self.pending or {}
        if low in YES_WORDS:
            self.pending = None
            result = self._run_tool(job.get("tool", ""), job.get("args", {}))
            reply = result.get("message", "Done.")
            self._log_turn(user_text, reply)
            self.routines.log(user_text, job.get("tool"))
            return {"reply": reply, "tool": job.get("tool"), "tool_result": result}
        if low in NO_WORDS:
            self.pending = None
            reply = "Okay, cancelled."
            self._log_turn(user_text, reply)
            return {"reply": reply, "tool": None, "tool_result": None}
        self.pending = None  # anything else starts fresh
        return None

    def _ask_confirm(self, tool: str, args: dict) -> dict:
        label = CONFIRM_LABELS.get(tool, tool)
        self.pending = {"tool": tool, "args": args, "label": label}
        reply = (f"This will {label} and close everything. "
                 "Say 'yes' to confirm, or 'no' to cancel.")
        self._log_turn(f"[confirm:{tool}]", reply)
        return {"reply": reply, "tool": tool,
                "tool_result": {"ok": True, "pending_confirm": True}}

    # ---------- multi-step agent ----------
    def _agent_run(self, user_text: str, system: str,
                   messages: list, call: dict) -> dict:
        """Execute tool calls in a loop (max 3), feeding results back to
        the LLM so it can chain steps, then answer. Confirm-gated tools
        stop the loop and ask the user instead."""
        used_model = self.llm.model
        timeout = int(getattr(self.config.ai, "request_timeout", 45) or 45)
        raw, current = call, None
        for _step in range(3):
            tool, args = raw.get("tool", ""), raw.get("args", {})
            if tool in CONFIRM_TOOLS:
                return self._ask_confirm(tool, args)
            result = self._run_tool(tool, args)
            if tool in ("create_timer", "cancel_timer"):
                reply = result.get("message", "Done.")
                self._log_turn(user_text, reply)
                self.routines.log(user_text, tool)
                return {"reply": reply, "tool": tool, "tool_result": result,
                        "model": self.llm.active_model or used_model}
            reply = raw.get("reply") or result.get("message", "Done.")
            if not result.get("ok") and raw.get("reply"):
                reply = result["message"]
            # terminal? if the model gave no further instruction need,
            # ask it whether another step is needed.
            messages = messages + [
                {"role": "assistant", "content": json.dumps(raw)},
                {"role": "user", "content": (
                    f"Tool '{tool}' returned: {result.get('message', '')}. "
                    "If another tool is needed, reply with ONLY the next tool JSON. "
                    "Otherwise give the final short voice answer (no JSON).")},
            ]
            try:
                model = self.llm.active_model or self.llm.model
                nxt = self.llm._chat_once(model, system, messages, timeout)
            except Exception as e:
                self._log_turn(user_text, reply)
                self.routines.log(user_text, tool)
                return {"reply": reply, "tool": tool, "tool_result": result,
                        "model": self.llm.active_model or used_model}
            current = parse_tool_call(nxt)
            if not current:
                nxt = self.human_filler(user_text, nxt)
                self._log_turn(user_text, nxt)
                self.routines.log(user_text, tool)
                return {"reply": nxt, "tool": tool, "tool_result": result,
                        "model": self.llm.active_model or used_model}
            raw = current
        # loop exhausted: answer with the last honest reply
        self._log_turn(user_text, reply)
        self.routines.log(user_text, tool)
        return {"reply": reply, "tool": tool, "tool_result": result,
                "model": self.llm.active_model or used_model}

    # ---------- local (offline) commands ----------
    def _local_commands(self, text: str) -> dict | None:
        low = text.lower().strip()

        # greetings / capabilities (rotating, human variety)
        hellos = ("hey milo", "hello milo", "hi milo", "hey", "hello", "hi",
                  "hey buddy", "hi buddy", "yo", "salam", "salam milo",
                  "assalamualaikum", "adab")
        if low in hellos:
            import random as _r
            pool = ["Yes? I'm listening.", "Hey! What's up?",
                    "I'm here — talk to me.", "Haan, bolo!",
                    "Hey hey! All ears."]
            if is_bangla(text):
                pool = ["Haan, bolo!", "Hey! Ki khobor?",
                        "Achi — bolo ki help lagbe?", "Shunchi, bolo!"]
            reply = _r.choice(pool)
            return {"reply": reply, "tool": None, "tool_result": None}
        if "what can you do" in low:
            return {"reply": ("I can chat, remember things, open apps and websites, "
                              "search the web, take screenshots, check system info, "
                              "and manage reminders."),
                    "tool": None, "tool_result": None}
        # identity: who are you / who made you (Bangla-aware, works offline)
        if re.search(
                r"who are you|your name|who made you|who created you|who built you"
                r"|creator|developer|maker|where are you from|your country"
                r"|tumi ke|tui ke|tomar nam|tumar nam|tomake ke|ke bana|banailo"
                r"|kothakar|kon desh|porichoy",
                low):
            reply = IDENTITY_BN if is_bangla(text) else IDENTITY_EN
            return {"reply": reply, "tool": None, "tool_result": None}
        # memory Q&A works offline: "what sport do i like?"
        if re.search(r"what.*(do i like|is my favori?te|do you remember|is my name)", low):
            hits = self.memory.search_memory(text, 3)
            if hits:
                return {"reply": hits[0]["value"], "tool": None, "tool_result": None}

        # "forget ..." -> delete matching memories (no UI needed)
        m = re.match(r"forget (that )?(.+)", low)
        if m:
            try:
                n = self.memory.delete_matching(m.group(2))
            except Exception:
                n = 0
            reply = "Forgot it." if n else "I couldn't find that memory."
            return {"reply": reply, "tool": None, "tool_result": None}

        # ---- self status (no tech jargon) ----
        if re.search(r"(engine|system) (status|check)|tumi thik acho|status bolo|check yourself", low):
            msg = self.system_status()
            self._log_turn(text, msg)
            return {"reply": msg, "tool": "system_status",
                    "tool_result": {"ok": True}}

        # ---- screen understanding ("ekhane samasya ki?") ----
        if re.search(r"screen|ekhane|what.*(wrong|problem|error)|analyse|analyze|dekho to|dekhao", low) \
                and re.search(r"\?|ki|what|kemon|somossa|problem|wrong|error|dekho|bujh", low):
            if not self.llm.configured:
                reply = "I need a moment — the engine is offline."
                self._log_turn(text, reply)
                return {"reply": reply, "tool": None, "tool_result": None}
            res = vision_tools.ask_screen(text, self.llm)
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "look_at_screen",
                    "tool_result": res}

        # ---- close app ("discord bondho koro" / "close chrome") ----
        m = re.match(r"(?:close|bondho(?: koro| kore dao| kor)?|off koro|kill) (.+)", low)
        if m:
            res = pc_tools.close_application(m.group(1))
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "close_application",
                    "tool_result": res}

        # ---- lock / power (shutdown family asks first) ----
        if re.search(r"\block\b|lock koro|lock kore dao", low):
            res = pc_tools.lock_pc()
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "lock_pc", "tool_result": res}
        if re.search(r"shutdown|shut ?down|pc (off|bondho)|computer (off|bondho)", low):
            return self._ask_confirm("shutdown_pc", {})
        if re.search(r"\brestart\b|reboot|restart koro", low):
            return self._ask_confirm("restart_pc", {})
        if re.search(r"\bsleep\b|ghum(ao| par(ao|o))?|sleep koro|suspend", low):
            return self._ask_confirm("sleep_pc", {})
        if re.search(r"sign ?out|log ?off|signout koro", low):
            return self._ask_confirm("sign_out", {})

        # ---- volume / media ----
        if re.search(r"volume (barao|up|baro)|louder|awaj barao", low):
            res = pc_tools.volume_up()
            return {"reply": res["message"], "tool": "volume_up", "tool_result": res}
        if re.search(r"volume (komao|down|komo)|quieter|awaj komao", low):
            res = pc_tools.volume_down()
            return {"reply": res["message"], "tool": "volume_down", "tool_result": res}
        if re.search(r"\bmute\b|unmute|chup koro|awaj bondho", low):
            res = pc_tools.volume_mute_toggle()
            return {"reply": res["message"], "tool": "volume_mute", "tool_result": res}
        if re.search(r"next (song|track|gaan)|porer gaan|porer ta", low):
            res = pc_tools.media_next()
            return {"reply": res["message"], "tool": "media_next", "tool_result": res}
        if re.search(r"prev(ious)? (song|track|gaan)|ager gaan|ager ta", low):
            res = pc_tools.media_prev()
            return {"reply": res["message"], "tool": "media_prev", "tool_result": res}
        if re.search(r"play|pause|gaan (chalao|thamao|bondho)|media", low) \
                and re.search(r"play|pause|chalao|tham", low):
            res = pc_tools.media_play_pause()
            return {"reply": res["message"], "tool": "media_play_pause",
                    "tool_result": res}

        # ---- countdown timer ("10 minuter timer dao" / "timer 5 minutes") ----
        if "timer" in low or "টাইমার" in text:
            secs = self._parse_timer(text)
            if secs:
                label = re.sub(r"(?i)timer|টাইমার", "", text).strip()[:60] or "Timer"
                res = {"ok": True, "timer_seconds": secs, "timer_label": label,
                       "message": f"Timer set for {self._fmt_dur(secs)}."}
                self._log_turn(text, res["message"])
                return {"reply": res["message"], "tool": "create_timer",
                        "tool_result": res}
            reply = "How long? Say like: '10 minuter timer dao'."
            return {"reply": reply, "tool": None, "tool_result": None}
        if re.search(r"cancel timer|timer (bondho|cancel|off)", low):
            res = {"ok": True, "cancel_timer": True, "message": "Timer cancelled."}
            return {"reply": res["message"], "tool": "cancel_timer",
                    "tool_result": res}

        # ---- todo list ----
        m = re.match(r"(?:todo|to-do)\s+add\s+(.+)|(?:todo|to-do)\s+(.+?)\s+(?:jog|add) koro", low)
        if m:
            item = m.group(1) or m.group(2)
            rid = self.todos.add(item)
            reply = f"Added to-do #{rid}."
            self._log_turn(text, reply)
            return {"reply": reply, "tool": "todo_add",
                    "tool_result": {"ok": True, "id": rid}}
        if re.search(r"my todos|todo (list|gulo|gula)|todos (dekhao|bolo)|to-do list", low):
            items = self.todos.open_items()
            if not items:
                reply = "Your to-do list is empty. Nice!"
            else:
                reply = "To-dos: " + " | ".join(
                    f"{i+1}. {t['text']}" for i, t in enumerate(items[:5]))
            self._log_turn(text, reply)
            return {"reply": reply, "tool": "todo_list",
                    "tool_result": {"ok": True}}
        m = re.match(r"(?:todo|to-do)\s+(?:done\s+)?(\d+)\s*(?:done|shesh|ses|complete)?", low)
        if m or re.search(r"(?:done|shesh|complete)\s+(?:todo|to-do)?\s*(\d+)", low):
            num = int((m and m.group(1)) or re.search(r"(\d+)", low).group(1))
            res = self.todos.done(num)
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "todo_done", "tool_result": res}

        # ---- files ----
        m = re.match(r"(?:find|search)(?: file)?(?: for)? (.+)|(.+?) (?:file|files) (?:khujo|khojo|search koro|ber koro)", low)
        if m:
            q = (m.group(1) or m.group(2) or "").strip()
            res = file_tools.search_files(q)
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "search_files",
                    "tool_result": res}
        m = re.match(r"(?:create|make|ban[ao]o?)(?: a)? folder (.+)|folder (.+?) (?:banao|banan|koro|create koro)", low)
        if m:
            res = file_tools.create_folder((m.group(1) or m.group(2) or "").strip())
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "create_folder",
                    "tool_result": res}
        if re.search(r"organiz|shajao|sajao|guchao|guchiye dao", low) and "download" in low:
            res = file_tools.organize_downloads()
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "organize_downloads",
                    "tool_result": res}
        if re.search(r"(boro|large|biggest|largest|sobcheye boro).*(file|files)|large files", low):
            res = file_tools.list_large_files("", 10)
            self._log_turn(text, res["message"])
            return {"reply": res["message"], "tool": "list_large_files",
                    "tool_result": res}

        # "open <site/app>" (+ Bangla "kholo")
        m = re.match(r"open (.+)", low)
        kh = re.match(r"(.+?)\s+(?:kholo|khulun|khol|open koro|koro open|chalu koro)\s*$", low)
        if m or kh:
            target = (m.group(1) if m else kh.group(1)).strip()
            if any(k in target for k in
                   ("youtube", "google", "facebook", "gmail", "github", "spotify",
                    "netflix", "instagram", "stackoverflow", ".com", ".org", "http")):
                site = target.split()[0]
                res = browser_tools.open_website(site=site, url=target)
                spoken = res["message"] if res["ok"] else res["message"]
                return {"reply": self._shorten_open(spoken, target),
                        "tool": "open_website", "tool_result": res}
            res = browser_tools.open_application(target)
            return {"reply": res["message"], "tool": "open_application", "tool_result": res}

        # "search google/youtube for ..."
        m = re.match(r"search (google|youtube)( for)? (.+)", low)
        if m:
            res = browser_tools.search_web(m.group(3), engine=m.group(1))
            return {"reply": res["message"], "tool": "search_web", "tool_result": res}
        m = re.match(r"(google|youtube) (.+)", low)
        if m and len(low.split()) > 2:
            res = browser_tools.search_web(m.group(2), engine=m.group(1))
            return {"reply": res["message"], "tool": "search_web", "tool_result": res}

        # "go to <site>"
        m = re.match(r"go to (.+)", low)
        if m:
            res = browser_tools.open_website(url=m.group(1))
            return {"reply": res["message"], "tool": "open_website", "tool_result": res}

        if "screenshot" in low or "screen shot" in low:
            res = take_screenshot(save_dir="data")
            return {"reply": res["message"], "tool": "take_screenshot", "tool_result": res}

        if any(k in low for k in ("cpu", "ram", "battery", "disk space", "ip address", "my ip")):
            detail = "all"
            for k in ("cpu", "ram", "battery", "disk", "ip"):
                if k in low:
                    detail = k
                    break
            res = system_tools.get_system_info(detail)
            return {"reply": res["message"], "tool": "get_system_info", "tool_result": res}

        if "what time" in low or "current time" in low or low == "time":
            res = system_tools.get_current_time()
            return {"reply": res["message"], "tool": "get_current_time", "tool_result": res}

        # reminders: "remind me at 8 pm to ..."
        if "remind me" in low:
            due = parse_reminder_time(text)
            reminder_text = re.split(r"remind me( to)?", text, flags=re.I)[-1].strip()
            reminder_text = re.sub(r"^(at|on|tomorrow|today)\b.*?(to|that|about)\s+", "",
                                   reminder_text, flags=re.I).strip() or text
            if due:
                rid = self.reminders.create(reminder_text, due)
                when = datetime.fromtimestamp(due).strftime("%I:%M %p, %b %d")
                return {"reply": f"Reminder set for {when}.",
                        "tool": "create_reminder",
                        "tool_result": {"ok": True, "id": rid}}
            return {"reply": ("When should I remind you? For example: "
                              "'Remind me at 8 PM to call Rahim'."),
                    "tool": None, "tool_result": None}
        return None

    # ---------- tool dispatcher (for LLM tool calls) ----------
    def _run_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "open_website":
                return browser_tools.open_website(url=args.get("url", ""),
                                                  site=args.get("site", ""))
            if name == "search_web":
                return browser_tools.search_web(args.get("query", ""),
                                                args.get("engine", "google"))
            if name == "web_search":
                return browser_tools.web_search_snippets(args.get("query", ""))
            if name == "open_application":
                return browser_tools.open_application(args.get("app", ""))
            if name == "take_screenshot":
                return take_screenshot(save_dir="data")
            if name == "get_system_info":
                return system_tools.get_system_info(args.get("detail", "all"))
            if name == "get_current_time":
                return system_tools.get_current_time()
            if name == "create_reminder":
                return self.reminders.create_from_text(
                    args.get("text", ""),
                    minutes_from_now=float(args.get("minutes_from_now") or 0),
                    due_at_str=args.get("due_at", ""))
            # ---- PC control ----
            if name == "close_application":
                return pc_tools.close_application(args.get("app", ""))
            if name == "lock_pc":
                return pc_tools.lock_pc()
            if name == "shutdown_pc":
                return pc_tools.shutdown_pc()
            if name == "restart_pc":
                return pc_tools.restart_pc()
            if name == "sleep_pc":
                return pc_tools.sleep_pc()
            if name == "sign_out":
                return pc_tools.sign_out()
            if name == "volume_up":
                return pc_tools.volume_up()
            if name == "volume_down":
                return pc_tools.volume_down()
            if name == "volume_mute":
                return pc_tools.volume_mute_toggle()
            if name == "media_next":
                return pc_tools.media_next()
            if name == "media_prev":
                return pc_tools.media_prev()
            if name == "media_play_pause":
                return pc_tools.media_play_pause()
            # ---- files ----
            if name == "search_files":
                return file_tools.search_files(args.get("query", ""),
                                               args.get("folder", ""))
            if name == "create_folder":
                return file_tools.create_folder(args.get("name", ""),
                                                args.get("where", ""))
            if name == "rename_path":
                return file_tools.rename_path(args.get("src", ""),
                                              args.get("new_name", ""))
            if name == "copy_path":
                return file_tools.copy_path(args.get("src", ""),
                                            args.get("dest_folder", ""))
            if name == "move_path":
                return file_tools.move_path(args.get("src", ""),
                                            args.get("dest_folder", ""))
            if name == "list_large_files":
                try:
                    top = int(args.get("top", 10))
                except Exception:
                    top = 10
                return file_tools.list_large_files(args.get("folder", ""), top)
            if name == "organize_downloads":
                return file_tools.organize_downloads()
            if name == "read_text_file":
                return file_tools.read_text_file(args.get("path", ""))
            # ---- vision ----
            if name == "look_at_screen":
                return vision_tools.ask_screen(
                    args.get("question", "What is on the screen?"), self.llm)
            # ---- todo ----
            if name == "todo_add":
                rid = self.todos.add(args.get("text", ""))
                return {"ok": True, "message": f"Added to-do #{rid}.", "id": rid}
            if name == "todo_list":
                items = self.todos.open_items()
                if not items:
                    return {"ok": True, "message": "Your to-do list is empty. Nice!"}
                lines = [f"{i+1}. {t['text']}" for i, t in enumerate(items)]
                return {"ok": True, "message": "To-dos: " + " | ".join(lines[:5])}
            if name == "todo_done":
                try:
                    num = int(args.get("num", 1))
                except Exception:
                    num = 1
                return self.todos.done(num)
            # ---- timer (GUI executes; marker result) ----
            if name == "create_timer":
                try:
                    secs = int(float(args.get("seconds", 600)))
                except Exception:
                    secs = 600
                secs = max(5, min(secs, 12 * 3600))
                label = (args.get("label", "") or "Timer").strip()[:60]
                return {"ok": True, "timer_seconds": secs, "timer_label": label,
                        "message": f"Timer set for {self._fmt_dur(secs)}."}
            if name == "cancel_timer":
                return {"ok": True, "cancel_timer": True,
                        "message": "Timer cancelled."}
            if name == "system_status":
                return {"ok": True, "message": self.system_status()}
            return {"ok": False, "message": f"Unknown tool: {name}"}
        except Exception as e:
            return {"ok": False, "message": f"Tool '{name}' failed: {e}"}

    BN_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")

    @classmethod
    def _parse_timer(cls, text: str) -> int | None:
        """'10 minuter timer dao' / 'timer 5 minutes' / '৩০ সেকেন্ড টাইমার' -> seconds."""
        t = text.translate(cls.BN_DIGITS).lower()
        m = re.search(r"(\d+)\s*(seconds?|sekend|minutes?|minit|hours?|ghonta|hr)", t)
        if not m:
            # Bangla words without latin unit
            m = re.search(r"(\d+)\s*(সেকেন্ড|মিনিট|ঘণ্টা|ঘন্টা)", text)
            if not m:
                return None
            unit = m.group(2)
            n = int(m.group(1).translate(cls.BN_DIGITS))
            mult = 3600 if "ঘণ" in unit or "ঘন" in unit else 60 if "মিন" in unit else 1
            return max(5, min(n * mult, 12 * 3600))
        n, unit = int(m.group(1)), m.group(2)
        mult = 3600 if unit.startswith(("hour", "ghonta", "hr")) else 60 \
            if unit.startswith(("minute", "minit", "min")) else 1
        return max(5, min(n * mult, 12 * 3600))

    @staticmethod
    def _fmt_dur(secs: int) -> str:
        if secs < 60:
            return f"{secs} seconds"
        if secs < 3600:
            m = secs // 60
            return f"{m} minute{'s' if m != 1 else ''}"
        h = secs // 3600
        return f"{h} hour{'s' if h != 1 else ''}"

    def system_status(self) -> str:
        """Self-diagnostics in plain words (no tech jargon). Never raises."""
        parts = []
        try:
            parts.append("AI engine ready." if self.llm.configured
                         else "AI engine offline.")
        except Exception:
            pass
        try:
            ok, _ = Listener.check_available()
            parts.append("Microphone ready." if ok else "No microphone found.")
        except Exception:
            pass
        try:
            n = len(self.memory.all_memories())
            parts.append(f"{n} memories kept." if n else "Memory empty.")
        except Exception:
            pass
        try:
            import socket
            socket.create_connection(("8.8.8.8", 53), timeout=3).close()
            parts.append("Internet connected.")
        except Exception:
            parts.append("No internet.")
        try:
            info = system_tools.get_system_info("all")
            if info.get("ok"):
                parts.append(info["message"])
        except Exception:
            pass
        return " ".join(parts) if parts else "Status check failed."

    # ---------- helpers ----------
    MOOD_WORDS = {
        "tired": ("tired", "klanto", "ghum", "sleepy", "exhausted", "rest"),
        "sad": ("sad", "mon kharap", "kharap lagche", "upset", "depressed",
                "kanna", "crying", "lonely"),
        "happy": ("happy", "khushi", "moja", "excited", "great news", "awesome day",
                  "congrat", "utt ejito", "anondo"),
        "sick": ("sick", "oshustho", "jor", "fever", "doctor", "hospital", "pain"),
        "busy": ("busy", "besto", "chap", "deadline", "tension", "stressed", "pressure"),
    }

    @classmethod
    def sense_mood(cls, text: str) -> str:
        low = (text or "").lower()
        for mood, words in cls.MOOD_WORDS.items():
            if any(w in low for w in words):
                return mood
        return ""

    @staticmethod
    def human_filler(text: str, reply: str) -> str:
        """Rare conversational softener (chat answers only, ~1 in 6)."""
        import random as _r
        if len(reply) < 40 or reply.rstrip().endswith("?"):
            return reply
        if _r.random() > 0.17:
            return reply
        if is_bangla(text):
            return _r.choice(["Achha, ", "Hmm, ", "Dekho, "]) + reply
        return _r.choice(["Hmm, ", "Well, ", "Honestly, "]) + reply

    @staticmethod
    def is_thanks(text: str) -> bool:
        low = (text or "").lower()
        return any(k in low for k in (
            "thank", "thx", "dhonnobad", "dhonyobad", "shukriya",
            "kritoggo", "thanks a lot", "thank you"))

    def get_user_name(self) -> str:
        """First name from remembered profile ('my name is X'), else ''."""
        try:
            for m in self.memory.search_memory("my name is", 5):
                low = m.get("value", "").lower()
                if "my name is" in low:
                    name = m["value"][low.index("my name is") + 10:].strip()
                    name = name.split()[0].strip(".,!?\"'") if name else ""
                    if name:
                        return name[:20]
        except Exception:
            pass
        return ""

    def _is_openrouter(self) -> bool:
        return (self.config.ai.provider or "").lower() == "openrouter" \
            or "openrouter" in (self.config.ai.base_url or "").lower()

    def _extra_fallbacks(self) -> list[str]:
        raw = (self.config.ai.fallback_models or "")
        return [m.strip() for m in raw.replace("\n", ",").split(",") if m.strip()]

    def _offline_answer(self, user_text: str) -> dict | str:
        low = user_text.lower()
        # memory recall still works offline
        if "remember" not in low and ("?" in user_text or "what" in low or "who" in low):
            hits = self.memory.search_memory(user_text, 3)
            if hits:
                return hits[0]["value"]
        return LLMClient.offline_reply(user_text)

    def _is_pure_memory_statement(self, text: str) -> bool:
        low = text.lower()
        return (low.startswith("remember")
                or "my favorite" in low or "my favourite" in low
                or "my name is" in low)

    @staticmethod
    def _shorten_open(message: str, target: str) -> str:
        # UX rule: "Opening YouTube." not a paragraph.
        name = target.strip().split()[0].capitalize()
        if "http" in message or "opened" in message.lower():
            return f"Opening {name}."
        return message

    def _log_turn(self, user_text: str, reply: str) -> None:
        self.conversation.add_user(user_text)
        self.conversation.add_assistant(reply)
        try:
            self.conv_memory.log("user", user_text)
            self.conv_memory.log("assistant", reply)
        except Exception:
            pass
