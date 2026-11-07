# MXB v3.0 Companion Guide

MXB is a Windows desktop companion you can **talk to or type to**. It keeps listening while it works, can operate any app through the mouse, keyboard and accessibility tree, controls your hardware, and works with your files. Anything destructive needs your "yes" first.

---

## 1. Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# LLM brain (pick one or both)
setx NVIDIA_API_KEY "nvapi-..."      # cloud: fast, best planning quality
ollama pull llama3.1:8b               # local: private; set llm.local_model to it
python -u main.py
```

`llama3.2:1b` (the old default) handles simple commands, but it is too small for reliable multi-step plans or agent mode. Use the NVIDIA model or a local 8B model for those.

---

## 2. Talking and typing

| Channel | How |
| :--- | :--- |
| Voice | Start with the wake word: **"MXB, open Chrome."** After MXB replies, you have 15 s for follow-ups without the wake word. |
| Chat | `Ctrl+Alt+Space`, tray icon → *Open Chat*, or say *"MXB, open chat"*. Press Enter to send; ↑/↓ recall history. |
| Replies | Voice commands get spoken + written replies. Typed commands get written replies only (`voice.speak_text_replies: true` to hear them too). |
| Parallel | While a task runs, you can still ask questions (*"what's the time?"*, *"what is a transformer?"*); MXB answers on a second lane. New *actions* are queued in order. |
| Status | *"What are you doing?"* tells you the current step and how many commands are queued. |
| Stop | **"stop"**, "cancel", "shut up": no wake word needed. Also the chat Stop button and `Ctrl+Alt+K`. This aborts the plan, clears the queue, cancels pending questions and cuts speech. |

While MXB is *speaking*, the microphone ignores input so it doesn't hear itself. Use the Stop button or hotkey to interrupt a long answer.

---

## 3. Command reference

### Screen, search boxes and fields
| Say / type | Action |
| :--- | :--- |
| go to the search box and enter **cute cats** and press enter | `search_on_screen` |
| go to the youtube search bar and type **lofi** and hit enter | `search_on_screen` with hint "youtube" |
| go to the search box and type **hello** | `type_into` (no Enter) |
| type **me@x.com** in the email field | `type_into "email :: me@x.com"` |
| click the **Sign in** button / link / tab / menu | `click_element` |
| click **Settings** | `click_text` (OCR, then accessibility tree) |
| what can I click | `list_ui_elements` |
| read my screen / take a screenshot | `read_screen` / `capture_screen` (→ Pictures/MXB Screenshots) |

How the search box is found: (1) the Windows UI Automation tree, i.e. a real Edit/ComboBox named "Search…", "Search YouTube", "Address and search bar", etc.; (2) OCR for a visible "Search" placeholder; (3) a shortcut for the active app: browser → `Ctrl+L`, File Explorer → `Ctrl+E`, desktop → `Win+S`, others → `Ctrl+F`. MXB tells you which method it used.

### Hardware
| Say / type | Action |
| :--- | :--- |
| turn on / turn off bluetooth · is bluetooth on | `bluetooth_power` |
| list my bluetooth devices | `bluetooth_devices` (shows connected / not connected) |
| connect my **airdopes** · disconnect my headphones | `bluetooth_connect` / `bluetooth_disconnect` |
| turn off wifi · wifi status · show wifi networks | `wifi_power` / `wifi_networks` |
| connect to **Home_5G** wifi · disconnect from wifi | `wifi_connect` (saved networks) / `wifi_disconnect` |
| set volume to 40 · what's the volume · volume up | `set_volume` / `media_control` |
| mute the mic · unmute the microphone | `mic_mute` |
| set brightness to 70 · brightness up · dimmer | `set_brightness` |
| list connected devices · list usb devices · show keyboards | `list_devices` |
| list audio devices | `audio_devices` |
| open bluetooth / sound / display / wifi settings | `open_settings` |
| shut down / restart / sleep / sign out the pc · cancel shutdown | `power_action` (confirmed; 5 s delay to cancel) |

### Files
| Say / type | Action |
| :--- | :--- |
| find the file named **resume** · find file budget in D drive | `find_files` |
| read file notes.txt · what's in plan.md | `read_file` (text, code, PDF, DOCX) |
| summarize the file report.pdf | `read_file` + LLM summary |
| open the file resume.pdf | `open_path` (searches by name if needed) |
| move report.pdf to documents · copy notes.docx to D drive | `move_file` / `copy_file` |
| rename file draft.docx to final | `rename_file` (keeps the extension) |
| delete the file old.txt | Recycle Bin (asks first) |
| permanently delete the file junk.txt | Permanent delete (asks first) |
| give access to D drive · give access to C:\Projects | `grant_file_access` (asks first) |
| give full file access | Everything except OS folders (asks first) |
| revoke access to D drive · what folders can you access | `revoke_file_access` / `list_file_access` |

### Apps, windows, keyboard, mouse (existing)
open / close / force close *app* · switch to *window* · minimize / maximize / snap left / top left · show desktop · type *text* · press enter · copy / paste / undo / save · scroll down · click / right click / double click · open terminal / task manager.

### Intelligence
Questions and chat · *"search the web for…"* · *"summarize clipboard"* · *"remember that…"* · weather · timers · *"what time is it"* (answered locally, never guessed by the LLM).

### Agent mode
`agent: <goal>` (or "autopilot: …"). MXB looks at the active window (title, clickable elements with coordinates, OCR text, optional screenshot), plans 1–3 steps, acts, and repeats up to `agent.max_steps`. Say "stop" at any time. Set `agent.use_vision: true` to also send a screenshot to the vision model.

---

## 4. Safety model

1. **Confirmation before damage.** These actions always ask *"…? Say yes or no."* (voice, typed yes/no, or the chat buttons): delete, empty Recycle Bin, kill process, force-close an app, shutdown/restart/sleep/sign-out, overwriting an existing file, broad file-access grants, and reading vault secrets aloud. No answer within 30 s counts as **no**. "stop" counts as **no** and halts everything.
2. **No confirmation channel → no action.** If the executor is used without the bus (scripts, tests), risky actions are refused rather than run silently.
3. **File scope.** By default MXB uses only your personal folders (Desktop, Documents, Downloads, Pictures, Music, Videos, OneDrive). Other locations need a grant, which is saved in `permissions.json` and can be revoked by voice.
4. **OS folders are always read-only.** Even with full access, MXB never writes to Windows, Program Files or ProgramData. A misheard command must not be able to break the OS.
5. **Deletes are recoverable by default.** Normal deletes go to the Recycle Bin. Permanent deletion must be asked for explicitly.
6. **Wake word by default.** With `listening.mode: "always"` MXB acts on everything it hears, including a TV or other people in the room. Only switch it on in a quiet room.

To turn confirmations off entirely (not recommended), set `safety.confirm_destructive: false`.

---

## 5. Configuration (`config.json`)

| Key | Default | Meaning |
| :--- | :--- | :--- |
| `listening.mode` | `"wake_word"` | `"always"` = no wake word |
| `listening.wake_words` | `["mxb", …]` | Any names, e.g. `["jarvis"]` |
| `listening.follow_up_seconds` | `15` | Follow-up window after a reply |
| `voice.speak_text_replies` | `false` | Also speak replies to typed commands |
| `safety.confirm_destructive` | `true` | Ask before destructive actions |
| `safety.confirmation_timeout_sec` | `30` | Silence = no |
| `files.extra_allowed_folders` | `[]` | Extra folders allowed without a voice grant |
| `agent.max_steps` / `agent.use_vision` | `8` / `false` | Agent loop limits |
| `llm.vision_model` / `llm.local_vision_model` | NVIDIA Llama 3.2 Vision / `llama3.2-vision` | Used by agent mode when vision is on |
| `hotkeys.open_chat` | `ctrl+alt+space` | Toggle chat window |
| `ui.open_chat_on_start` | `true` | Show chat on launch |

---

## 6. Known limits

- **Bluetooth connect/disconnect** works for classic audio devices (earbuds, headphones, speakers) by toggling their audio profiles through the Win32 Bluetooth API. Some drivers require admin rights. BLE mice and keyboards can't be connected programmatically; MXB opens Bluetooth settings instead and says so.
- **Wi-Fi connect** works for networks Windows has already saved. For new networks MXB opens Wi-Fi settings so you can type the password yourself.
- **Brightness** works on laptop panels (WMI) and monitors with DDC/CI enabled.
- **Accessibility tree:** most Windows apps, Chrome, Edge and Firefox expose their controls. Games and custom-drawn UIs don't, so MXB falls back to OCR or shortcuts.
- **Switching the default audio output** has no public Windows API; MXB lists devices and opens Sound settings instead.
