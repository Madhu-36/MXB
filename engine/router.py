import re
import json
import requests
import traceback
from collections import deque
from engine.executor import OSExecutionManager
from engine.tts import VoiceSynthesizer
from engine.memory import MemoryBank
from utils.credentials import CredentialsManager

class IntentRouter:
    def __init__(self):
        self.executor = OSExecutionManager()
        self.tts = VoiceSynthesizer()
        self.memory = MemoryBank()
        # Keep track of the last 5 conversation turns
        self.history = deque(maxlen=5)

    def route(self, transcription: str) -> str:
        text = transcription.lower().strip()
        if not text:
            return "Ignored empty transcription."

        # Remove trailing punctuation from transcription
        clean_text = re.sub(r'[\.,!\?]+$', '', text).strip()
        print(f"[Router] Parsing intent: '{clean_text}'")

        # =========================================================================
        # Layer 1: High-Speed Deterministic Fast-Path Routing (Sub-millisecond)
        # =========================================================================

        # 1. System Telemetry / Hardware Check
        if any(p in clean_text for p in [
            "check system", "system status", "how is my pc", "how is my computer",
            "pc metrics", "cpu usage", "ram usage", "battery percentage", "battery status",
            "check hardware", "pc status"
        ]):
            reply = "Checking your hardware status now."
            self.tts.speak(reply)
            metrics = self.executor.execute_action("check_system", "none")
            self.tts.speak(metrics)
            self.history.append({"user": clean_text, "mxb": metrics})
            return f"MXB: {reply}\n{metrics}"

        # 2. Window Management (Must be checked before open/close apps)
        if any(p in clean_text for p in ["minimize this window", "minimize window", "minimize this", "minimize screen"]):
            reply = "Minimizing current window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "minimize")
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["maximize this window", "maximize window", "maximize this", "maximize screen"]):
            reply = "Maximizing current window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "maximize")
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\nAction: {res}"

        if clean_text in ["close window", "close this window", "close active window"]:
            reply = "Closing active window."
            self.tts.speak(reply)
            res = self.executor.execute_action("manage_window", "close")
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\nAction: {res}"

        # 3. Media Controls
        if any(p in clean_text for p in ["volume up", "turn up volume", "turn up the volume", "louder", "increase volume"]):
            reply = "Turning volume up."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "volume_up")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["volume down", "turn down volume", "turn down the volume", "quieter", "lower volume"]):
            reply = "Turning volume down."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "volume_down")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["mute audio", "mute sound", "mute volume", "mute", "unmute audio", "unmute sound", "unmute"]):
            reply = "Toggling mute."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "mute")
            return f"MXB: {reply}\nAction: {res}"

        if any(p in clean_text for p in ["play music", "pause music", "pause playback", "resume music", "play song"]):
            reply = "Toggling media playback."
            self.tts.speak(reply)
            res = self.executor.execute_action("media_control", "play")
            return f"MXB: {reply}\nAction: {res}"

        # 4. App Launching
        launch_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:open|launch|start)\s+(?:up\s+)?([a-zA-Z0-9\s]+)$', clean_text)
        if launch_match:
            app_name = launch_match.group(1).strip()
            app_name = re.sub(r'\s+please$', '', app_name).strip()
            if app_name and app_name not in ["the door", "a tab"]:
                reply = f"Opening {app_name} for you."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("open_app", app_name)

        # 5. App Closing / Killing
        close_match = re.search(r'^(?:please\s+)?(?:can you\s+)?(?:close|kill|quit|terminate|exit)\s+([a-zA-Z0-9\s]+)$', clean_text)
        if close_match:
            target_app = close_match.group(1).strip()
            if target_app and target_app not in ["window", "this window", "the window", "active window"]:
                reply = f"Closing {target_app}."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\n" + self.executor.execute_action("close_app", target_app)

        # 6. Screen Capture
        if re.search(r'\b(screenshot|capture screen|print screen|take a screenshot)\b', clean_text):
            reply = "Capturing your screen."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("capture_screen", "")

        # 7. Direct Keystroke Typing
        if clean_text.startswith("type "):
            extracted_text = clean_text.split("type ", 1)[1]
            reply = "Typing that now."
            self.tts.speak(reply)
            self.history.append({"user": clean_text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("type_text", extracted_text)

        # 8. Web Search
        search_match = re.search(r'^(?:search the web for|search for|search|google|look up)\s+(.+)$', clean_text)
        if search_match:
            query = search_match.group(1).strip()
            reply = f"Searching the web for {query}."
            self.tts.speak(reply)
            summary = self.executor.execute_action("search_web", query)
            self.tts.speak(summary)
            self.history.append({"user": clean_text, "mxb": summary})
            return f"MXB: {reply}\n{summary}"

        # 9. Clipboard Intelligence
        if any(p in clean_text for p in ["summarize clipboard", "analyze clipboard", "read clipboard", "explain clipboard", "what did i copy", "what i just copied"]):
            reply = "Reading your clipboard now."
            self.tts.speak(reply)
            analysis = self.executor.execute_action("analyze_clipboard", "summarize clearly in 1 or 2 sentences")
            self.tts.speak("Here is the analysis of your clipboard.")
            self.history.append({"user": clean_text, "mxb": analysis})
            return f"MXB: {reply}\n{analysis}"

        # 10. Memory Saving
        if clean_text.startswith("remember that ") or clean_text.startswith("remember "):
            fact = re.sub(r'^remember(?:\s+that)?\s+', '', clean_text).strip()
            if fact:
                self.memory.remember(fact)
                reply = f"I've saved that to my long-term memory."
                self.tts.speak(reply)
                self.history.append({"user": clean_text, "mxb": reply})
                return f"MXB: {reply}\nSaved: {fact}"

        # =========================================================================
        # Layer 2: Conversational "Second Brain" Speech Understanding
        # =========================================================================
        print("[Router] No direct fast-path match. Sending to LLM Speech Understanding...")
        return self._route_to_llm(transcription)

    def _query_nvidia_llm(self, prompt: str, api_key: str) -> dict | None:
        """High-speed speech understanding via NVIDIA Build Cloud LLM (0.3s latency)."""
        url = "https://integrate.api.nvidia.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        system_prompt = (
            "You are MXB (Machine eXecutive Brain), a high-speed AI executive brain for the user.\n"
            "You MUST respond with ONLY valid JSON containing EXACTLY three keys: \"action\", \"target\", and \"reply\".\n\n"
            "Available Actions:\n"
            "- \"open_app\": Open application (target: exact app name)\n"
            "- \"close_app\": Close application (target: exact app name)\n"
            "- \"type_text\": Type dictated text on keyboard (target: text to type)\n"
            "- \"search_web\": Search online (target: search query)\n"
            "- \"media_control\": Volume/playback (target: volume_up, volume_down, mute, play, pause)\n"
            "- \"manage_window\": Window control (target: minimize, maximize, close)\n"
            "- \"notify\": Windows desktop toast (target: message)\n"
            "- \"check_system\": Hardware metrics (target: none)\n"
            "- \"remember_fact\": Save to long-term memory (target: fact to save)\n"
            "- \"analyze_clipboard\": Analyze clipboard (target: instruction)\n"
            "- \"conversation\": Answer general questions, trivia, coding help directly (target: none)\n"
        )
        payload = {
            "model": "meta/llama-3.1-8b-instruct",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.2,
            "max_tokens": 150,
            "response_format": {"type": "json_object"}
        }
        resp = requests.post(url, headers=headers, json=payload, timeout=8)
        if resp.status_code == 200:
            content = resp.json()["choices"][0]["message"]["content"].strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            return json.loads(content.strip())
        else:
            print(f"[NVIDIA Build LLM] Response {resp.status_code}: {resp.text}")
            return None

    def _route_to_llm(self, text: str) -> str:
        try:
            # 1. Fetch relevant User Memories
            saved_memories = self.memory.get_memories(query=text, limit=5)
            memory_context = ""
            if saved_memories:
                memory_context = "User's Saved Memories:\n" + "\n".join([f"- {m}" for m in saved_memories]) + "\n\n"
                
            # 2. Add Recent Conversation Context
            history_context = "Recent Conversation Context:\n"
            if not self.history:
                history_context += "No previous context.\n\n"
            else:
                for turn in self.history:
                    history_context += f"User: {turn['user']}\nMXB: {turn['mxb']}\n"
                history_context += "\n"

            # 3. Add Current System Time
            from datetime import datetime
            current_time = datetime.now().strftime("%A, %B %d, %Y - %I:%M %p")
            time_context = f"Current System Time: {current_time}\n\n"

            # 4. Add Active Window Context
            active_window_context = ""
            try:
                import pygetwindow as gw
                active_window = gw.getActiveWindow()
                if active_window and active_window.title:
                    active_window_context = f"User's Current Active Window: '{active_window.title}'\n\n"
            except Exception:
                pass

            # 5. Add Environment Context (Weather/Location)
            from utils.environment import EnvironmentContext
            env_context = f"User's Physical Environment: {EnvironmentContext.get_weather_and_location()}\n\n"

            augmented_prompt = f"{memory_context}{history_context}{time_context}{active_window_context}{env_context}User Command: '{text}'"

            action_data = None

            # Path A: Try NVIDIA Build Cloud LLM (Ultra-fast cloud inference ~0.3s)
            nv_key = CredentialsManager.get_nvidia_api_key()
            if nv_key:
                try:
                    print("[Router] Querying NVIDIA Build Cloud LLM for speech understanding...")
                    action_data = self._query_nvidia_llm(augmented_prompt, nv_key)
                except Exception as e:
                    print(f"[Router] NVIDIA Build LLM exception: {e}. Falling back to local Ollama...")
                    action_data = None

            # Path B: Local Ollama CPU Fallback
            if not action_data:
                print("[Router] Using local Ollama engine fallback...")
                payload = {
                    "model": "mxb-brain",
                    "prompt": augmented_prompt,
                    "stream": False,
                    "format": "json",
                    "keep_alive": "1h",
                    "options": {
                        "num_predict": 100, 
                        "num_ctx": 1024, 
                        "temperature": 0.2,
                        "num_thread": 4
                    }
                }
                
                response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=45)
                if response.status_code == 404:
                    error = "I cannot reach my AI brain. Please verify Ollama is running."
                    self.tts.speak(error)
                    return error
                    
                response.raise_for_status()
                data = response.json()
                raw_response = data.get("response", "{}").strip()
                if raw_response.startswith("```json"):
                    raw_response = raw_response[7:]
                if raw_response.startswith("```"):
                    raw_response = raw_response[3:]
                if raw_response.endswith("```"):
                    raw_response = raw_response[:-3]
                action_data = json.loads(raw_response.strip())

            action = action_data.get("action", "unknown")
            target = action_data.get("target", "none")
            reply = action_data.get("reply", "")
            
            if reply:
                self.tts.speak(reply)
                self.history.append({"user": text, "mxb": reply})
            
            if action not in ["unknown", "conversation", "none"]:
                exec_result = self.executor.execute_action(action, target)
                return f"MXB: {reply}\nAction: {exec_result}"
            
            return f"MXB: {reply}"
            
        except requests.exceptions.ReadTimeout:
            timeout_msg = "My deep-reasoning model is taking a while on this CPU. Let me know if you want me to perform a specific OS action."
            self.tts.speak(timeout_msg)
            return f"MXB: {timeout_msg}"
        except requests.exceptions.ConnectionError:
            error = "Ollama is not running. Please start the Ollama server."
            self.tts.speak(error)
            return error
        except Exception as e:
            traceback.print_exc()
            return f"Speech Understanding failed: {str(e)}"
