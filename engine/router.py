import re
import json
import requests
import traceback
from collections import deque
from engine.executor import OSExecutionManager
from engine.tts import VoiceSynthesizer
from engine.memory import MemoryBank

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

        print(f"[Router] Parsing intent: '{text}'")

        # Layer 1: Fast Regex intercept for super common commands
        launch_match = re.search(r'\b(open|launch|start)\s+([a-zA-Z0-9\s]+)\b', text)
        if launch_match:
            app_name = launch_match.group(2).strip()
            reply = f"Opening {app_name} for you."
            self.tts.speak(reply)
            self.history.append({"user": text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("open_app", app_name)

        if re.search(r'\b(screenshot|capture screen|print screen)\b', text):
            reply = "Capturing your screen."
            self.tts.speak(reply)
            self.history.append({"user": text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("capture_screen", "")
            
        if "type " in text:
            extracted_text = text.split("type ", 1)[1]
            reply = "Typing that now."
            self.tts.speak(reply)
            self.history.append({"user": text, "mxb": reply})
            return f"MXB: {reply}\n" + self.executor.execute_action("type_text", extracted_text)

        # Layer 2: Conversational "Second Brain" Route
        print("[Router] Sending to LLM Second Brain...")
        return self._route_to_llm(transcription)

    def _route_to_llm(self, text: str) -> str:
        try:
            # 1. Fetch User Memories to inject into the LLM context
            saved_memories = self.memory.get_memories()
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

            # 4. Augment the user's prompt
            augmented_prompt = f"{memory_context}{history_context}{time_context}User Command: '{text}'"

            payload = {
                "model": "mxb-brain",
                "prompt": augmented_prompt,
                "stream": False,
                "format": "json",
                "keep_alive": "1h",
                "options": {
                    "num_predict": 200, 
                    "num_ctx": 4096, 
                    "temperature": 0.2 
                }
            }
            
            response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=15)
            
            if response.status_code == 404:
                error = "I cannot reach my AI brain. Please run the build_llm batch file."
                self.tts.speak(error)
                return error
                
            response.raise_for_status()
            data = response.json()
            raw_response = data.get("response", "{}")
            
            print(f"[LLM Output] {raw_response}")
            
            # Clean potential Markdown wrapping (Llama 3.1 often does this even with JSON format enforced)
            cleaned_response = raw_response.strip()
            if cleaned_response.startswith("```json"):
                cleaned_response = cleaned_response[7:]
            if cleaned_response.startswith("```"):
                cleaned_response = cleaned_response[3:]
            if cleaned_response.endswith("```"):
                cleaned_response = cleaned_response[:-3]
            cleaned_response = cleaned_response.strip()
            
            try:
                action_data = json.loads(cleaned_response)
            except json.JSONDecodeError as e:
                print(f"[Router] JSON Decode Error on LLM output: {e}")
                action_data = {"action": "conversation", "target": "none", "reply": "I'm sorry, I failed to process my own thoughts."}
                
            action = action_data.get("action", "unknown")
            target = action_data.get("target", "none")
            reply = action_data.get("reply", "")
            
            # Speak the conversational reply
            if reply:
                self.tts.speak(reply)
                self.history.append({"user": text, "mxb": reply})
            
            # Execute physical OS actions if necessary
            if action not in ["unknown", "conversation", "none"]:
                exec_result = self.executor.execute_action(action, target)
                
                # If it was a clipboard analysis, we might want to speak the first sentence or let the user read it
                if action == "analyze_clipboard":
                    # Speak just the first bit so we don't read a massive essay out loud
                    short_reply = "Here is the summary of your clipboard."
                    self.tts.speak(short_reply)
                    
                return f"MXB: {reply}\nAction: {exec_result}"
            
            return f"MXB: {reply}"
            
        except requests.exceptions.ConnectionError:
            error = "Ollama is not running. Please start the Ollama server."
            self.tts.speak(error)
            return error
        except Exception as e:
            traceback.print_exc()
            return f"LLM Routing failed: {str(e)}"
