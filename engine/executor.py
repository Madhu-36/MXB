import os
import subprocess
import webbrowser
import traceback
import pyperclip
import requests
from pynput.keyboard import Controller, Key
import pywinauto
from engine.memory import MemoryBank

class OSExecutionManager:
    def __init__(self):
        self.keyboard = Controller()
        self.memory = MemoryBank()

    def execute_action(self, action: str, target: str) -> str:
        print(f"[Executor] Executing -> Action: {action}, Target: {target}")
        
        if action == "open_app":
            return self.launch_app(target)
            
        elif action == "close_app":
            try:
                os.system(f"taskkill /F /IM {target}.exe")
                return f"Closed {target}"
            except Exception as e:
                return f"Failed to close {target}: {e}"
                
        elif action == "type_text":
            return self.type_text(target)
            
        elif action == "search_web":
            webbrowser.open(f"https://www.google.com/search?q={target}")
            return f"Searched the web for: {target}"
            
        elif action == "media_control":
            return self.control_volume(target)
            
        elif action == "remember_fact":
            self.memory.remember(target)
            return f"Memory saved: {target}"
            
        elif action == "analyze_clipboard":
            return self.analyze_clipboard(target)
            
        else:
            print(f"[Executor] Unsupported action: {action}")
            return f"Action '{action}' is not supported yet."

    def analyze_clipboard(self, instruction: str) -> str:
        print("[Executor] Reading system clipboard...")
        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content or clipboard_content.strip() == "":
                return "Your clipboard is currently empty."
                
            print(f"[Executor] Found {len(clipboard_content)} characters in clipboard. Asking LLM to analyze...")
            
            # We use the standard llama3.1 model here (not mxb-brain) because we want raw text back, not JSON
            payload = {
                "model": "llama3.1",
                "prompt": f"You are MXB, acting as the user's Second Brain.\n\nHere is the exact content currently copied to their system clipboard:\n\"\"\"{clipboard_content}\"\"\"\n\nThe user has asked you to do this with it: {instruction}\n\nProvide your analysis or summary concisely:",
                "stream": False
            }
            
            response = requests.post("http://localhost:11434/api/generate", json=payload, timeout=45)
            response.raise_for_status()
            
            result_text = response.json().get("response", "Failed to parse clipboard.")
            print(f"[Clipboard Analysis] {result_text}")
            
            return f"Clipboard Analysis:\n{result_text}"
            
        except Exception as e:
            traceback.print_exc()
            return f"Failed to analyze clipboard: {e}"

    def launch_app(self, app_name: str) -> str:
        app_name_clean = app_name.lower().strip()
        print(f"[Executor] Attempting to launch: {app_name_clean}")
        try:
            app_map = {
                "notepad": "notepad.exe",
                "calculator": "calc.exe",
                "browser": "msedge.exe",
                "chrome": "chrome.exe",
                "spotify": "spotify.exe",
                "explorer": "explorer.exe",
                "cmd": "cmd.exe",
                "paint": "mspaint.exe"
            }
            exe = app_map.get(app_name_clean, f"{app_name_clean}.exe")
            os.startfile(exe) 
            return f"Launched {app_name}"
        except FileNotFoundError:
            print(f"[Executor] App {app_name} not found in PATH. Emulating Start Menu search...")
            try:
                self.keyboard.press(Key.cmd)
                self.keyboard.release(Key.cmd)
                import time; time.sleep(0.5)
                self.keyboard.type(app_name)
                time.sleep(0.5)
                self.keyboard.press(Key.enter)
                self.keyboard.release(Key.enter)
                return f"Searched start menu for {app_name}"
            except Exception as e:
                return f"App {app_name} not found."
        except Exception as e:
            traceback.print_exc()
            return f"Error launching {app_name}: {e}"

    def type_text(self, text: str) -> str:
        print(f"[Executor] Typing text: {text}")
        try:
            self.keyboard.type(text)
            return f"Typed: '{text}'"
        except Exception as e:
            traceback.print_exc()
            return f"Typing error: {e}"

    def control_volume(self, action: str) -> str:
        print(f"[Executor] Adjusting media: {action}")
        import keyboard as kb
        try:
            if action == "volume_up":
                kb.send("volume up")
            elif action == "volume_down":
                kb.send("volume down")
            elif action in ["mute", "unmute"]:
                kb.send("volume mute")
            elif action == "play" or action == "pause":
                kb.send("play/pause media")
            return f"Media control: {action}"
        except Exception as e:
            traceback.print_exc()
            return f"Media error: {e}"

    def capture_screen(self) -> str:
        print("[Executor] Capturing screen...")
        try:
            self.keyboard.press(Key.print_screen)
            self.keyboard.release(Key.print_screen)
            return "Screen captured to clipboard"
        except Exception as e:
            traceback.print_exc()
            return f"Screenshot error: {e}"
