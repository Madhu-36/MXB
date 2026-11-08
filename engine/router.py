import re
import json
import time
import traceback
from pathlib import Path
from collections import deque
from engine.executor import OSExecutionManager
from engine.tts import VoiceSynthesizer
from engine.memory import memory_bank
from engine.actions_catalog import planner_system_prompt, plan_tool_schema, validate_plan
from engine.llm_client import LLMClient, parse_json_reply
from engine.streaming import ReplyStreamer
from engine.semantic_memory import extract_preference
from engine.scheduler import parse_when, split_leading_time, split_trailing_time
from utils.environment import EnvironmentContext
from utils.math_evaluator import SafeMathEvaluator
from utils.audio_feedback import audio_feedback
from utils.weather import WeatherProbe
from utils.logger import log
from utils.paths import config_path as app_config_path

class IntentRouter:
    """
    Two-Tier Intent Routing Engine for MXB.
    Tier 1: High-Speed Sub-Millisecond Deterministic Fast-Path with fuzzy matching.
    Tier 2: Deep LLM Multi-Step Action Planning and Conversational Reasoning.
    """

    def __init__(self, config_path: str = None, executor = None, tts = None):
        self.executor = executor if executor is not None else OSExecutionManager()
        self.tts = tts if tts is not None else VoiceSynthesizer()
        self.memory = memory_bank
        self.history = deque(maxlen=6)

        # Load config
        self.config_path = Path(config_path) if config_path else app_config_path()
        self.config = self._load_config()
        self.llm = LLMClient(self.config)

    def _load_config(self) -> dict:
        try:
            if self.config_path.exists():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            log.warning(f"Router: Could not read config.json: {e}")
        return {}

    def route(self, transcription: str, feedback_callback=None) -> str:
        text = transcription.lower().strip()
        if not text:
            return "Ignored empty transcription."

        clean_text = re.sub(r'[\.,!\?]+$', '', text).strip()
        # Same text with the user's capitalization, for anything that gets typed or stored.
        original_text = re.sub(r'[\.,!\?]+$', '', transcription.strip()).strip()
        clean_text, original_text = self._strip_politeness(clean_text, original_text)
        log.info(f"IntentRouter: Routing intent for '{clean_text}'")

        # =========================================================================
        # TIER 1: HIGH-SPEED DETERMINISTIC FAST-PATH (Sub-Millisecond)
        # =========================================================================

        # 0. Emergency Voice Interruption (<1ms)
        if clean_text in ["stop", "cancel", "halt", "pause", "abort", "freeze", "stop executing", "cancel action", "shut up"]:
            log.warning("Router: Emergency Voice Interruption Triggered!")
            audio_feedback.play("abort")
            self.executor.abort_current_action()
            reply = "Actions stopped."
            self.tts.speak(reply)
            return f"MXB: {reply}"

        # 0.1. Greetings & Identity Fast-Path (<1ms)
        if clean_text in ["hello", "hi", "hey", "hey mxb", "hello mxb", "welcome", "good morning", "good evening", "good afternoon"]:
            reply = "Hello! MXB executive brain is online and ready for your commands."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}"

        if clean_text in ["who are you", "what are you", "what can you do"]:
            reply = "I am MXB, your AI desktop executive assistant. I can control your mouse, keyboard, windows, apps, files, and read your screen by voice."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}"

        # 0.2. Command History Recall (<1ms)
        if any(p in clean_text for p in ["last command", "what did i say", "command history", "previous command"]):
            if self.history:
                last_turn = self.history[-1]
                reply = f"Your last command was: '{last_turn['user']}'."
            else:
                reply = "No previous command history recorded yet."
            self.tts.speak(reply)
            return f"MXB: {reply}"

        # 0.25. MXB v3 companion fast-paths: search boxes, UI fields, hardware, files, power
        companion_result = self._route_companion(clean_text, original_text)
        if companion_result is not None:
            return companion_result

        # 0.3. Mathematical Query Fast-Path (<0.5ms)
        math_solution = SafeMathEvaluator.try_solve(clean_text)
        if math_solution:
            self.tts.speak(math_solution)
            self.history.append({"user": clean_text, "mxb": math_solution})
            return f"MXB: {math_solution}"

        # 0.4. Weather & Meteorology Fast-Path
        target_city = WeatherProbe.extract_city(clean_text)
        if target_city or clean_text in ["what is the weather", "current weather", "how is the weather outside"]:
            w_res = WeatherProbe.get_weather(target_city or "")
            self.tts.speak(w_res["summary"])
            self.history.append({"user": clean_text, "mxb": w_res["summary"]})
            return f"MXB: {w_res['summary']}"

        # 0.5. Battery & Power Telemetry (<0.5ms)
        if any(p in clean_text for p in [
            "battery", "battery status", "battery percentage", "how much battery",
            "check battery", "power status", "is it charging", "battery level"
        ]):
            reply = "Checking battery status."
            self.tts.speak(reply)
            status = self.executor.execute_action("check_battery")
            self.tts.speak(status)
            self.history.append({"user": clean_text, "mxb": status})
            return f"MXB: {reply}\n{status}"

        # 0.6. Timers & Stopwatch Fast-Path (<0.5ms)
        timer_match = re.search(r'^(?:set|start)(?:\s+a)?\s+timer\s+for\s+(.+)$', clean_text)
        if timer_match:
            duration_text = timer_match.group(1).strip()
            reply = f"Setting timer for {duration_text}."
            self.tts.speak(reply)
            res = self.executor.execute_action("timer_start", duration_text)
            self.tts.speak(res)
            self.history.append({"user": clean_text, "mxb": res})
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["cancel timer", "stop timer", "clear timer"]):
            reply = "Cancelling active timer."
            self.tts.speak(reply)
            res = self.executor.execute_action("timer_cancel")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["timer status", "check timer", "how much time is left", "time left on timer", "active timers"]):
            res = self.executor.execute_action("timer_status")
            self.tts.speak(res)
            return f"MXB: {res}"

        # 0.7. Color Picker & Eyedropper Fast-Path (<0.5ms)
        if any(p in clean_text for p in [
            "what color is at my cursor", "pick color", "color picker", "cursor color",
            "eyedropper", "sample color", "color at cursor"
        ]):
            res = self.executor.execute_action("pick_color")
            self.tts.speak(res)
            self.history.append({"user": clean_text, "mxb": res})
            return f"MXB: {res}"

        # 0.8. Process & Port Inspection (<1ms)
        kill_proc_match = re.search(r'^(?:kill|terminate|stop)\s+process\s+([a-zA-Z0-9_\-\.]+)$', clean_text)
        if kill_proc_match:
            proc_target = kill_proc_match.group(1).strip()
            res = self.executor.execute_action("kill_process", proc_target)
            self.tts.speak(res)
            return f"MXB: {res}"

        port_match = re.search(r'^(?:what(?:\'s|\s+is)\s+using\s+port|check\s+port|who\s+is\s+on\s+port)\s+(\d+)$', clean_text)
        if port_match:
            port_num = port_match.group(1).strip()
            res = self.executor.execute_action("find_port", port_num)
            self.tts.speak(res)
            return f"MXB: {res}"

        if any(p in clean_text for p in ["top processes", "ram hogs", "memory usage by app", "heavy processes"]):
            res = self.executor.execute_action("top_processes")
            self.tts.speak(res)
            return f"MXB: {res}"

        # 0.9. Native OS Lock & Maintenance (<1ms)
        if any(p in clean_text for p in ["lock screen", "lock pc", "lock computer", "lock workstation", "lock windows"]):
            reply = "Locking workstation now."
            self.tts.speak(reply)
            res = self.executor.execute_action("lock_pc")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["empty recycle bin", "empty the recycle bin", "clean recycle bin", "empty trash", "clear trash"]):
            res = self.executor.execute_action("empty_recycle_bin")
            self.tts.speak(res)
            return f"MXB: {res}"

        if any(p in clean_text for p in ["open task manager", "open taskmgr", "show task manager", "launch task manager"]):
            reply = "Opening Windows Task Manager."
            self.tts.speak(reply)
            res = self.executor.execute_action("open_task_manager")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["open terminal", "open powershell", "open console", "launch terminal"]):
            reply = "Opening terminal."
            self.tts.speak(reply)
            res = self.executor.execute_action("open_terminal")
            return f"MXB: {reply}\nAction: {res}"

        # 1. System Health / Telemetry
        if any(p in clean_text for p in [
            "check system", "check the system", "check my system", "check my pc", "check my computer",
            "system status", "pc status", "how is my pc", "how is my computer",
            "cpu usage", "ram usage", "battery percentage", "battery status", "pc metrics"
        ]):
            reply = "Checking your hardware status now."
            self.tts.speak(reply)
            metrics = self.executor.execute_action("check_system")
            self.tts.speak(metrics)
            self.history.append({"user": clean_text, "mxb": metrics})
            return f"MXB: {reply}\n{metrics}"

        # 2. Vision: OCR Screen Reading
        if any(p in clean_text for p in ["read screen", "read my screen", "what is on my screen", "what's on my screen", "read the screen"]):
            reply = "Reading what is visible on your screen."
            self.tts.speak(reply)
            screen_content = self.executor.execute_action("read_screen")
            self.history.append({"user": clean_text, "mxb": screen_content})
            return f"MXB: {reply}\n{screen_content}"

        # 3. Vision: Click text / button on screen
        click_text_match = re.search(r'^(?:please\s+)?(?:can you\s+)?click\s+(?:on\s+)?(?:the\s+)?(?:button\s+)?(["\']?)(.+?)\1$', clean_text)
        if click_text_match and not any(k in clean_text for k in ["right", "double", "here", "middle"]):
            target_element = click_text_match.group(2).strip()
            if target_element not in ["mouse", "it", "this"]:
                reply = f"Clicking {target_element}."
                self.tts.speak(reply)
                res = self.executor.execute_action("click_text", target_element)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\nAction: {res}"

        # 4. Mouse Controls
        if clean_text in ["click", "left click", "click mouse", "click here"]:
            res = self.executor.execute_action("left_click")
            return f"Action: {res}"

        if clean_text in ["right click", "context menu"]:
            res = self.executor.execute_action("right_click")
            return f"Action: {res}"

        if clean_text in ["double click"]:
            res = self.executor.execute_action("double_click")
            return f"Action: {res}"

        if any(p in clean_text for p in ["scroll down", "page down", "scroll downward"]):
            res = self.executor.execute_action("scroll_down")
            return f"Action: {res}"

        if any(p in clean_text for p in ["scroll up", "page up", "scroll upward"]):
            res = self.executor.execute_action("scroll_up")
            return f"Action: {res}"

        # 5. Window Management & Desktop
        if any(p in clean_text for p in ["show desktop", "minimize all", "go to desktop"]):
            reply = "Showing your desktop."
            self.tts.speak(reply)
            res = self.executor.execute_action("show_desktop")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["minimize window", "minimize this window", "minimize this"]):
            reply = "Minimizing current window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "minimize")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["maximize window", "maximize this window", "maximize screen"]):
            reply = "Maximizing current window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "maximize")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["snap left", "window left"]):
            res = self.executor.execute_action("manage_window", "left")
            return f"Action: {res}"

        if any(p in clean_text for p in ["snap right", "window right"]):
            res = self.executor.execute_action("manage_window", "right")
            return f"Action: {res}"

        if any(p in clean_text for p in ["snap top left", "snap window top left", "top left corner"]):
            res = self.executor.execute_action("manage_window", "top_left")
            return f"Action: {res}"

        if any(p in clean_text for p in ["snap top right", "snap window top right", "top right corner"]):
            res = self.executor.execute_action("manage_window", "top_right")
            return f"Action: {res}"

        if any(p in clean_text for p in ["snap bottom left", "snap window bottom left", "bottom left corner"]):
            res = self.executor.execute_action("manage_window", "bottom_left")
            return f"Action: {res}"

        if any(p in clean_text for p in ["snap bottom right", "snap window bottom right", "bottom right corner"]):
            res = self.executor.execute_action("manage_window", "bottom_right")
            return f"Action: {res}"

        if any(p in clean_text for p in ["center window", "snap center", "center screen"]):
            res = self.executor.execute_action("manage_window", "center")
            return f"Action: {res}"

        if any(p in clean_text for p in ["shake window", "aero shake", "minimize other windows", "minimize others"]):
            res = self.executor.execute_action("manage_window", "shake")
            return f"Action: {res}"

        if clean_text in ["close window", "close this window", "close active window"]:
            reply = "Closing active window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "close")
            return f"MXB: {reply}\nAction: {res}"

        # 6. Common Keyboard Shortcuts
        if clean_text in ["copy", "copy this", "copy that", "copy selection"]:
            res = self.executor.execute_action("copy_text")
            return f"Action: {res}"

        if clean_text in ["paste", "paste here", "paste text"]:
            res = self.executor.execute_action("paste_text")
            return f"Action: {res}"

        if clean_text in ["select all", "select everything"]:
            res = self.executor.execute_action("select_all")
            return f"Action: {res}"

        if clean_text in ["undo", "undo that"]:
            res = self.executor.execute_action("undo")
            return f"Action: {res}"

        if clean_text in ["save", "save file", "save document", "save this"]:
            res = self.executor.execute_action("save_file")
            return f"Action: {res}"

        if clean_text in ["press enter", "hit enter"]:
            res = self.executor.execute_action("press_key", "enter")
            return f"Action: {res}"

        if clean_text in ["press escape", "hit escape"]:
            res = self.executor.execute_action("press_key", "escape")
            return f"Action: {res}"

        # 7. Media & Volume Controls
        if any(p in clean_text for p in ["volume up", "turn up volume", "louder", "increase volume"]):
            reply = "Turning volume up."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "volume_up")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["volume down", "turn down volume", "quieter", "lower volume"]):
            reply = "Turning volume down."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "volume_down")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["mute audio", "mute sound", "mute volume", "mute", "unmute"]):
            reply = "Toggling mute."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "mute")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["play music", "pause music", "pause playback", "play song"]):
            reply = "Toggling media playback."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "play")
            return f"MXB: {reply}\nAction: {res}"

        # 8. Screenshot Capture
        if any(p in clean_text for p in ["screenshot", "take a screenshot", "capture screen", "print screen"]):
            reply = "Capturing screen."
            self.tts.speak(reply)
            res = self.executor.execute_action("capture_screen")
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\nAction: {res}"

        # 9. App Launching
        launch_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:open|launch|start|pull up|bring up|fire up)\s+(?:up\s+)?'
                                 r'(?:the\s+|my\s+)?([a-zA-Z0-9\s]+?)(?:\s+app)?$', clean_text)
        if launch_match:
            app_name = launch_match.group(1).strip()
            if app_name and app_name not in ["the door", "a tab", "window", "folder"]:
                reply = f"Opening {app_name} for you."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("open_app", app_name)

        # 10. App Closing
        close_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:close|kill|quit|terminate|exit)\s+(?:the\s+|my\s+)?([a-zA-Z0-9\s]+)$', clean_text)
        if close_match:
            target_app = close_match.group(1).strip()
            if target_app and target_app not in ["window", "this window", "active window"]:
                reply = f"Closing {target_app}."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("close_app", target_app)

        # 11. Direct Text Typing
        if clean_text.startswith("type "):
            extracted = original_text.split(" ", 1)[1] if " " in original_text else clean_text.split("type ", 1)[1]
            reply = "Typing that now."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("type_text", extracted)

        # 12. File System Operations
        if clean_text.startswith("create folder ") or clean_text.startswith("make folder "):
            fname = re.sub(r'^(?:create|make)\s+folder\s+', '', original_text, flags=re.IGNORECASE).strip()
            reply = f"Creating folder {fname}."
            self.tts.speak(reply)
            res = self.executor.execute_action("create_folder", fname)
            return f"MXB: {reply}\nAction: {res}"

        if clean_text.startswith("list files") or clean_text.startswith("show files"):
            folder = clean_text.replace("list files in", "").replace("list files", "").strip() or "desktop"
            reply = f"Listing files in {folder}."
            self.tts.speak(reply)
            res = self.executor.execute_action("list_files", folder)
            self.tts.speak(res)
            return f"MXB: {reply}\n{res}"

        # 13. Web Search
        search_match = re.search(r'^(?:search (?:the web|google|online|the internet) for|search on google for|google search(?: for)?|'
                                 r'search for|search|google|look up)\s+(.+)$', clean_text)
        if search_match:
            query = search_match.group(1).strip()
            reply = f"Searching the web for {query}."
            self.tts.speak(reply)
            summary = self.executor.execute_action("search_web", query)
            self.tts.speak(summary)
            self.history.append({"user": clean_text, "mxb": summary})
            return f"MXB: {reply}\n{summary}"

        # 14. Clipboard Analysis
        if any(p in clean_text for p in ["summarize clipboard", "read clipboard", "explain clipboard", "what did i copy"]):
            reply = "Reading your clipboard now."
            self.tts.speak(reply)
            analysis = self.executor.execute_action("analyze_clipboard", "summarize clearly in 1 or 2 spoken sentences")
            self.tts.speak(analysis)
            self.history.append({"user": clean_text, "mxb": analysis})
            return f"MXB: {reply}\n{analysis}"

        # 15. Long-term Memory
        if clean_text.startswith("remember that ") or clean_text.startswith("remember "):
            fact = re.sub(r'^remember(?:\s+that)?\s+', '', original_text, flags=re.IGNORECASE).strip()
            if fact:
                self.memory.remember(fact)
                try:
                    self.executor.semantic.add(fact, kind="fact")
                except Exception:
                    pass
                reply = "I've saved that to my long-term memory."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\nSaved: {fact}"

        # 16. Hardware-Anchored Vault (DPAPI)
        store_vault_match = re.search(r'^(?:store|save)\s+(?:secret|password|credential)\s+([a-zA-Z0-9_\-]+)\s+(?:as|value)\s+(.+)$', clean_text)
        if store_vault_match:
            v_key = store_vault_match.group(1).strip()
            v_val = store_vault_match.group(2).strip()
            orig_vault = re.search(r'(?:as|value)\s+(.+)$', original_text, re.IGNORECASE)
            if orig_vault and orig_vault.group(1).strip().lower() == v_val:
                v_val = orig_vault.group(1).strip()  # secrets are case-sensitive
            res = self.executor.execute_action("vault_store", f"{v_key}::{v_val}")
            self.tts.speak(res)
            return f"MXB: {res}"

        get_vault_match = re.search(r'^(?:get|show|retrieve)\s+(?:secret|password|credential)\s+([a-zA-Z0-9_\-]+)$', clean_text)
        if get_vault_match:
            v_key = get_vault_match.group(1).strip()
            res = self.executor.execute_action("vault_get", v_key)
            self.tts.speak(res)
            return f"MXB: {res}"

        if any(p in clean_text for p in ["list secrets", "vault keys", "list vault"]):
            res = self.executor.execute_action("vault_list")
            self.tts.speak(res)
            return f"MXB: {res}"

        # =========================================================================
        # TIER 2: LLM MULTI-STEP ACTION PLANNER & SECOND BRAIN REASONING
        # =========================================================================
        log.info("IntentRouter: No direct match in Tier 1. Delegating to LLM Multi-Step Planner...")
        return self._route_to_llm(transcription, feedback_callback=feedback_callback)

    _POLITE_PREFIX = re.compile(r"^(?:(?:hey|hi|ok|okay)\s+)?(?:mxb[,\s]+)?(?:(?:please|kindly)\s+)?"
                                r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?)?")
    # Only filler that never carries meaning ("...saying thanks" must keep "thanks").
    _POLITE_SUFFIX = re.compile(r"(?:,?\s+(?:please|for me))+$")

    @classmethod
    def _strip_politeness(cls, t: str, o: str) -> tuple[str, str]:
        """'could you open notepad for me' -> 'open notepad' (same cut applied to the original-case text)."""
        if len(t) != len(o):
            return t, o
        m = cls._POLITE_PREFIX.match(t)
        start = m.end() if m else 0
        if start and start < len(t):
            t, o = t[start:], o[start:]
        m = cls._POLITE_SUFFIX.search(t)
        if m and m.start() > 0:
            t, o = t[:m.start()], o[:m.start()]
        return t.strip(), o.strip()

    @staticmethod
    def _clean_and_parse_json(raw: str) -> dict | None:
        return parse_json_reply(raw)

    def _route_to_llm(self, text: str, feedback_callback=None) -> str:
        try:
            # 1. Fetch relevant user memories (semantic search first, keyword memory as fallback)
            saved_memories = []
            try:
                saved_memories = list(self.executor.semantic.recall_texts(text, k=5))
            except Exception:
                pass
            if not saved_memories:
                saved_memories = self.memory.get_memories(query=text, limit=4)
            memory_context = ""
            if saved_memories:
                memory_context = "User's Saved Memories:\n" + "\n".join([f"- {m}" for m in saved_memories]) + "\n\n"

            # 2. Conversation history context
            history_context = ""
            if self.history:
                history_context = "Recent Conversation Context:\n"
                for turn in self.history:
                    history_context += f"User: {turn['user']}\nMXB: {turn['mxb']}\n"
                history_context += "\n"

            # 3. Current active window context
            active_window_context = ""
            try:
                import pygetwindow as gw
                from safety.injection import detect_injection, wrap_untrusted
                active = gw.getActiveWindow()
                # Web pages control their own window titles, so the title is untrusted text.
                if active and active.title and not detect_injection(active.title):
                    active_window_context = f"Active window title: {wrap_untrusted(active.title, 'window-title', 200)}\n\n"
            except Exception:
                pass

            # 4. Environmental context (cached) + clock
            env_context = f"{EnvironmentContext.get_weather_and_location()}\nLocal time: {time.strftime('%A %d %B %Y, %I:%M %p')}\n\n"

            augmented_prompt = f"{memory_context}{history_context}{active_window_context}{env_context}User Command: '{text}'"

            if feedback_callback:
                feedback_callback("Thinking...")
            plan_data, already_spoke = self._plan(augmented_prompt)

            if not plan_data:
                fallback_msg = ("I understood your request but could not reach my reasoning engine. "
                                "Check your NVIDIA API key or start Ollama.")
                self.tts.speak(fallback_msg)
                return fallback_msg

            reply = str(plan_data.get("reply", "") or "")
            steps = plan_data.get("plan", []) or []
            if not isinstance(steps, list):
                steps = []

            # Handle older single-action format if returned
            if not steps and "action" in plan_data and plan_data["action"] not in ["unknown", "conversation", "none"]:
                steps = [{"action": plan_data["action"], "target": plan_data.get("target", "")}]

            if reply:
                reply = re.sub(r'^(?:mxb\s*:\s*)+', '', reply, flags=re.IGNORECASE).strip()
                if not already_spoke:
                    self.tts.speak(reply)
                self.history.append({"user": text, "mxb": reply})

            steps, dropped = validate_plan(steps)
            if dropped:
                log.warning(f"Router: LLM proposed unknown actions {dropped}; skipped.")
            if steps:
                results = self.executor.planner.execute_plan(steps, feedback_callback=feedback_callback)
                results = [r for r in results if r]
                # Speak results that carry information (search results, file contents, device lists)
                informative = [r for r in results if self._is_informative(r)]
                if informative:
                    self.tts.speak(informative[-1][:400])
                summary_actions = "; ".join(results)
                return f"MXB: {reply}\nActions: {summary_actions}"

            return f"MXB: {reply}"

        except Exception as e:
            traceback.print_exc()
            log.error(f"Router LLM Error: {e}")
            return f"Speech Understanding Error: {e}"

    def _plan(self, prompt: str) -> tuple[dict | None, bool]:
        """
        Voice turns: stream the plan and speak the reply sentence-by-sentence as it
        arrives (lowest latency). Text turns: native tool calling (most reliable),
        then JSON mode as a fallback. Returns (plan_data, reply_already_spoken).
        """
        system = planner_system_prompt()
        llm_cfg = self.config.get("llm", {})
        speaking = True
        try:
            speaking = bool(self.tts.speaking_enabled())
        except Exception:
            pass
        if llm_cfg.get("streaming", True) and speaking:
            streamer = ReplyStreamer(self.tts.speak)
            raw = self.llm.stream_chat(system, prompt, on_delta=streamer.feed)
            streamer.finish()
            data = parse_json_reply(raw) if raw else None
            if data:
                return data, streamer.spoke
        data = self.llm.plan_with_tools(system, prompt, plan_tool_schema())
        if not data:
            data = self.llm.chat_json(system, prompt)
        return data, False

    # =========================================================================
    # MXB v4 FAST-PATHS: marks, undo, memory, documents, schedules, routines, remote, plugins
    # =========================================================================
    def _route_v4(self, t: str, o: str) -> str | None:
        # ---------------- Plugin skills (user-installed, so they get first pick) ----------------
        try:
            matched = self.executor.skills.match(o)
        except Exception:
            matched = None
        if isinstance(matched, tuple):
            sk, target = matched
            return self._act(t, sk.name, target)
        if t in {"list skills", "list plugins", "what plugins do you have", "what skills do you have", "show plugins"}:
            try:
                reply = self.executor.skills.describe()
            except Exception:
                reply = "No plugin skills are installed."
            self.tts.speak(reply)
            return f"MXB: {reply}"

        # ---------------- Set-of-marks voice clicking ----------------
        if t in {"show numbers", "show marks", "show labels", "show hints", "label the screen", "number the screen",
                 "number everything", "show clickable items", "show numbers on screen"}:
            return self._act(t, "show_marks")
        if t in {"hide numbers", "hide marks", "hide labels", "hide hints", "clear numbers"}:
            return self._act(t, "hide_marks", speak_result=False)
        m = re.match(r"^(?:click|press|tap|select|open)\s+(?:on\s+)?(?:number\s+|mark\s+|item\s+)?(?P<n>\d{1,3})$", t)
        if m:
            return self._act(t, "click_mark", m.group("n"), speak_result=False)
        m = re.match(r"^(?:type|enter|write)\s+(?P<text>.+?)\s+(?:in|into|on)\s+(?:number\s+|mark\s+|item\s+)(?P<n>\d{1,3})$", t) or \
            re.match(r"^(?:type|enter|write)\s+(?P<text>.+?)\s+(?:in|into)\s+(?P<n>\d{1,3})$", t)
        if m:
            return self._act(t, "type_mark", f"{m.group('n')} :: {self._grp(m, 'text', t, o)}", speak_result=False)

        # ---------------- Undo MXB's file actions ----------------
        if t in {"undo the last file action", "undo last file action", "undo your last action", "undo what you did",
                 "revert that", "revert the last change", "undo the move", "undo the delete", "undo the rename",
                 "undo the copy", "undo last action"}:
            return self._act(t, "undo_last")
        if t == "undo that":
            age = None
            try:
                age = float(self.executor.journal.seconds_since_last())
            except Exception:
                pass
            if age is not None and age < 120:
                return self._act(t, "undo_last")

        # ---------------- Memory ----------------
        if t in {"what do you remember", "what do you remember about me", "what do you know about me",
                 "what have you learned about me", "list memories", "show memories"}:
            return self._act(t, "recall_memories", "")
        m = re.match(r"^what do you (?:remember|know) about (?P<x>.+)$", t)
        if m:
            return self._act(t, "recall_memories", m.group("x"))
        m = re.match(r"^forget (?:that |about |what i said about |the fact that )?(?P<x>.+)$", t)
        if m and m.group("x") not in {"it", "that", "this", "everything"}:
            return self._act(t, "forget_memory", self._grp(m, "x", t, o))
        pref = extract_preference(o)
        if pref:
            res = self.executor.execute_action("remember_preference", pref)
            reply = "Got it, I'll remember that." if "already" not in str(res).lower() else "I already knew that."
            self.tts.speak(reply)
            self.history.append({"user": t, "mxb": reply})
            return f"MXB: {reply}"

        # ---------------- Documents (RAG) ----------------
        docs = r"(?:documents|docs|notes|files|pdfs|folder)"
        m = re.match(rf"^(?:ask my {docs}|search my {docs} for|what do my {docs} say about|according to my {docs},?|"
                     rf"check my {docs} (?:for|about)|look in my {docs} for)\s+(?P<q>.+)$", t)
        if m:
            return self._act(t, "ask_documents", self._grp(m, "q", t, o))
        if t in {"what have you indexed", "knowledge status", "what documents do you know", "which folders have you indexed",
                 "index status", "what folders have you learned"}:
            return self._act(t, "knowledge_status")
        m = re.match(r"^(?:index|re-?index)\s+(?:the\s+|my\s+)?(?:folder\s+)?(?P<f>.+?)(?:\s+folder)?$", t) or \
            re.match(r"^(?:learn|read and remember|study|learn from)\s+(?:the\s+|my\s+)?(?:folder\s+(?P<f2>.+)|(?P<f>.+?)\s+folder)$", t)
        if m:
            group = "f" if m.groupdict().get("f") else "f2"
            return self._act(t, "index_folder", self._grp(m, group, t, o))

        # ---------------- Reminders & schedules ----------------
        if re.match(r"^(?:list|show|what are)\s+(?:my\s+|all\s+)?(?:reminders|schedules|scheduled (?:commands|tasks))$|^what(?:'s| is) scheduled$", t):
            return self._act(t, "list_schedules")
        if re.match(r"^(?:cancel|delete|clear|remove)\s+all\s+(?:my\s+)?(?:reminders|schedules|scheduled (?:commands|tasks))$", t):
            return self._act(t, "cancel_schedule", "all")
        m = re.match(r"^(?:cancel|delete|remove)\s+(?:the\s+|my\s+)?(?:reminder|schedule|scheduled (?:command|task))\s*(?:number\s+)?(?:to\s+|about\s+|for\s+)?(?P<x>.*)$", t)
        if m:
            return self._act(t, "cancel_schedule", m.group("x").strip() or "1")
        m = re.match(r"^(?:set\s+(?:a\s+)?reminder|remind me)\s+(?P<rest>.+)$", t)
        if m:
            parsed = self._parse_reminder(self._grp(m, "rest", t, o))
            if parsed:
                when, what = parsed
                return self._act(t, "set_reminder", f"{when} :: {what}")
        m = re.match(r"^(?:schedule|automatically|auto)\s+(?P<rest>.+)$", t)
        if m:
            rest = self._grp(m, "rest", t, o)
            split = split_trailing_time(rest) or (lambda r: (r[1], r[0]) if r else None)(split_leading_time(rest))
            if split:
                cmd, when = split
                return self._act(t, "schedule_command", f"{when} :: {cmd}")
        if t.startswith("every "):
            split = split_leading_time(o)
            if split:
                when, cmd = split
                rem = re.match(r"^(?:remind me to|remind me)\s+(?P<w>.+)$", cmd, re.I)
                if rem:
                    return self._act(t, "set_reminder", f"{when} :: {rem.group('w')}")
                return self._act(t, "schedule_command", f"{when} :: {cmd}")

        # ---------------- Routines & recordings ----------------
        m = re.match(r"^(?:create|make|save|add)\s+(?:a\s+|new\s+)?routine\s+(?:called\s+|named\s+)?(?P<name>.+?)\s*(?::|that does|which does|with|to do)\s*(?P<cmds>.+)$", t)
        if m:
            return self._act(t, "create_routine", f"{self._grp(m, 'name', t, o)} :: {self._grp(m, 'cmds', t, o)}")
        if re.match(r"^(?:list|show|what are)\s+(?:my\s+)?(?:routines|workflows|macros)$|^what routines do i have$", t):
            return self._act(t, "list_routines")
        m = re.match(r"^(?:delete|remove)\s+(?:the\s+)?(?:routine|workflow|macro)\s+(?P<name>.+)$", t)
        if m:
            return self._act(t, "delete_routine", m.group("name"))
        m = re.match(r"^(?:start|begin)\s+recording(?:\s+(?:a\s+)?(?:workflow|macro|routine))?(?:\s+(?:called|named|for))?\s*(?P<name>.*)$", t)
        if m:
            return self._act(t, "start_recording", self._grp(m, "name", t, o) or "workflow")
        if t in {"stop recording", "finish recording", "end recording", "save recording", "save the recording", "done recording"}:
            return self._act(t, "stop_recording")
        m = re.match(r"^(?:run|start|do|play)\s+(?:my\s+|the\s+)?(?:routine|workflow|macro)\s+(?P<name>.+)$", t) or \
            re.match(r"^(?:run|start|do)\s+(?:my\s+|the\s+)?(?P<name>.+?)\s+(?:routine|workflow|macro)$", t)
        if m:
            return self._act(t, "run_routine", m.group("name"), speak_result=True)
        m = re.match(r"^run\s+(?:my\s+|the\s+)?(?P<name>.+)$", t)
        if m:
            found = None
            try:
                found = self.executor.routines.find(m.group("name"))
            except Exception:
                pass
            if isinstance(found, tuple):
                return self._act(t, "run_routine", m.group("name"))

        # ---------------- Trust: audit log, updates, autostart ----------------
        if t in {"show the audit log", "show audit log", "audit log", "show activity log", "what have you done",
                 "what did you do", "show your activity"}:
            return self._act(t, "audit_log", "")
        if t in {"what did you do today", "what have you done today", "what did you do while i was away"}:
            return self._act(t, "audit_log", "today")
        if t in {"check for updates", "check for update", "is there an update", "any updates", "update check"}:
            return self._act(t, "check_updates", "")
        if t in {"install the update", "install update", "update mxb", "update yourself", "install the new version"}:
            return self._act(t, "install_update", "")
        if t in {"start with windows", "start automatically", "launch at startup", "enable autostart", "start mxb with windows"}:
            return self._act(t, "autostart", "on")
        if t in {"don't start with windows", "do not start with windows", "disable autostart", "stop starting with windows"}:
            return self._act(t, "autostart", "off")

        # ---------------- v4.2: MXB browser ----------------
        browser = r"(?:the\s+)?mxb(?:'s)?\s+browser"
        m = re.match(rf"^open\s+(?P<u>.+?)\s+in\s+{browser}$", t) or re.match(r"^(?:browse|surf)\s+(?:to\s+)?(?P<u>(?!.*\b(?:folder|files?|documents|downloads|desktop|pictures|drive)\b).+)$", t)
        if m:
            return self._act(t, "web_open", m.group("u"), speak_result=True)
        if re.match(rf"^(?:open|start|launch)\s+{browser}$", t):
            return self._act(t, "web_open", "about:blank", speak_result=True)
        if re.match(rf"^(?:close|quit|exit)\s+{browser}$", t):
            return self._act(t, "web_close", "")
        m = re.match(r"^(?:web|page)\s+(?P<verb>click|press)\s+(?:on\s+)?(?P<x>.+)$", t)
        if m:
            return self._act(t, "web_click" if m.group("verb") == "click" else "web_press", m.group("x"))
        if self._web_on():
            if t in {"read this page", "read the page", "read the web page", "read this webpage", "read the webpage",
                     "read this website", "read the article"}:
                return self._act(t, "web_read", "", speak_result=True)
            if t in {"summarize this page", "summarise this page", "summarize the page", "summarise the page",
                     "what is this page about", "what's this page about", "summarize this article", "tldr"}:
                return self._act(t, "web_summarize", "", speak_result=True)
            if re.match(r"^(?:show|list|number)\s+(?:the\s+)?(?:page\s+elements|elements|links|buttons)(?:\s+on\s+(?:the|this)\s+page)?$", t):
                return self._act(t, "web_elements", "", speak_result=True)
            if t in {"list tabs", "list the tabs", "show tabs", "show the tabs", "which tabs are open"}:
                return self._act(t, "web_tabs", "", speak_result=True)
            if t in {"go back", "back", "previous page"}:
                return self._act(t, "web_back", "")

        # ---------------- v4.2: MCP, visual grounding, language ----------------
        if t in {"list mcp tools", "show mcp tools", "mcp tools", "mcp status", "what mcp tools do you have",
                 "list my tools", "what tools do you have", "show connected tools"}:
            return self._act(t, "mcp_tools", "", speak_result=True)
        if t in {"reload mcp", "reconnect mcp", "reload mcp servers", "restart mcp servers", "reconnect mcp servers"}:
            return self._act(t, "mcp_reload", "", speak_result=True)
        m = re.match(r"^(?:visually\s+click|click\s+visually(?:\s+on)?|look for and click|find and click)\s+(?:on\s+)?(?:the\s+)?(?P<d>.+)$", t)
        if m:
            return self._act(t, "click_visual", m.group("d"))
        m = re.match(r"^where(?:'s|\s+is)\s+(?:the\s+)?(?P<d>.+?)\s+on\s+(?:the\s+|my\s+)?screen$", t)
        if m:
            return self._act(t, "locate_visual", m.group("d"), speak_result=True)
        m = re.match(r"^(?:speak|talk|reply|answer|respond)(?:\s+to\s+me)?\s+(?:only\s+)?in\s+(?P<lang>[a-z]+)$", t) or \
            re.match(r"^(?:switch|change|set)\s+(?:your\s+|the\s+)?language\s+to\s+(?P<lang>[a-z]+)$", t)
        if m:
            return self._act(t, "set_language", m.group("lang"), speak_result=True)

        # ---------------- Phone remote ----------------
        phone = r"(?:phone|mobile)\s+(?:remote|control|access|app)"
        if re.match(rf"^(?:turn on|enable|start|open|switch on)\s+(?:the\s+)?{phone}$", t):
            return self._act(t, "phone_remote", "on")
        if re.match(rf"^(?:turn off|disable|stop|close|switch off)\s+(?:the\s+)?{phone}$", t):
            return self._act(t, "phone_remote", "off")
        if re.match(rf"^(?:{phone}\s+status|is (?:the\s+)?{phone} on)$", t):
            return self._act(t, "phone_remote", "status")
        if t in {"new phone link", "reset phone remote", "change phone remote link", "rotate phone remote token"}:
            return self._act(t, "phone_remote", "rotate")
        return None

    def _web_on(self) -> bool:
        probe = getattr(self.executor, "web_active", None)
        try:
            return callable(probe) and probe() is True
        except Exception:
            return False

    _NUM_WORDS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
                  "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14, "fifteen": 15,
                  "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
                  "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90}

    @classmethod
    def _words_to_number(cls, text: str) -> int | None:
        """'fifty' -> 50, 'seventy five' -> 75, 'a hundred' / 'one hundred' -> 100."""
        words = [w for w in re.split(r"[\s-]+", (text or "").lower().strip()) if w and w != "and"]
        if not words:
            return None
        if words[-1] == "hundred" and len(words) <= 2 and (len(words) == 1 or words[0] in {"a", "one"}):
            return 100
        total = 0
        for w in words:
            if w not in cls._NUM_WORDS:
                return None
            total += cls._NUM_WORDS[w]
        return total if 0 <= total <= 100 else None

    @staticmethod
    def _parse_reminder(rest: str) -> tuple[str, str] | None:
        """'in 20 minutes to stretch' | 'to call mom at 5 pm' | 'about the demo tomorrow at 9' -> (when, what)."""
        rest = rest.strip()
        m = re.match(r"^(?:to|about|that)\s+(?P<what>.+)$", rest, re.I)
        if m:
            split = split_trailing_time(m.group("what"))
            if split:
                return split[1], split[0]
            return None
        parts = re.split(r"\s+(?:to|about|that)\s+", rest, maxsplit=1)
        if len(parts) == 2 and parse_when(parts[0]):
            return parts[0], parts[1]
        split = split_leading_time(rest)
        if split:
            return split[0], re.sub(r"^(?:to|about|that)\s+", "", split[1], flags=re.I)
        return None

    @staticmethod
    def _is_informative(result: str) -> bool:
        low = (result or "").lower()
        if not low:
            return False
        markers = ("found ", "paired bluetooth", "nearby wi-fi", "connected devices", "speakers:", "volume is",
                   "brightness is", "cancelled", "couldn't", "could not", "don't have access", "not found",
                   "wi-fi is", "bluetooth is", "microphone is", "i stopped", "agent task")
        return any(m in low for m in markers) or (": " in result and len(result) > 60 and "visible on screen" not in low)

    # =========================================================================
    # MXB v3 COMPANION FAST-PATHS
    # =========================================================================
    def _act(self, user_text: str, action: str, target: str = "", reply: str | None = None,
             speak_result: bool = True) -> str:
        if reply:
            self.tts.speak(reply)
        res = self.executor.execute_action(action, target)
        if speak_result and res:
            self.tts.speak(res)
        self.history.append({"user": user_text, "mxb": res or reply or ""})
        return f"MXB: {reply}\nAction: {res}" if reply else f"MXB: {res}"

    @staticmethod
    def _grp(m, group: str, t: str, o: str) -> str:
        """
        Returns a regex group from the ORIGINAL-case text. Patterns run on the
        lowercased text t; o is the same string with the user's capitalization, so
        the matched span can be sliced out of o (keeps "Hello World", file names, SSIDs).
        """
        value = m.group(group) or ""
        if len(t) == len(o):
            start, end = m.span(group)
            if start >= 0:
                value = o[start:end]
        return value.strip()

    _SEARCH_BOX = r"search\s*(?:box|bar|field|input)?"
    _ENTER_TAIL = r"(?:\s*(?:,|and|then|&)?\s*(?:press|hit|click)\s+(?:the\s+)?(?:enter|return|search)(?:\s+key|\s+button)?)"

    def _route_companion(self, t: str, o: str) -> str | None:
        # ---------------- Clock (never let the LLM guess the time) ----------------
        if t in {"what time is it", "what's the time", "what is the time", "tell me the time", "time please", "current time"}:
            reply = time.strftime("It's %I:%M %p.").replace(" 0", " ")
            self.tts.speak(reply)
            return f"MXB: {reply}"
        if t in {"what's the date", "what is the date", "what is today's date", "what's today's date", "what day is it", "today's date"}:
            reply = time.strftime("Today is %A, %d %B %Y.")
            self.tts.speak(reply)
            return f"MXB: {reply}"

        v4 = self._route_v4(t, o)
        if v4 is not None:
            return v4

        # ---------------- Known folders, websites, settings, media (bench-driven fixes) ----------------
        m = re.match(r"^(?P<verb>open|show|go to)\s+(?:my\s+|the\s+)?(?P<f>desktop|downloads|documents|pictures|music|videos|home)(?P<folder>\s+folder)?$", t)
        if m and not (m.group("f") == "desktop" and m.group("verb") != "open" and not m.group("folder")):
            # ("show desktop" / "go to desktop" still mean minimize-everything)
            return self._act(t, "open_path", m.group("f"), speak_result=False)
        m = re.match(r"^(?:go to|open|visit|browse to|navigate to)\s+(?P<url>(?:https?://)?(?:www\.)?[\w\-]+(?:\.[\w\-]+)*\."
                     r"(?:com|in|org|net|io|dev|edu|gov|co|ai|app|me|tv|ly|so)(?:/\S*)?)$", t)
        if m:
            return self._act(t, "open_url", self._grp(m, "url", t, o), speak_result=False)
        if t in {"open settings", "open windows settings", "show settings", "open the settings"}:
            return self._act(t, "open_settings", "", speak_result=False)
        if re.match(r"^(?:pause|stop|resume|continue|play)\s+(?:the\s+)?(?:music|song|video|playback|track)$", t):
            return self._act(t, "media_control", "play", speak_result=False)
        if t in {"next song", "next track", "skip song", "skip this song", "play the next song", "skip track"}:
            return self._act(t, "media_control", "next", speak_result=False)
        if t in {"previous song", "previous track", "last song", "play the previous song", "go back a song"}:
            return self._act(t, "media_control", "prev", speak_result=False)
        if re.match(r"^(?:turn|put)\s+(?:the\s+)?volume\s+all the way (?:down|off)$|^mute everything$", t):
            return self._act(t, "set_volume", "0")
        if re.match(r"^(?:turn|put)\s+(?:the\s+)?volume\s+all the way up$|^max(?:imum)? volume$", t):
            return self._act(t, "set_volume", "100")
        m = re.match(r"^(?:set|change|put|turn)\s+(?:the\s+)?(?P<what>volume|sound|brightness|screen brightness)\s+(?:to|at)\s+(?P<n>[a-z][a-z\s-]+?)\s*(?:%|percent)?$", t)
        if m and self._words_to_number(m.group("n")) is not None:
            action = "set_brightness" if "bright" in m.group("what") else "set_volume"
            return self._act(t, action, str(self._words_to_number(m.group("n"))))
        if t in {"lock my computer", "lock my pc", "lock my laptop", "lock the computer", "lock the pc", "lock it"}:
            return self._act(t, "lock_pc")

        # ---------------- Search box on screen ----------------
        sb, tail = self._SEARCH_BOX, self._ENTER_TAIL
        p1 = (rf"^(?:please\s+)?(?:go\s+to|click(?:\s+on)?|focus(?:\s+on)?|open|use|select|tap(?:\s+on)?)\s+(?:the\s+|that\s+)?"
              rf"(?:(?P<hint>[\w\s\.]+?)\s+)?{sb}\s*(?:,|and|then)?\s*(?:and\s+)?(?:type|enter|write|put|search(?:\s+for)?|input)\s+"
              rf"(?P<text>.+?){tail}?$")
        m = re.match(p1, t)
        if m:
            text = self._grp(m, "text", t, o)
            hint = (m.group("hint") or "").strip()
            hint = "" if hint in {"", "the", "a", "that"} else hint
            press_enter = bool(re.search(tail + "$", t))
            if press_enter:
                return self._act(t, "search_on_screen", f"{hint} :: {text}" if hint else text, speak_result=False)
            return self._act(t, "type_into", f"search {hint} :: {text}".replace("  ", " "), speak_result=False)

        p2 = (rf"^(?:please\s+)?(?:type|enter|write|put|input)\s+(?P<text>.+?)\s+(?:in|into|inside|on)\s+(?:the\s+)?"
              rf"(?P<field>[\w\s\.]+?)\s*(?:box|bar|field|input|textbox)(?P<tail>{tail})?$")
        m = re.match(p2, t)
        if m:
            text = self._grp(m, "text", t, o)
            field = m.group("field").strip()
            enter = "enter" if m.group("tail") else ""
            if "search" in field and enter:
                hint = field.replace("search", "").strip()
                return self._act(t, "search_on_screen", f"{hint} :: {text}" if hint else text, speak_result=False)
            return self._act(t, "type_into", f"{field} :: {text}" + (" :: enter" if enter else ""), speak_result=False)

        p3 = (rf"^(?:please\s+)?(?:search(?:\s+for)?|look\s+up|find)\s+(?P<text>.+?)\s+(?:in|on|using|with)\s+(?:the\s+)?"
              rf"(?:(?P<hint>[\w\s\.]+?)\s+)?{sb}$")
        m = re.match(p3, t)
        if m and re.search(r"(box|bar|field|input)$", t):
            text = self._grp(m, "text", t, o)
            hint = (m.group("hint") or "").strip()
            return self._act(t, "search_on_screen", f"{hint} :: {text}" if hint else text, speak_result=False)

        m = re.match(r"^(?:please\s+)?(?:go\s+to|click(?:\s+on)?|focus(?:\s+on)?|select)\s+(?:the\s+)?(?P<hint>[\w\s\.]*?)\s*search\s*(?:box|bar|field|input)$", t)
        if m:
            return self._act(t, "focus_search_box", m.group("hint").strip(), speak_result=False)

        # ---------------- Click a named control ----------------
        m = re.match(r"^(?:please\s+)?(?:click|press|tap|hit|select)\s+(?:on\s+)?(?:the\s+)?(?P<name>.+?)\s+(?:button|link|tab|menu|option|icon|checkbox|item|toggle)$", t)
        if m:
            name = self._grp(m, "name", t, o)
            return self._act(t, "click_element", name, speak_result=False)

        if t in {"what can i click", "list buttons", "what's on this window", "what is on this window", "list ui elements", "what buttons are there"}:
            return self._act(t, "list_ui_elements")

        # ---------------- Bluetooth ----------------
        bt = r"blue\s?tooth"
        m = re.match(rf"^(?:please\s+)?(?:turn|switch|put)\s+(on|off)\s+(?:the\s+)?{bt}$", t) or \
            re.match(rf"^(?:please\s+)?(?:turn|switch|put)\s+(?:the\s+)?{bt}\s+(?:back\s+)?(on|off)$", t)
        if m:
            return self._act(t, "bluetooth_power", m.group(1))
        m = re.match(rf"^(enable|disable)\s+(?:the\s+)?{bt}$", t)
        if m:
            return self._act(t, "bluetooth_power", "on" if m.group(1) == "enable" else "off")
        if re.match(rf"^(?:is\s+)?{bt}\s+(?:on|status|enabled)$|^(?:{bt}\s+status|is\s+(?:the\s+)?{bt}\s+on)$", t):
            return self._act(t, "bluetooth_power", "status")
        if re.match(rf"^(?:list|show(?:\s+me)?|what are)(?:\s+(?:my|all|the))?\s+(?:paired\s+|connected\s+)?{bt}\s+devices(?:\s+(?:are\s+)?(?:connected|paired))?$", t) or \
           re.match(rf"^what\s+{bt}\s+devices\s+are\s+(?:connected|paired)$", t):
            return self._act(t, "bluetooth_devices")

        # ---------------- Wi-Fi ----------------
        wifi = r"(?:wi-?fi|wireless|wlan)"
        m = re.match(rf"^(?:please\s+)?(?:turn|switch)\s+(on|off)\s+(?:the\s+)?{wifi}$", t) or \
            re.match(rf"^(?:please\s+)?(?:turn|switch)\s+(?:the\s+)?{wifi}\s+(?:back\s+)?(on|off)$", t)
        if m:
            return self._act(t, "wifi_power", m.group(1))
        m = re.match(rf"^(enable|disable)\s+(?:the\s+)?{wifi}$", t)
        if m:
            return self._act(t, "wifi_power", "on" if m.group(1) == "enable" else "off")
        if re.match(rf"^(?:{wifi}\s+status|am\s+i\s+connected\s+to\s+(?:the\s+)?(?:{wifi}|internet)|which\s+{wifi}\s+am\s+i\s+(?:on|connected to)|is\s+{wifi}\s+(?:on|connected))$", t):
            return self._act(t, "wifi_power", "status")
        if re.match(rf"^(?:list|show|scan(?:\s+for)?|find)\s+(?:available\s+|nearby\s+)?(?:{wifi}\s+)?networks$|^(?:what|which)\s+{wifi}\s+networks\s+are\s+(?:available|nearby)$", t):
            return self._act(t, "wifi_networks")
        m = re.match(rf"^connect\s+(?:me\s+)?to\s+(?:the\s+)?(?:{wifi}\s+)?(?:network\s+)?(?:named\s+|called\s+)?(?P<ssid>.+?)\s+{wifi}(?:\s+network)?$", t) or \
            re.match(rf"^connect\s+(?:me\s+)?to\s+(?:the\s+)?{wifi}\s+(?:network\s+)?(?:named\s+|called\s+)?(?P<ssid>.+)$", t)
        if m:
            ssid = self._grp(m, "ssid", t, o)
            return self._act(t, "wifi_connect", ssid)
        if re.match(rf"^disconnect\s+(?:from\s+)?(?:the\s+)?{wifi}$", t):
            return self._act(t, "wifi_disconnect")

        # ---------------- Bluetooth device connect / disconnect ----------------
        if not re.search(rf"{wifi}|network|internet|vpn|server|database", t):
            m = re.match(r"^(?:please\s+)?connect\s+(?:to\s+)?(?:my\s+|the\s+)?(?P<dev>.+?)(?:\s+(?:via|over|with|using)\s+blue\s?tooth)?$", t)
            if m and m.group("dev") not in {"it", "this", "that"}:
                return self._act(t, "bluetooth_connect", self._grp(m, "dev", t, o))
            m = re.match(r"^(?:please\s+)?disconnect\s+(?:from\s+)?(?:my\s+|the\s+)?(?P<dev>.+?)$", t)
            if m and m.group("dev") not in {"it", "this", "that"}:
                return self._act(t, "bluetooth_disconnect", self._grp(m, "dev", t, o))

        # ---------------- Volume / mic / brightness ----------------
        m = re.match(r"^(?:set|change|put|turn)\s+(?:the\s+)?(?:volume|sound)\s+(?:to|at|up to|down to)\s+(\d{1,3})\s*(?:%|percent)?$", t) or \
            re.match(r"^volume\s+(?:to\s+)?(\d{1,3})\s*(?:%|percent)?$", t)
        if m:
            return self._act(t, "set_volume", m.group(1))
        if t in {"what is the volume", "what's the volume", "volume level", "current volume"}:
            return self._act(t, "set_volume", "status")
        if re.match(r"^(?:mute|turn off|disable)\s+(?:the\s+|my\s+)?(?:mic|microphone)$", t):
            return self._act(t, "mic_mute", "on")
        if re.match(r"^(?:unmute|turn on|enable)\s+(?:the\s+|my\s+)?(?:mic|microphone)$", t):
            return self._act(t, "mic_mute", "off")
        if t in {"is my mic muted", "is the mic muted", "is my microphone muted", "mic status", "microphone status"}:
            return self._act(t, "mic_mute", "status")
        m = re.match(r"^(?:set|change|put|turn)\s+(?:the\s+)?(?:screen\s+|display\s+)?brightness\s+(?:to|at|up to|down to)\s+(\d{1,3})\s*(?:%|percent)?$", t) or \
            re.match(r"^brightness\s+(?:to\s+)?(\d{1,3})\s*(?:%|percent)?$", t)
        if m:
            return self._act(t, "set_brightness", m.group(1))
        if re.match(r"^(?:increase|raise|turn up)\s+(?:the\s+)?(?:screen\s+)?brightness$|^brightness\s+up$|^(?:make\s+(?:the\s+)?screen\s+)?brighter$", t):
            return self._act(t, "set_brightness", "up")
        if re.match(r"^(?:decrease|lower|reduce|turn down|dim)\s+(?:the\s+)?(?:screen|display)?\s*(?:brightness)?$|^brightness\s+down$|^(?:make\s+(?:the\s+)?screen\s+)?dimmer$", t):
            return self._act(t, "set_brightness", "down")
        if t in {"what is the brightness", "what's the brightness", "brightness level", "current brightness"}:
            return self._act(t, "set_brightness", "status")

        # ---------------- Devices & settings ----------------
        m = re.match(r"^(?:list|show|what are)\s+(?:all\s+|my\s+|the\s+)?(?:connected\s+)?(?P<cat>usb|hardware|keyboards?|mice|mouse|cameras?|webcams?|monitors?|displays?|printers?|disks?|drives?)?\s*devices?(?:\s+(?:are\s+)?(?:connected|plugged in|attached))?$", t) or \
            re.match(r"^what\s+(?:devices|hardware)\s+(?:is|are)\s+(?:connected|plugged in|attached)$", t) or \
            re.match(r"^(?:list|show)\s+(?:my\s+|the\s+|connected\s+)?(?P<cat>keyboards|mice|cameras|webcams|monitors|displays|printers)$", t)
        if m:
            cat = (m.groupdict().get("cat") or "").lower()
            cat = {"mice": "mouse", "webcam": "camera", "webcams": "camera", "displays": "monitor", "display": "monitor",
                   "hardware": "", "drives": "disk", "drive": "disk"}.get(cat, cat.rstrip("s") if cat not in {"usb"} else cat)
            return self._act(t, "list_devices", cat)
        if re.match(r"^(?:list|show|what are)\s+(?:my\s+|the\s+)?(?:audio|sound)\s+devices$|^(?:list|show|what are)\s+(?:my\s+|the\s+)?(?:speakers|microphones|mics)(?:\s+and\s+(?:speakers|microphones|mics))?$", t):
            return self._act(t, "audio_devices")
        m = re.match(r"^(?:open|show|go to)\s+(?:the\s+)?(?P<page>bluetooth|wi-?fi|sound|audio|display|network|battery|power|privacy|microphone|camera|windows update|update|apps|mouse|touchpad|keyboard|notifications|storage|printers|devices)\s+settings$", t)
        if m:
            return self._act(t, "open_settings", m.group("page"))

        # ---------------- Power ----------------
        if t in {"cancel shutdown", "abort shutdown", "cancel restart", "don't shut down", "stop the shutdown"}:
            return self._act(t, "power_action", "cancel")
        m = re.match(r"^(?:please\s+)?(shut\s*down|power\s+off|restart|reboot|sign\s+out|log\s+(?:off|out)|sleep)(?:\s+(?:the\s+|my\s+)?(?:pc|computer|laptop|system|machine))?(?:\s+now)?$", t) or \
            re.match(r"^(?:please\s+)?(turn\s+off|put)\s+(?:the\s+|my\s+)?(?:pc|computer|laptop|system|machine)(?:\s+to\s+sleep)?(?:\s+now)?$", t)
        if m:
            word = m.group(1)
            kind = ("restart" if word in {"restart", "reboot"} else
                    "sign_out" if word.startswith(("sign", "log")) else
                    "sleep" if word == "sleep" or "to sleep" in t else "shutdown")
            return self._act(t, "power_action", kind)

        # ---------------- Files ----------------
        m = re.match(r"^(?:give|grant|allow)\s+(?:you\s+|mxb\s+)?(?:full\s+|complete\s+)?(?:file\s+)?access\s+to\s+(?:all\s+(?:my\s+)?files|everything|all\s+drives|my\s+(?:whole|entire)\s+(?:computer|pc|disk))$", t) or \
            re.match(r"^(?:give|grant)\s+(?:you\s+|mxb\s+)?full\s+(?:file\s+)?access$|^you\s+can\s+access\s+all\s+(?:my\s+)?files$", t)
        if m:
            return self._act(t, "grant_file_access", "all")
        m = re.match(r"^(?:give|grant|allow)\s+(?:you\s+|mxb\s+)?(?:file\s+)?access\s+to\s+(?:the\s+|my\s+)?(?P<loc>.+)$", t)
        if m:
            loc = self._grp(m, "loc", t, o)
            return self._act(t, "grant_file_access", loc)
        m = re.match(r"^(?:revoke|remove|take away)\s+(?:your\s+)?(?:file\s+)?access\s*(?:to|from)?\s*(?:the\s+|my\s+)?(?P<loc>.*)$", t)
        if m:
            return self._act(t, "revoke_file_access", m.group("loc").strip() or "all")
        if re.match(r"^(?:what|which)\s+(?:files|folders|drives)\s+can\s+you\s+access$|^(?:show|list)\s+(?:your\s+)?file\s+access$", t):
            return self._act(t, "list_file_access")

        file_word = r"(?:file|files|document|documents|folder|pdf|photo|image|picture|video|song)"
        m = re.match(rf"^(?:please\s+)?(?:find|search\s+for|locate|where\s+is|look\s+for)\s+(?:the\s+|my\s+|a\s+)?{file_word}\s+(?:named\s+|called\s+)?(?P<q>.+?)(?:\s+in\s+(?:the\s+|my\s+)?(?P<root>.+))?$", t)
        if m:
            q = self._grp(m, "q", t, o)
            root = self._grp(m, "root", t, o) if m.group("root") else ""
            return self._act(t, "find_files", f"{q} :: {root}" if root else q)

        m = re.match(r"^(?:please\s+)?(?:read|open and read|show me)\s+(?:the\s+|my\s+)?(?:file\s+|document\s+)(?P<p>.+)$", t) or \
            re.match(r"^(?:please\s+)?(?:read|what(?:'s|\s+is)\s+in)\s+(?:the\s+|my\s+)?(?:file\s+)?(?P<p>[\w\s\-\.\\/:]+\.\w{1,5})$", t)
        if m:
            path = self._grp(m, "p", t, o)
            return self._act(t, "read_file", path)
        m = re.match(r"^(?:please\s+)?(?:summarize|summarise|explain)\s+(?:the\s+|my\s+)?(?:file|document|pdf)\s+(?P<p>.+)$", t)
        if m:
            path = self._grp(m, "p", t, o)
            return self._act(t, "read_file", f"{path} :: Summarize this file in 3 short sentences.")

        m = re.match(r"^(?:please\s+)?open\s+(?:the\s+|my\s+)?(?:file|folder|document|pdf)\s+(?:named\s+|called\s+)?(?P<p>.+)$", t)
        if m and m.group("p") not in {"explorer", "manager", "history"}:
            path = self._grp(m, "p", t, o)
            return self._act(t, "open_path", path, speak_result=False)

        m = re.match(r"^(?:please\s+)?(permanently\s+delete|delete\s+permanently|delete|remove|trash)\s+(?:the\s+|my\s+)?(?:file|folder|document)\s+(?P<p>.+?)(?:\s+permanently)?$", t)
        if m:
            path = self._grp(m, "p", t, o)
            permanent = "permanent" in t
            return self._act(t, "delete_file", f"{path} :: permanent" if permanent else path)

        m = re.match(r"^(?:please\s+)?(move|copy)\s+(?:the\s+|my\s+)?(?:file\s+|folder\s+)?(?P<src>.+?)\s+(?:to|into)\s+(?:the\s+|my\s+)?(?P<dst>.+)$", t)
        if m and m.group("src") not in {"window", "this window", "mouse", "cursor", "it", "this", "that", "the window"} \
                and not re.search(r"(window|mouse|cursor|screen|monitor)", m.group("src")):
            src = self._grp(m, "src", t, o)
            dst = self._grp(m, "dst", t, o)
            return self._act(t, "move_file" if m.group(1) == "move" else "copy_file", f"{src} :: {dst}")

        m = re.match(r"^(?:please\s+)?rename\s+(?:the\s+|my\s+)?(?:file\s+|folder\s+)?(?P<src>.+?)\s+(?:to|as)\s+(?P<dst>.+)$", t)
        if m:
            src = self._grp(m, "src", t, o)
            dst = self._grp(m, "dst", t, o)
            return self._act(t, "rename_file", f"{src} :: {dst}")

        # ---------------- Graceful / forced close ----------------
        m = re.match(r"^(?:please\s+)?force\s+(?:close|quit|kill)\s+(?P<app>[\w\s\.]+)$", t)
        if m:
            return self._act(t, "force_close_app", m.group("app").strip())

        # ---------------- Agent mode ----------------
        m = re.match(r"^(?:agent|autopilot|agent mode|take over)\s*[:,]?\s+(?P<goal>.+)$", t)
        if m:
            goal = self._grp(m, "goal", t, o)
            self.tts.speak("On it. I'll work through it step by step. Say stop any time.")
            res = self.executor.execute_action("agent_task", goal)
            self.tts.speak(res)
            self.history.append({"user": t, "mxb": res})
            return f"MXB: {res}"

        return None
