import re
import json
import time
import requests
import traceback
from pathlib import Path
from collections import deque
from rapidfuzz import fuzz
from engine.executor import OSExecutionManager
from engine.tts import VoiceSynthesizer
from engine.memory import memory_bank
from utils.credentials import CredentialsManager
from utils.environment import EnvironmentContext
from utils.math_evaluator import SafeMathEvaluator
from utils.logger import log

class IntentRouter:
    """
    Two-Tier Intent Routing Engine for MXB.
    Tier 1: High-Speed Sub-Millisecond Deterministic Fast-Path with fuzzy matching.
    Tier 2: Deep LLM Multi-Step Action Planning and Conversational Reasoning.
    """

    def __init__(self, config_path: str = None):
        self.executor = OSExecutionManager()
        self.tts = VoiceSynthesizer()
        self.memory = memory_bank
        self.history = deque(maxlen=6)

        # Load config
        self.config_path = Path(config_path) if config_path else Path(__file__).parent.parent / "config.json"
        self.config = self._load_config()

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
        log.info(f"IntentRouter: Routing intent for '{clean_text}'")

        # =========================================================================
        # TIER 1: HIGH-SPEED DETERMINISTIC FAST-PATH (Sub-Millisecond)
        # =========================================================================

        # 0. Emergency Voice Interruption (<1ms)
        if clean_text in ["stop", "cancel", "halt", "pause", "abort", "freeze", "stop executing", "cancel action", "shut up"]:
            log.warning("Router: Emergency Voice Interruption Triggered!")
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

        # 0.3. Mathematical Query Fast-Path (<0.5ms)
        math_solution = SafeMathEvaluator.try_solve(clean_text)
        if math_solution:
            self.tts.speak(math_solution)
            self.history.append({"user": clean_text, "mxb": math_solution})
            return f"MXB: {math_solution}"

        # 1. System Health / Telemetry
        if any(p in clean_text for p in [
            "check system", "system status", "pc status", "how is my pc", "how is my computer",
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
        launch_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:open|launch|start)\s+(?:up\s+)?([a-zA-Z0-9\s]+)$', clean_text)
        if launch_match:
            app_name = launch_match.group(1).strip()
            if app_name and app_name not in ["the door", "a tab", "window", "folder"]:
                reply = f"Opening {app_name} for you."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("open_app", app_name)

        # 10. App Closing
        close_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:close|kill|quit|terminate|exit)\s+([a-zA-Z0-9\s]+)$', clean_text)
        if close_match:
            target_app = close_match.group(1).strip()
            if target_app and target_app not in ["window", "this window", "active window"]:
                reply = f"Closing {target_app}."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("close_app", target_app)

        # 11. Direct Text Typing
        if clean_text.startswith("type "):
            extracted = clean_text.split("type ", 1)[1]
            reply = "Typing that now."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("type_text", extracted)

        # 12. File System Operations
        if clean_text.startswith("create folder ") or clean_text.startswith("make folder "):
            fname = re.sub(r'^(?:create|make)\s+folder\s+', '', clean_text).strip()
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
        search_match = re.search(r'^(?:search the web for|search for|search|google|look up)\s+(.+)$', clean_text)
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
            fact = re.sub(r'^remember(?:\s+that)?\s+', '', clean_text).strip()
            if fact:
                self.memory.remember(fact)
                reply = "I've saved that to my long-term memory."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\nSaved: {fact}"

        # =========================================================================
        # TIER 2: LLM MULTI-STEP ACTION PLANNER & SECOND BRAIN REASONING
        # =========================================================================
        log.info("IntentRouter: No direct match in Tier 1. Delegating to LLM Multi-Step Planner...")
        return self._route_to_llm(transcription, feedback_callback=feedback_callback)

    @staticmethod
    def _clean_and_parse_json(raw: str) -> dict | None:
        if not raw:
            return None
        text = raw.strip()
        # Strip markdown fences
        if text.startswith("```json"):
            text = text[7:]
        elif text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        # Try standard JSON parsing first
        try:
            return json.loads(text)
        except Exception:
            pass

        # Try extracting between first { and last }
        first_brace = text.find("{")
        last_brace = text.rfind("}")
        if first_brace != -1 and last_brace != -1 and last_brace > first_brace:
            sub = text[first_brace:last_brace + 1]
            try:
                return json.loads(sub)
            except Exception:
                pass

        # Resilient Regex fallback for truncated or malformed responses
        reply = ""
        reply_match = re.search(r'"reply"\s*:\s*"([^"]*)', text)
        if reply_match:
            reply = reply_match.group(1).strip()

        plan = []
        # Find all steps {"action": "...", "target": "..."}
        step_matches = re.findall(r'\{\s*"action"\s*:\s*"([^"]+)"(?:\s*,\s*"target"\s*:\s*"([^"]*)")?\s*\}', text)
        for sm in step_matches:
            plan.append({"action": sm[0], "target": sm[1] if len(sm) > 1 else ""})

        if reply or plan:
            return {"reply": reply, "plan": plan}

        # If model answered in plain natural language instead of JSON
        if text and not text.startswith("{"):
            return {"reply": text, "plan": []}

        return None

    def _query_nvidia_llm(self, prompt: str, api_key: str) -> dict | None:
        cfg_llm = self.config.get("llm", {})
        url = cfg_llm.get("api_url", "https://integrate.api.nvidia.com/v1/chat/completions")
        model_name = cfg_llm.get("model", "meta/llama-3.1-8b-instruct")

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        system_prompt = (
            "You are MXB (Machine eXecutive Brain), an ultra-fast AI desktop assistant capable of full computer operation.\n"
            "You MUST respond ONLY with valid JSON.\n\n"
            "JSON Format:\n"
            "{\n"
            '  "reply": "Concise spoken confirmation or answer",\n'
            '  "plan": [\n'
            '    {"action": "<action_name>", "target": "<target_value>", "duration": 0.0}\n'
            '  ]\n'
            "}\n\n"
            "Available Actions:\n"
            '- "open_app": (target: app name)\n'
            '- "close_app": (target: app name)\n'
            '- "click_text": (target: button/text label to click on screen)\n'
            '- "left_click": (target: "x,y" or "")\n'
            '- "right_click": (target: "x,y" or "")\n'
            '- "double_click": (target: "x,y" or "")\n'
            '- "drag_and_drop": (target: "x1, y1 -> x2, y2")\n'
            '- "scroll": (target: "down" or "up")\n'
            '- "type_text": (target: text to type)\n'
            '- "press_key": (target: enter, esc, tab, backspace, space, etc.)\n'
            '- "shortcut": (target: ctrl+c, ctrl+v, ctrl+t, ctrl+l, alt+tab, win+d, etc.)\n'
            '- "manage_window": (target: minimize, maximize, close, left, right)\n'
            '- "show_desktop": (target: "")\n'
            '- "open_url": (target: website url)\n'
            '- "search_web": (target: search query)\n'
            '- "create_folder": (target: folder name or path)\n'
            '- "create_file": (target: "filename.txt :: file contents")\n'
            '- "list_files": (target: folder name)\n'
            '- "check_system": (target: "")\n'
            '- "capture_screen": (target: "")\n'
            '- "read_screen": (target: "")\n'
            '- "remember_fact": (target: fact to store)\n'
            '- "analyze_clipboard": (target: instruction)\n'
            '- "wait": (target: duration in seconds, e.g. "1.5")\n'
            '- "conversation": (target: none - just provide the answer in the reply field)\n\n'
            "For compound instructions (e.g. 'open notepad and type hello', 'open chrome and search X'), break them down into ordered plan steps!"
        )

        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 250,
            "response_format": {"type": "json_object"}
        }

        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"]
            return self._clean_and_parse_json(content)
        else:
            log.warning(f"NVIDIA Build LLM returned {resp.status_code}: {resp.text}")
            return None

    def _route_to_llm(self, text: str, feedback_callback=None) -> str:
        try:
            # 1. Fetch relevant user memories
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
                active = gw.getActiveWindow()
                if active and active.title:
                    active_window_context = f"Active Window: '{active.title}'\n\n"
            except Exception:
                pass

            # 4. Environmental context (cached)
            env_context = f"{EnvironmentContext.get_weather_and_location()}\n\n"

            augmented_prompt = f"{memory_context}{history_context}{active_window_context}{env_context}User Command: '{text}'"

            plan_data = None

            # Path A: NVIDIA Build Cloud LLM
            nv_key = CredentialsManager.get_nvidia_api_key()
            if nv_key:
                try:
                    log.info("Router: Planning with NVIDIA Cloud LLM...")
                    plan_data = self._query_nvidia_llm(augmented_prompt, nv_key)
                except Exception as e:
                    log.warning(f"NVIDIA Cloud LLM exception: {e}. Falling back to Ollama...")
                    plan_data = None

            # Path B: Fast Local Ollama Fallback (llama3.2:1b or mxb-brain)
            if not plan_data:
                local_model = self.config.get("llm", {}).get("local_model", "llama3.2:1b")
                log.info(f"Router: Planning with Local Ollama fallback ({local_model})...")
                system_instruction = (
                    "You are MXB, an AI desktop assistant. Respond ONLY with valid JSON.\n"
                    "JSON Format: {\"reply\": \"Spoken answer\", \"plan\": [{\"action\": \"<action>\", \"target\": \"<target>\"}]}\n"
                    "Available Actions: open_app, close_app, type_text, press_key, shortcut, scroll, click_text, manage_window, show_desktop, conversation."
                )
                payload = {
                    "model": local_model,
                    "messages": [
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": augmented_prompt}
                    ],
                    "stream": False,
                    "format": "json",
                    "keep_alive": "2h",
                    "options": {
                        "num_predict": 250,
                        "num_ctx": 1024,
                        "num_thread": 4,
                        "temperature": 0.1
                    }
                }
                resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=25)
                if resp.status_code == 200:
                    raw_resp = resp.json().get("message", {}).get("content", "{}").strip()
                    plan_data = self._clean_and_parse_json(raw_resp)

            if not plan_data:
                fallback_msg = "I understood your request but could not reach my reasoning engine."
                self.tts.speak(fallback_msg)
                return fallback_msg

            reply = plan_data.get("reply", "")
            steps = plan_data.get("plan", [])

            # Handle older single-action format if returned
            if not steps and "action" in plan_data and plan_data["action"] not in ["unknown", "conversation", "none"]:
                steps = [{"action": plan_data["action"], "target": plan_data.get("target", "")}]

            if reply:
                reply = re.sub(r'^(?:mxb\s*:\s*)+', '', reply, flags=re.IGNORECASE).strip()
                self.tts.speak(reply)
                self.history.append({"user": text, "mxb": reply})

            if steps:
                results = self.executor.planner.execute_plan(steps, feedback_callback=feedback_callback)
                summary_actions = "; ".join(results)
                return f"MXB: {reply}\nActions: {summary_actions}"

            return f"MXB: {reply}"

        except Exception as e:
            traceback.print_exc()
            log.error(f"Router LLM Error: {e}")
            return f"Speech Understanding Error: {e}"
