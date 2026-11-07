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
    ActionSpec("wait", "seconds e.g. '1.5'", "Pause between steps (e.g. while an app opens)", "control"),
    ActionSpec("conversation", '"none"', "Just answer in the reply field, no OS action", "control"),
)

_BY_NAME = {spec.name: spec for spec in CATALOG}


def get_spec(action: str) -> ActionSpec | None:
    return _BY_NAME.get((action or "").lower().strip())


def action_names() -> list[str]:
    return [spec.name for spec in CATALOG]


def risk_of(action: str) -> str:
    spec = get_spec(action)
    return spec.risk if spec else "safe"


def uses_input(action: str) -> bool:
    spec = get_spec(action)
    return bool(spec and spec.uses_input)


def prompt_tool_list(exclude: tuple[str, ...] = ()) -> str:
    """Renders the catalog as a compact tool list for LLM system prompts."""
    lines = []
    current = None
    for spec in CATALOG:
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
- Keep "reply" to one or two short spoken sentences without markdown."""


def planner_system_prompt(assistant_name: str = "MXB") -> str:
    return (
        f"You are {assistant_name}, an AI desktop companion with full control of the user's Windows PC "
        "(mouse, keyboard, apps, windows, files, Bluetooth, Wi-Fi, volume, brightness).\n\n"
        f"{PLANNER_RULES}\n\nAvailable actions:\n{prompt_tool_list()}"
    )
