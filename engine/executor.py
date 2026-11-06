import os
import subprocess
import webbrowser
import traceback
import pyperclip
import requests
import pygetwindow as gw
import psutil
from engine.memory import memory_bank
from utils.app_launcher import SmartAppLauncher
from engine.mouse import MouseController
from engine.keyboard_ext import KeyboardExtended
from engine.screen import ScreenVision
from engine.file_ops import FileOperationsManager
from engine.planner import ActionPlanner
from utils.logger import log

class OSExecutionManager:
    """
    Unified OS Execution Manager for MXB.
    Acts as the digital 'two hands' of the assistant, automating:
    - Mouse movement, clicks, drags, scrolling, and OCR text clicking
    - Full keyboard input, key combinations, and system shortcuts
    - Screen vision, active window inspection, and text extraction
    - File system creation, navigation, and deletion
    - Application lifecycle and Start Menu index execution
    """

    def __init__(self):
        self.mouse = MouseController()
        self.keyboard = KeyboardExtended()
        self.screen = ScreenVision()
        self.file_ops = FileOperationsManager()
        self.app_launcher = SmartAppLauncher()
        self.memory = memory_bank
        self.planner = ActionPlanner(self)

    def abort_current_action(self):
        log.warning("OSExecution: Aborting current action pipeline!")
        self.planner.abort()

    def execute_action(self, action: str, target: str = "") -> str:
        action = action.lower().strip().replace(" ", "_").replace("-", "_")

        # Action normalization and aliases
        if action in ["open_application", "start_app", "launch_app"]:
            action = "open_app"
        elif action in ["close_application", "terminate_app", "quit_app"]:
            action = "close_app"
        elif action in ["stop_action", "abort_action", "halt_action", "stop"]:
            self.abort_current_action()
            return "Actions stopped."
        elif action in ["manage_windows"]:
            action = "manage_window"

        log.info(f"OSExecution: Executing -> Action: '{action}', Target: '{target}'")

        try:
            # 1. Mouse Operations
            if action in ["left_click", "click"]:
                if target and "," in str(target):
                    parts = [int(p.strip()) for p in str(target).split(",")]
                    self.mouse.left_click(parts[0], parts[1])
                    return f"Clicked at ({parts[0]}, {parts[1]})"
                self.mouse.left_click()
                return "Clicked mouse"

            elif action in ["right_click", "context_menu"]:
                if target and "," in str(target):
                    parts = [int(p.strip()) for p in str(target).split(",")]
                    self.mouse.right_click(parts[0], parts[1])
                    return f"Right-clicked at ({parts[0]}, {parts[1]})"
                self.mouse.right_click()
                return "Right-clicked mouse"

            elif action == "double_click":
                if target and "," in str(target):
                    parts = [int(p.strip()) for p in str(target).split(",")]
                    self.mouse.double_click(parts[0], parts[1])
                    return f"Double-clicked at ({parts[0]}, {parts[1]})"
                self.mouse.double_click()
                return "Double-clicked mouse"

            elif action == "move_mouse":
                if "," in str(target):
                    parts = [int(p.strip()) for p in str(target).split(",")]
                    self.mouse.move_to(parts[0], parts[1], smooth=True)
                    return f"Moved cursor to ({parts[0]}, {parts[1]})"
                return "Invalid coordinates for mouse movement."

            elif action == "scroll":
                # target can be 'down', 'up', or 'down 5'
                parts = str(target).split()
                direction = parts[0] if parts else "down"
                amt = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 4
                self.mouse.scroll(direction, amt)
                return f"Scrolled {direction} by {amt}"

            elif action in ["scroll_down", "page_down"]:
                self.mouse.scroll("down", 5)
                return "Scrolled down"

            elif action in ["scroll_up", "page_up"]:
                self.mouse.scroll("up", 5)
                return "Scrolled up"

            elif action in ["drag", "drag_and_drop"]:
                cleaned = str(target).replace("->", ",").replace("to", ",")
                parts = [int(p.strip()) for p in cleaned.split(",") if p.strip().isdigit() or (p.strip().startswith('-') and p.strip()[1:].isdigit())]
                if len(parts) >= 4:
                    self.mouse.drag_and_drop(parts[0], parts[1], parts[2], parts[3])
                    return f"Dragged from ({parts[0]}, {parts[1]}) to ({parts[2]}, {parts[3]})"
                return "Invalid coordinates for drag and drop."

            # 2. Vision & Screen OCR Click
            elif action in ["click_text", "click_element", "click_button"]:
                coords = self.screen.find_text_coordinates(str(target))
                if coords:
                    cx, cy = coords
                    self.mouse.left_click(cx, cy)
                    return f"Located and clicked '{target}' at ({cx}, {cy})"
                return f"Could not find '{target}' on screen to click."

            elif action in ["read_screen", "screen_text", "ocr_screen"]:
                text = self.screen.read_screen_text()
                log.info(f"OSExecution: Read {len(text)} characters from screen.")
                return f"Visible on Screen:\n{text[:400]}..."

            elif action in ["read_active_window", "active_window_text"]:
                text = self.screen.read_active_window_text()
                log.info(f"OSExecution: Read {len(text)} characters from active window.")
                return f"Active Window Text:\n{text[:400]}..."

            # 3. Keyboard & Typing Operations
            elif action == "type_text":
                self.keyboard.type_text(str(target))
                return f"Typed: '{target}'"

            elif action in ["press_key", "tap_key"]:
                self.keyboard.tap_key(str(target))
                return f"Pressed key '{target}'"

            elif action in ["press_enter", "enter"]:
                self.keyboard.tap_key("enter")
                return "Pressed Enter"

            elif action in ["press_tab", "tab"]:
                self.keyboard.tap_key("tab")
                return "Pressed Tab"

            elif action in ["press_escape", "escape", "press_esc"]:
                self.keyboard.tap_key("escape")
                return "Pressed Escape"

            elif action in ["shortcut", "hotkey"]:
                # e.g. "ctrl+c" or "ctrl,shift,esc"
                delim = "+" if "+" in str(target) else ","
                keys = [k.strip() for k in str(target).split(delim)]
                self.keyboard.shortcut(*keys)
                return f"Executed shortcut: {' + '.join(keys)}"

            elif action == "copy_text":
                self.keyboard.copy()
                return "Copied to clipboard"

            elif action == "paste_text":
                self.keyboard.paste()
                return "Pasted from clipboard"

            elif action == "select_all":
                self.keyboard.select_all()
                return "Selected all content"

            elif action == "undo":
                self.keyboard.undo()
                return "Executed Undo"

            elif action == "save_file":
                self.keyboard.save()
                return "Executed Save"

            # 4. Application Lifecycle
            elif action == "open_app":
                return self.app_launcher.launch(str(target))

            elif action in ["close_app", "kill_app"]:
                clean_target = str(target).replace(".exe", "").strip()
                # Safe process termination without shell injection
                subprocess.run(
                    ["taskkill", "/F", "/IM", f"{clean_target}.exe"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                log.info(f"OSExecution: Terminated application '{clean_target}'")
                return f"Closed {clean_target}"

            # 5. Window Management
            elif action in ["manage_window", "snap_window"]:
                return self.manage_window(str(target))

            elif action in ["aero_shake", "minimize_others"]:
                from engine.window_manager import window_manager
                return window_manager.minimize_all_except_active()

            elif action == "switch_window":
                return self.switch_window(str(target))

            elif action == "show_desktop":
                self.keyboard.show_desktop()
                return "Showing desktop"

            # 6. File System Operations
            elif action == "create_folder":
                return self.file_ops.create_folder(str(target))

            elif action == "create_file":
                parts = str(target).split("::", 1)
                file_path = parts[0].strip()
                content = parts[1].strip() if len(parts) > 1 else ""
                return self.file_ops.create_file(file_path, content)

            elif action in ["open_path", "open_folder", "open_file"]:
                return self.file_ops.open_path(str(target))

            elif action in ["list_files", "list_directory"]:
                return self.file_ops.list_directory(str(target) if target else "desktop")

            elif action in ["preview_file", "view_file", "read_file"]:
                res = self.file_ops.preview_file(str(target))
                if res.get("error"):
                    return f"File preview failed: {res['error']}"
                if res.get("is_binary"):
                    return res["content"]
                return f"Preview of {res['name']} ({res.get('lines_shown', 0)}/{res.get('total_lines', 0)} lines):\n{res.get('content', '')}"

            elif action in ["directory_tree", "folder_tree", "show_tree"]:
                folder = str(target) if target else "desktop"
                return self.file_ops.get_directory_tree(folder)

            elif action == "delete_file":
                return self.file_ops.delete_file(str(target))

            # 7. Media & Volume Controls
            elif action == "media_control":
                return self.control_volume(str(target))

            # 8. Web Search & Intelligence
            elif action == "search_web":
                from utils.web_search import AIWebSearch
                return AIWebSearch.search_and_summarize(str(target))

            elif action == "open_url":
                url = str(target)
                if not url.startswith("http"):
                    url = "https://" + url
                webbrowser.open(url)
                return f"Opened website: {url}"

            # 9. Memory & Clipboard Intelligence
            elif action == "remember_fact":
                self.memory.remember(str(target))
                return f"Saved to memory: {target}"

            elif action == "analyze_clipboard":
                return self.analyze_clipboard(str(target))

            elif action in ["clipboard_history", "recent_clips"]:
                from utils.clipboard_monitor import clipboard_monitor
                clips = clipboard_monitor.get_recent(limit=3)
                if not clips:
                    return "Clipboard history is empty."
                formatted = [f"[{i+1}] {c['text'][:60]}..." if len(c['text']) > 60 else f"[{i+1}] {c['text']}" for i, c in enumerate(clips)]
                return "Recent Clipboard:\n" + "\n".join(formatted)

            elif action in ["search_clipboard", "find_clipboard"]:
                from utils.clipboard_monitor import clipboard_monitor
                matches = clipboard_monitor.search(str(target), limit=2)
                if not matches:
                    return f"No clipboard history found matching '{target}'."
                return f"Found matching clip: '{matches[0]['text'][:100]}'"

            elif action in ["clear_clipboard_history"]:
                from utils.clipboard_monitor import clipboard_monitor
                clipboard_monitor.clear()
                return "Clipboard history cleared."

            elif action in ["vault_store", "store_secret"]:
                from utils.vault import secure_vault
                parts = str(target).split("::", 1)
                if len(parts) == 2:
                    k, v = parts[0].strip(), parts[1].strip()
                    ok = secure_vault.set_secret(k, v)
                    return f"Stored secret '{k}' in encrypted vault." if ok else f"Failed to store '{k}'."
                return "Invalid format. Expected 'key::secret_value'."

            elif action in ["vault_get", "get_secret"]:
                from utils.vault import secure_vault
                val = secure_vault.get_secret(str(target))
                if val is not None:
                    return f"Secret '{target}': {val}"
                return f"Secret '{target}' not found in vault."

            elif action in ["vault_list", "list_secrets"]:
                from utils.vault import secure_vault
                keys = secure_vault.list_keys()
                return ("Vault keys: " + ", ".join(keys)) if keys else "Vault is currently empty."

            # 10. System Telemetry & Screen Capture
            elif action == "check_system":
                return self.check_system()

            elif action in ["check_battery", "battery_status", "power_status", "battery"]:
                from utils.power_manager import PowerManager
                status = PowerManager.get_battery_status()
                return status["summary"]

            elif action == "capture_screen":
                return self.capture_screen()

            elif action in ["list_apps", "running_apps", "open_windows"]:
                apps = self.list_running_apps()
                if apps:
                    return "Running Apps: " + ", ".join(apps[:6])
                return "No active visible applications found."

            elif action in ["app_resources", "process_usage"]:
                usage = self.get_app_resource_usage(str(target))
                return f"{target} ({usage['instances']} inst): {usage['memory_mb']} MB RAM, {usage['cpu_percent']}% CPU"

            elif action == "notify":
                from utils.notifications import Notifier
                Notifier.show_notification("MXB Executive Brain", str(target))
                return f"Notification: {target}"

            else:
                log.warning(f"OSExecution: Unsupported action '{action}'")
                return f"Action '{action}' is not supported yet."

        except Exception as e:
            traceback.print_exc()
            log.error(f"OSExecution Error on action '{action}': {e}")
            return f"Failed to execute {action}: {e}"

    def manage_window(self, command: str) -> str:
        try:
            active = gw.getActiveWindow()
            if not active:
                return "No active window found."

            cmd = command.lower().strip()
            if cmd in ["minimize", "min"]:
                active.minimize()
                return f"Minimized {active.title}"
            elif cmd in ["maximize", "max"]:
                active.maximize()
                return f"Maximized {active.title}"
            elif cmd in ["close", "exit"]:
                active.close()
                return f"Closed {active.title}"
            elif cmd in ["restore"]:
                active.restore()
                return f"Restored {active.title}"
            elif cmd == "left":
                self.keyboard.snap_window_left()
                return "Snapped window left"
            elif cmd == "right":
                self.keyboard.snap_window_right()
                return "Snapped window right"
            elif cmd in ["top_left", "top_right", "bottom_left", "bottom_right", "top", "bottom", "center", "middle"]:
                from engine.window_manager import window_manager
                return window_manager.snap_active_window(cmd)
            elif cmd in ["shake", "minimize_others", "isolate"]:
                from engine.window_manager import window_manager
                return window_manager.minimize_all_except_active()
            else:
                return f"Unknown window command: {command}"
        except Exception as e:
            return f"Window management failed: {e}"

    def switch_window(self, app_title: str) -> str:
        try:
            windows = gw.getAllWindows()
            app_title = app_title.lower().strip()
            for w in windows:
                if w.title and app_title in w.title.lower():
                    w.activate()
                    log.info(f"OSExecution: Switched window focus to '{w.title}'")
                    return f"Switched to {w.title}"
            # Fallback to Alt+Tab
            self.keyboard.task_switch()
            return "Switched active application"
        except Exception as e:
            return f"Failed to switch window: {e}"

    def check_system(self) -> str:
        try:
            cpu = psutil.cpu_percent(interval=0.3)
            ram = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            report = f"CPU Usage: {cpu}%. "
            report += f"RAM: {ram.percent}% used ({ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB). "
            report += f"Disk: {disk.percent}% full."

            battery = psutil.sensors_battery()
            if battery:
                report += f" Battery: {battery.percent}%, Plugged in: {battery.power_plugged}."

            return report
        except Exception as e:
            return f"Failed to check system status: {e}"

    def analyze_clipboard(self, instruction: str) -> str:
        log.info("OSExecution: Analyzing system clipboard...")
        try:
            clipboard_content = pyperclip.paste()
            if not clipboard_content or not clipboard_content.strip():
                return "Your clipboard is currently empty."

            # Use NVIDIA Cloud LLM if available, else Ollama
            from utils.credentials import CredentialsManager
            nv_key = CredentialsManager.get_nvidia_api_key()

            prompt = (
                f"You are MXB, acting as the user's Second Brain.\n\n"
                f"Here is the text currently copied to their system clipboard:\n"
                f"\"\"\"{clipboard_content[:3000]}\"\"\"\n\n"
                f"User Instruction: {instruction}\n"
                f"Provide your answer concisely in 1 or 2 spoken sentences without markdown formatting."
            )

            if nv_key:
                try:
                    url = "https://integrate.api.nvidia.com/v1/chat/completions"
                    headers = {"Authorization": f"Bearer {nv_key}", "Content-Type": "application/json"}
                    payload = {
                        "model": "meta/llama-3.1-8b-instruct",
                        "messages": [{"role": "user", "content": prompt}],
                        "temperature": 0.2,
                        "max_tokens": 150
                    }
                    r = requests.post(url, headers=headers, json=payload, timeout=8)
                    if r.status_code == 200:
                        return r.json()["choices"][0]["message"]["content"].strip()
                except Exception as nv_err:
                    log.warning(f"NVIDIA Clipboard analysis failed: {nv_err}")

            # Local Ollama fallback
            payload = {
                "model": "llama3.1",
                "prompt": prompt,
                "stream": False
            }
            resp = requests.post("http://localhost:11434/api/generate", json=payload, timeout=35)
            if resp.status_code == 200:
                return resp.json().get("response", "Clipboard processed.")
            return "Unable to analyze clipboard content."
        except Exception as e:
            return f"Failed to analyze clipboard: {e}"

    def control_volume(self, action: str) -> str:
        action = action.lower().strip()
        if action in ["volume_up", "up", "louder"]:
            for _ in range(3):
                self.keyboard.tap_key("f3")  # Or media volume up
            return "Volume increased"
        elif action in ["volume_down", "down", "quieter"]:
            for _ in range(3):
                self.keyboard.tap_key("f2")
            return "Volume decreased"
        elif action in ["mute", "unmute"]:
            self.keyboard.tap_key("f1")
            return "Audio mute toggled"
        elif action in ["play", "pause"]:
            self.keyboard.tap_key("space")
            return "Media playback toggled"
        return f"Unknown volume action: {action}"

    def capture_screen(self) -> str:
        try:
            self.keyboard.tap_key("f12")  # or printscreen
            from PySide6.QtGui import QGuiApplication
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance()
            if app:
                screen = QGuiApplication.primaryScreen()
                if screen:
                    desktop_dir = Path.home() / "Desktop"
                    save_path = desktop_dir / f"screenshot_{int(psutil.time.time())}.png"
                    pix = screen.grabWindow(0)
                    pix.save(str(save_path), "PNG")
                    return f"Saved screenshot to Desktop: {save_path.name}"
            return "Captured screenshot to clipboard."
        except Exception as e:
            return f"Screenshot error: {e}"

    def list_running_apps(self, limit: int = 10) -> list[str]:
        """Returns a list of currently open visible windows/applications."""
        try:
            titles = []
            for w in gw.getAllWindows():
                t = w.title.strip()
                if t and t not in titles and not any(ign in t.lower() for ign in ["program manager", "setup", "nvidia"]):
                    titles.append(t)
                if len(titles) >= limit:
                    break
            return titles
        except Exception as e:
            log.error(f"OSExecution: Failed listing apps: {e}")
            return []

    def get_app_resource_usage(self, app_name: str) -> dict:
        """Returns total memory (MB) and CPU% for processes matching app_name."""
        app_clean = app_name.lower().replace(".exe", "").strip()
        total_rss = 0
        total_cpu = 0.0
        match_count = 0
        for p in psutil.process_iter(['name', 'memory_info', 'cpu_percent']):
            try:
                pname = p.info['name'].lower()
                if app_clean in pname:
                    mem = p.info['memory_info']
                    if mem:
                        total_rss += mem.rss
                    total_cpu += p.info.get('cpu_percent', 0.0) or 0.0
                    match_count += 1
            except Exception:
                continue
        return {
            "app": app_name,
            "instances": match_count,
            "memory_mb": round(total_rss / (1024 * 1024), 1),
            "cpu_percent": round(total_cpu, 1)
        }
