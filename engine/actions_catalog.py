"""
MXB Action Catalog — the single source of truth for every action MXB can perform.

Used by:
- The LLM planner (system prompt is generated from this list, so NVIDIA and Ollama
  always see the same tools).
- The safety policy (each action carries a risk level).
- The test-suite (every catalog action must be handled by the executor).

Risk levels:
- "safe":    runs immediately.
- "confirm": MXB asks the user (voice "yes"/"no", chat buttons, or typed answer) first.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ActionSpec:
    name: str
    target: str
    description: str
    category: str
    risk: str = "safe"
    uses_input: bool = False  # True when the action drives mouse/keyboard/focus


CATALOG: tuple[ActionSpec, ...] = (
    # ---------------- Mouse ----------------
    ActionSpec("left_click", '"x,y" or "" for current position', "Left click", "mouse", uses_input=True),
    ActionSpec("right_click", '"x,y" or ""', "Right click / context menu", "mouse", uses_input=True),
    ActionSpec("double_click", '"x,y" or ""', "Double click", "mouse", uses_input=True),
    ActionSpec("move_mouse", '"x,y"', "Move the cursor", "mouse", uses_input=True),
    ActionSpec("drag_and_drop", '"x1,y1 -> x2,y2"', "Drag from one point to another", "mouse", uses_input=True),
    ActionSpec("scroll", '"down", "up", "left", "right" optionally with amount e.g. "down 5"', "Scroll the mouse wheel", "mouse", uses_input=True),

    # ---------------- Screen understanding & UI control ----------------
    ActionSpec("focus_search_box", 'optional hint e.g. "youtube" or ""', "Find and click the search box/bar on screen", "screen", uses_input=True),
    ActionSpec("search_on_screen", '"text" or "hint :: text"', "Focus the on-screen search box, type text and press Enter", "screen", uses_input=True),
    ActionSpec("type_into", '"field name :: text" (field e.g. "username", "search", "message")', "Click a named text field and type into it", "screen", uses_input=True),
    ActionSpec("click_element", "visible name of a button/link/tab/menu item", "Click a UI element by its name (accessibility tree, OCR fallback)", "screen", uses_input=True),
    ActionSpec("click_text", "visible text on screen", "Click on visible text (OCR)", "screen", uses_input=True),
    ActionSpec("read_screen", '""', "Read all visible text on screen", "screen"),
    ActionSpec("read_active_window", '""', "Read text inside the focused window", "screen"),
    ActionSpec("list_ui_elements", '""', "List clickable elements and fields in the focused window", "screen"),
    ActionSpec("capture_screen", '""', "Save a screenshot to Pictures/MXB Screenshots", "screen"),
    ActionSpec("pick_color", '"x,y" or ""', "Color of the pixel at the cursor", "screen"),

    # ---------------- Keyboard ----------------
    ActionSpec("type_text", "exact text to type", "Type text at the current cursor position", "keyboard", uses_input=True),
    ActionSpec("press_key", "enter, esc, tab, backspace, space, up, down, f5, ...", "Press one key", "keyboard", uses_input=True),
    ActionSpec("shortcut", "ctrl+c, ctrl+t, ctrl+l, alt+tab, win+d, ...", "Press a key combination", "keyboard", uses_input=True),
    ActionSpec("copy_text", '""', "Copy selection (Ctrl+C)", "keyboard", uses_input=True),
    ActionSpec("paste_text", '""', "Paste (Ctrl+V)", "keyboard", uses_input=True),
    ActionSpec("select_all", '""', "Select all (Ctrl+A)", "keyboard", uses_input=True),
    ActionSpec("undo", '""', "Undo (Ctrl+Z)", "keyboard", uses_input=True),
    ActionSpec("save_file", '""', "Save (Ctrl+S)", "keyboard", uses_input=True),

    # ---------------- Apps & windows ----------------
    ActionSpec("open_app", "app name", "Launch an application", "apps", uses_input=True),
    ActionSpec("close_app", "app name", "Close an application gracefully (it may ask to save)", "apps", uses_input=True),
    ActionSpec("force_close_app", "app name", "Force-kill an application (unsaved work is lost)", "apps", risk="confirm"),
    ActionSpec("switch_window", "part of a window title", "Bring a window to the front", "apps", uses_input=True),
    ActionSpec("manage_window", "minimize, maximize, close, restore, left, right, top_left, center, shake", "Control the active window", "apps", uses_input=True),
    ActionSpec("show_desktop", '""', "Minimize everything", "apps", uses_input=True),
    ActionSpec("list_apps", '""', "List open windows", "apps"),
    ActionSpec("open_url", "website url", "Open a website in the default browser", "apps", uses_input=True),
    ActionSpec("open_terminal", '""', "Open Windows Terminal / PowerShell", "apps", uses_input=True),
    ActionSpec("open_task_manager", '""', "Open Task Manager", "apps", uses_input=True),

    # ---------------- Files ----------------
    ActionSpec("list_files", "folder name or path (desktop, downloads, D:\\\\work, ...)", "List a folder", "files"),
    ActionSpec("directory_tree", "folder", "Show a folder tree", "files"),
    ActionSpec("find_files", '"name or pattern" or "name :: folder"', "Search for files by name across allowed folders", "files"),
    ActionSpec("read_file", "file path or name", "Read a text/PDF/DOCX file's contents", "files"),
    ActionSpec("open_path", "file or folder path or name", "Open a file or folder with its default app", "files", uses_input=True),
    ActionSpec("create_folder", "folder path", "Create a folder", "files"),
    ActionSpec("create_file", '"path :: contents"', "Create a text file (asks before overwriting)", "files"),
    ActionSpec("copy_file", '"source :: destination"', "Copy a file or folder", "files"),
    ActionSpec("move_file", '"source :: destination"', "Move a file or folder", "files"),
    ActionSpec("rename_file", '"path :: new name"', "Rename a file or folder", "files"),
    ActionSpec("delete_file", '"path" (to Recycle Bin) or "path :: permanent"', "Delete a file or folder", "files", risk="confirm"),
    ActionSpec("grant_file_access", 'folder path, drive letter like "D", or "all"', "Allow MXB to access more of the file system", "files", risk="confirm"),
    ActionSpec("revoke_file_access", 'folder path, drive letter, or "all"', "Remove MXB's access to a location", "files"),
    ActionSpec("list_file_access", '""', "Show which folders MXB may access", "files"),

    # ---------------- Hardware ----------------
    ActionSpec("bluetooth_power", '"on", "off" or "status"', "Turn the Bluetooth radio on/off", "hardware"),
    ActionSpec("bluetooth_devices", '""', "List paired Bluetooth devices and whether they are connected", "hardware"),
    ActionSpec("bluetooth_connect", "device name (e.g. 'boAt Airdopes')", "Connect a paired Bluetooth audio device", "hardware"),
    ActionSpec("bluetooth_disconnect", "device name", "Disconnect a Bluetooth audio device", "hardware"),
    ActionSpec("wifi_power", '"on", "off" or "status"', "Turn the Wi-Fi radio on/off or report the connection", "hardware"),
    ActionSpec("wifi_networks", '""', "List nearby Wi-Fi networks", "hardware"),
    ActionSpec("wifi_connect", "network name (SSID)", "Connect to a saved Wi-Fi network", "hardware"),
    ActionSpec("wifi_disconnect", '""', "Disconnect from Wi-Fi", "hardware"),
    ActionSpec("set_volume", '0-100, "up", "down" or "status"', "Set speaker volume", "hardware"),
    ActionSpec("mic_mute", '"on" (mute), "off" (unmute), "toggle" or "status"', "Mute or unmute the microphone", "hardware"),
    ActionSpec("set_brightness", '0-100, "up", "down" or "status"', "Set screen brightness", "hardware"),
    ActionSpec("list_devices", 'optional category: keyboard, mouse, camera, audio, bluetooth, usb, monitor', "List connected hardware", "hardware"),
    ActionSpec("audio_devices", '""', "List speakers and microphones", "hardware"),
    ActionSpec("open_settings", "bluetooth, wifi, sound, display, battery, privacy, update, apps, mouse, keyboard", "Open a Windows Settings page", "hardware", uses_input=True),
    ActionSpec("media_control", "volume_up, volume_down, mute, play, pause, next, prev", "Media keys", "hardware"),

    # ---------------- System ----------------
    ActionSpec("check_system", '""', "CPU, RAM, disk and battery status", "system"),
    ActionSpec("check_battery", '""', "Battery status", "system"),
    ActionSpec("top_processes", '""', "Heaviest processes by RAM", "system"),
    ActionSpec("find_port", "port number", "Which process uses a port", "system"),
    ActionSpec("kill_process", "process name or PID", "Terminate a process", "system", risk="confirm"),
    ActionSpec("lock_pc", '""', "Lock the workstation", "system"),
    ActionSpec("empty_recycle_bin", '""', "Empty the Recycle Bin (permanent)", "system", risk="confirm"),
    ActionSpec("power_action", '"shutdown", "restart", "sleep" or "sign_out"', "Shut down, restart, sleep or sign out", "system", risk="confirm"),
    ActionSpec("notify", "message", "Show a Windows notification", "system"),

    # ---------------- Intelligence ----------------
    ActionSpec("search_web", "search query", "Search the internet and summarize (only when asked to search online)", "intelligence"),
    ActionSpec("analyze_clipboard", "instruction e.g. 'summarize'", "Analyze the clipboard text", "intelligence"),
    ActionSpec("remember_fact", "fact to store", "Save a fact to long-term memory", "intelligence"),
    ActionSpec("weather", "city or ''", "Current weather", "intelligence"),
    ActionSpec("timer_start", 'duration like "5 minutes"', "Start a countdown timer", "intelligence"),
    ActionSpec("agent_task", "the full goal in plain words", "Multi-step task that needs looking at the screen between steps", "intelligence", uses_input=True),
    ActionSpec("vault_get", "secret key name", "Read a secret from the encrypted vault", "intelligence", risk="confirm"),

    # ---------------- v4: agent precision & undo ----------------
    ActionSpec("show_marks", '""', "Number every clickable element on screen so the user can say 'click 12'", "screen"),
    ActionSpec("hide_marks", '""', "Hide the on-screen numbers", "screen"),
    ActionSpec("click_mark", "mark number from the element list, e.g. '12'", "Click the element with that mark number", "screen", uses_input=True),
    ActionSpec("type_mark", '"mark number :: text"', "Click the field with that mark number and type", "screen", uses_input=True),
    ActionSpec("undo_last", '""', "Undo MXB's last file action (move, rename, copy, create, delete-to-bin, overwrite)", "files"),

    # ---------------- v4: memory & documents ----------------
    ActionSpec("remember_preference", "preference in the user's words", "Store a lasting user preference", "memory"),
    ActionSpec("recall_memories", 'topic or ""', "List what MXB remembers (about a topic)", "memory"),
    ActionSpec("forget_memory", "what to forget", "Delete matching memories", "memory"),
    ActionSpec("index_folder", "folder path or name", "Read and index a folder's documents for question answering", "memory"),
    ActionSpec("ask_documents", "question", "Answer a question from the user's indexed documents, with sources", "memory"),
    ActionSpec("knowledge_status", '""', "Which folders are indexed and how many documents", "memory"),

    # ---------------- v4: automation ----------------
    ActionSpec("set_reminder", '"when :: what" e.g. "in 20 minutes :: stretch" or "at 5 pm :: call mom"', "Set a reminder", "automation"),
    ActionSpec("schedule_command", '"when :: command" e.g. "every day at 9 am :: open outlook"', "Run a command later or on a schedule", "automation"),
    ActionSpec("list_schedules", '""', "List reminders and scheduled commands", "automation"),
    ActionSpec("cancel_schedule", 'number, text, or "all"', "Cancel reminders / scheduled commands", "automation"),
    ActionSpec("create_routine", '"name :: command 1 ; command 2 ; ..."', "Save a named routine of commands", "automation"),
    ActionSpec("run_routine", "routine or recorded workflow name", "Run a saved routine or recorded workflow", "automation", uses_input=True),
    ActionSpec("list_routines", '""', "List routines and recorded workflows", "automation"),
    ActionSpec("delete_routine", "name", "Delete a routine or workflow", "automation"),
    ActionSpec("start_recording", "workflow name", "Record the user's clicks and typing as a replayable workflow", "automation"),
    ActionSpec("stop_recording", '""', "Stop and save the recording", "automation"),
    ActionSpec("phone_remote", '"on", "off" or "status"', "Turn the phone remote-control web app on/off", "automation", risk="confirm"),

    # ---------------- v4.1: trust, install & updates ----------------
    ActionSpec("audit_log", '"today", "last 2 hours" or ""', "Summarize what MXB did, blocked or was refused", "system"),
    ActionSpec("check_updates", '""', "Check GitHub for a newer MXB release", "system"),
    ActionSpec("install_update", '""', "Download (SHA-256 verified) and install the newest MXB release", "system", risk="confirm"),
    ActionSpec("autostart", '"on", "off" or "status"', "Start MXB when Windows starts", "system"),
    # ---------------- v4.2: MXB browser (Playwright: DOM-level, doesn't take over your mouse) ----------------
    ActionSpec("web_open", "url or site, e.g. 'github.com'", "Open a page in MXB's browser (reliable web clicking and typing)", "web"),
    ActionSpec("web_search", "search words", "Search the web in MXB's browser", "web"),
    ActionSpec("web_elements", '""', "List the numbered buttons, links and fields on the current page", "web"),
    ActionSpec("web_click", "element number from web_elements, or its visible text", "Click a link/button/tab on the page", "web"),
    ActionSpec("web_fill", '"element number or field name :: text"', "Type into a page field (never passwords)", "web"),
    ActionSpec("web_press", "enter, tab, escape, ctrl+a, ...", "Press a key on the page", "web"),
    ActionSpec("web_select", '"dropdown number or name :: option"', "Choose an option in a dropdown", "web"),
    ActionSpec("web_scroll", '"down", "up", "down 3", "top", "bottom"', "Scroll the page", "web"),
    ActionSpec("web_read", '""', "Read the page's main text", "web"),
    ActionSpec("web_summarize", 'question about the page, or ""', "Summarize the page or answer a question about it", "web"),
    ActionSpec("web_back", '""', "Go back to the previous page", "web"),
    ActionSpec("web_tabs", '""', "List the browser tabs", "web"),
    ActionSpec("web_switch_tab", "tab number", "Switch to a browser tab", "web"),
    ActionSpec("web_new_tab", 'url or ""', "Open a new tab", "web"),
    ActionSpec("web_close_tab", 'tab number or ""', "Close a tab (the current one by default)", "web"),
    ActionSpec("web_wait", 'text to wait for, or ""', "Wait until text appears on the page", "web"),
    ActionSpec("web_screenshot", '""', "Save a screenshot of the page", "web"),
    ActionSpec("web_close", '""', "Close MXB's browser", "web"),

    # ---------------- v4.2: pixel grounding (vision model finds things by looking) ----------------
    ActionSpec("click_visual", "what to click, e.g. 'the gear icon' or 'the blue Submit button'", "Find something on screen by looking and click it (icons, games, apps without accessibility info)", "screen", uses_input=True),
    ActionSpec("double_click_visual", "what to double-click", "Find something on screen by looking and double-click it", "screen", uses_input=True),
    ActionSpec("type_visual", '"description of the field :: text"', "Find a field by looking, click it and type", "screen", uses_input=True),
    ActionSpec("locate_visual", "what to find", "Say where something is on screen without clicking it", "screen"),

    # ---------------- v4.2: MCP tools & language ----------------
    ActionSpec("mcp_tools", '""', "List connected MCP servers and their tools", "mcp"),
    ActionSpec("mcp_reload", '""', "Reconnect to the MCP servers in config", "mcp"),
    ActionSpec("set_language", '"kannada", "hindi", "telugu", "tamil", "malayalam", "marathi", "bengali", "gujarati", "english" or "auto"', "Choose the language MXB listens and replies in", "voice"),

    ActionSpec("wait", "seconds e.g. '1.5'", "Pause between steps (e.g. while an app opens)", "control"),
    ActionSpec("conversation", '"none"', "Just answer in the reply field, no OS action", "control"),
)

_BY_NAME = {spec.name: spec for spec in CATALOG}
_DYNAMIC: dict[str, ActionSpec] = {}   # plugin skills register here at runtime

ALIASES = {
    "click": "left_click", "type": "type_text", "press": "press_key", "hotkey": "shortcut", "key": "press_key",
    "launch_app": "open_app", "start_app": "open_app", "open_application": "open_app", "open": "open_app",
    "close": "close_app", "browse": "open_url", "go_to_url": "open_url", "open_website": "open_url",
    "search_box": "search_on_screen", "find_file": "find_files", "search_files": "find_files",
    "remind": "set_reminder", "reminder": "set_reminder", "sleep": "wait", "pause": "wait", "answer": "conversation",
}


def register_dynamic(spec: ActionSpec):
    _DYNAMIC[spec.name] = spec


def unregister_dynamic(name: str):
    _DYNAMIC.pop(name, None)


def get_spec(action: str) -> ActionSpec | None:
    key = (action or "").lower().strip()
    return _BY_NAME.get(key) or _DYNAMIC.get(key)


def action_names(include_dynamic: bool = True) -> list[str]:
    names = [spec.name for spec in CATALOG]
    if include_dynamic:
        names += [n for n in _DYNAMIC if n not in _BY_NAME]
    return names


def all_specs() -> list[ActionSpec]:
    return list(CATALOG) + [s for n, s in _DYNAMIC.items() if n not in _BY_NAME]


def normalize_action(action: str) -> str:
    a = str(action or "").lower().strip().replace(" ", "_").replace("-", "_")
    return ALIASES.get(a, a)


def validate_plan(steps, max_steps: int = 12) -> tuple[list[dict], list[str]]:
    """
    Cleans an LLM plan: normalizes/aliases action names, drops unknown actions and
    no-op 'conversation' steps, stringifies targets, keeps 'expect', caps length.
    Returns (valid_steps, dropped_action_names).
    """
    valid, dropped = [], []
    known = set(action_names())
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        action = normalize_action(step.get("action", ""))
        if not action or action in ("conversation", "none"):
            continue
        if action not in known:
            dropped.append(action)
            continue
        clean = {"action": action, "target": "" if step.get("target") is None else str(step.get("target"))}
        if step.get("expect"):
            clean["expect"] = str(step["expect"])
        valid.append(clean)
        if len(valid) >= max_steps:
            break
    return valid, dropped


def risk_of(action: str) -> str:
    spec = get_spec(action)
    return spec.risk if spec else "safe"


def uses_input(action: str) -> bool:
    spec = get_spec(action)
    return bool(spec and spec.uses_input)


def prompt_tool_list(exclude: tuple[str, ...] = ()) -> str:
    """Renders the catalog (plus plugin skills) as a compact tool list for LLM system prompts."""
    lines = []
    current = None
    for spec in all_specs():
        if spec.name in exclude:
            continue
        if spec.category != current:
            current = spec.category
            lines.append(f"[{current}]")
        lines.append(f'- "{spec.name}": {spec.description} (target: {spec.target})')
    return "\n".join(lines)


PLANNER_RULES = """Rules:
- Respond ONLY with JSON: {"reply": "<short spoken answer>", "plan": [{"action": "<name>", "target": "<value>"}]}
- For questions or chat, answer in "reply" and use an empty plan.
- Break compound requests into ordered steps. Add {"action": "wait", "target": "1.5"} after opening apps or websites.
- "go to the search box and type X (and press enter)" -> use search_on_screen with target "X" (or "hint :: X" if a site/app is named).
- To fill a named field use type_into with "field :: text". Use click_element for buttons, links, tabs and menus by name.
- If the task needs looking at the screen to decide later steps, use one agent_task step with the whole goal.
- Never invent file paths. Use find_files first when the user names a file without a location.
- Dangerous actions (delete, kill, shutdown, overwrite) are confirmed by the system; do not ask for confirmation yourself.
- Put "reply" FIRST in the JSON. Keep it to one or two short spoken sentences without markdown.
- Questions about the user's own documents/notes -> ask_documents. Things the user says about themselves -> remember_preference.
- Websites: prefer the web_* actions (MXB's browser): web_open, then web_elements to get numbers, then web_click / web_fill by number."""


def plan_tool_schema(agent: bool = False) -> dict:
    """OpenAI-style function schema used for native tool calling (NVIDIA NIM / Ollama)."""
    props = {
        "reply": {"type": "string", "description": "One or two short spoken sentences for the user."},
        "plan": {
            "type": "array",
            "description": "Ordered desktop actions to run. Empty for plain answers.",
            "items": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": action_names()},
                    "target": {"type": "string"},
                    "expect": {"type": "string", "description": "Optional text that should be visible after this step."},
                },
                "required": ["action", "target"],
            },
        },
    }
    required = ["reply", "plan"]
    if agent:
        props["thought"] = {"type": "string", "description": "One short sentence of reasoning."}
        props["done"] = {"type": "boolean", "description": "True when the goal is achieved or impossible."}
        required.append("done")
    return {
        "type": "function",
        "function": {
            "name": "execute_plan",
            "description": "Reply to the user and run desktop actions on their Windows PC in order.",
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


def planner_system_prompt(assistant_name: str = "MXB") -> str:
    from safety.injection import UNTRUSTED_RULES
    from engine.indic import language_instruction
    return (
        f"You are {assistant_name}, an AI desktop companion with full control of the user's Windows PC "
        "(mouse, keyboard, apps, windows, files, Bluetooth, Wi-Fi, volume, brightness).\n\n"
        f"{PLANNER_RULES}\n{UNTRUSTED_RULES}{language_instruction()}\n\nAvailable actions:\n{prompt_tool_list()}"
    )
