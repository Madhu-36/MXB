# MXB Action Reference Guide

MXB v2.1 supports 30+ atomic and compound desktop automation actions executable either via Tier 1 deterministic fast-path or Tier 2 LLM multi-step planner.

---

## 1. Mouse Operations

| Action | Target Format | Description | Example Spoken Voice Command |
| :--- | :--- | :--- | :--- |
| `left_click` / `click` | `""` or `"x,y"` | Clicks at current or specified cursor position | *"Click"*, *"Click at 500, 300"* |
| `right_click` | `""` or `"x,y"` | Context menu right click | *"Right click"* |
| `double_click` | `""` or `"x,y"` | Double left click | *"Double click"* |
| `move_mouse` | `"x,y"` | Smoothly moves cursor to absolute coordinates | *"Move mouse to 800, 400"* |
| `scroll` | `"down"`, `"up"`, or `"down 5"` | Scrolls the mouse wheel by notch count | *"Scroll down 5 notches"* |
| `drag_and_drop` | `"x1, y1 -> x2, y2"` | Drags from start to end coordinates | *"Drag 200, 300 to 600, 300"* |

---

## 2. Screen Vision & OCR

| Action | Target Format | Description | Example Spoken Voice Command |
| :--- | :--- | :--- | :--- |
| `click_text` | `"Button / Label"` | Locates text on screen with Native OCR and clicks it | *"Click on Submit"*, *"Click Settings"* |
| `read_screen` | `""` | Runs OCR on full screen and reads text aloud | *"What is on my screen?"*, *"Read screen"* |
| `capture_screen`| `""` | Takes a full-resolution desktop screenshot | *"Take a screenshot"* |

---

## 3. Keyboard Automation & Shortcuts

| Action | Target Format | Description | Example Spoken Voice Command |
| :--- | :--- | :--- | :--- |
| `type_text` | `"text to type"` | Dictates text directly or via fast clipboard paste | *"Type hello world"* |
| `press_key` | `"enter"`, `"esc"`, `"tab"` | Taps a specific keyboard key | *"Press enter"*, *"Hit escape"* |
| `shortcut` | `"ctrl+c"`, `"alt+tab"` | Executes virtual-key combination in sequence | *"Shortcut alt plus tab"* |
| `show_desktop` | `""` | Minimizes all windows (Win+D) | *"Show desktop"*, *"Minimize all"* |
| `copy_text` | `""` | Copies selected text (Ctrl+C) | *"Copy selection"* |
| `paste_text` | `""` | Pastes clipboard content (Ctrl+V) | *"Paste text"* |
| `select_all` | `""` | Selects all contents (Ctrl+A) | *"Select everything"* |
| `save_file` | `""` | Saves active document (Ctrl+S) | *"Save document"* |

---

## 4. Window & Application Management

| Action | Target Format | Description | Example Spoken Voice Command |
| :--- | :--- | :--- | :--- |
| `open_app` | `"App Name"` | Smart app launcher resolving paths and Start Menu | *"Open Notepad"*, *"Launch Chrome"* |
| `close_app` | `"Process Name"` | Safely terminates an application process | *"Close Chrome"*, *"Quit Spotify"* |
| `manage_window`| `"minimize"`, `"maximize"`, `"left"`, `"right"` | Snaps or resizes current window | *"Maximize window"*, *"Snap window left"* |
| `list_apps` | `""` | Lists visible running windows | *"What apps are open?"* |
| `app_resources`| `"App Name"` | Reports CPU% and RAM usage in MB | *"Check Chrome resources"* |

---

## 5. File System Operations

| Action | Target Format | Description | Example Spoken Voice Command |
| :--- | :--- | :--- | :--- |
| `create_folder`| `"Folder Name"` | Creates directory in Desktop or target path | *"Create folder Projects"* |
| `create_file` | `"name.txt :: content"`| Creates file with initial content | *"Create file notes.txt with hello"* |
| `list_files` | `"desktop"` / `"downloads"`| Lists items in standard user directories | *"List files on desktop"* |
| `delete_file` | `"path or name"` | Safely removes target file | *"Delete file temp.txt"* |

---

## 6. Emergency Voice Interruption

Saying any of the following immediate trigger words halts active multi-step plans in under 50 ms:
- `"stop"`, `"cancel"`, `"halt"`, `"pause"`, `"abort"`, `"freeze"`, `"shut up"`
