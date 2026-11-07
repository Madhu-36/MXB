# MXB v4.1 Companion Guide

MXB is a Windows desktop companion you can **talk to or type to**. It keeps listening while it works, can operate any app through the mouse, keyboard and accessibility tree, controls your hardware, and works with your files. Anything destructive needs your "yes" first.

---

## 1. Setup

**Installer (recommended).** Run `MXB-Setup-<version>.exe` from the GitHub Releases page. It installs for your user only (no admin prompt) into `%LOCALAPPDATA%\Programs\MXB`. On first launch the setup wizard walks you through:

1. **Microphone**: pick one and press *Test* to see the level.
2. **AI brain**: paste an NVIDIA key (checked live) and/or use a local Ollama model (detected automatically).
3. **Voice and listening**: speech engine, voice (play a sample), wake word(s), wake-word vs always-listening.
4. **Finish**: start with Windows, open chat on start, daily update check.

Run it again any time from the tray: *Run Setup Wizard*. Your settings, memory, document index, audit log and logs live in `%APPDATA%\MXB` (set `MXB_DATA_DIR` to move them). Uninstalling leaves that folder alone; delete it yourself to remove everything.

**From source:**

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
# LLM brain (pick one or both)
setx NVIDIA_API_KEY "nvapi-..."      # cloud: fast, best planning quality
ollama pull llama3.1:8b               # local: private; set llm.local_model to it
python -u main.py
```

A source checkout keeps its data next to the code, exactly as before. The setup wizard appears once (skip it with `MXB_SKIP_SETUP=1`).

**Updates.** Say *"check for updates"* or use the tray. MXB also checks once a day and only mentions it when a new version exists. *"Install the update"* asks first, downloads the installer, verifies its SHA-256 against the release's `SHA256SUMS.txt` (a mismatched download is deleted), closes MXB, upgrades and reopens it. From source, update with `git pull`.

**Start with Windows.** *"start with windows"*, *"don't start with windows"*, or the wizard checkbox. It's a per-user Run entry (no admin), removed on uninstall. Only one MXB runs at a time; opening it again just tells you it's already in the tray.

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

### v4: precision clicking, undo
| Say / type | Action |
| :--- | :--- |
| show numbers · hide numbers | Numbered boxes over every clickable element (auto-hides after 20 s) |
| click 12 · type hello in 3 | `click_mark` / `type_mark` |
| undo the move · undo the last file action · undo that (within 2 min) | `undo_last`: reverses MXB's last move/rename/copy/create/delete/overwrite |

### v4: memory & your documents
| Say / type | Action |
| :--- | :--- |
| I prefer short answers · my manager is Ravi · call me S10 | Learned automatically (`remember_preference`). Anything that looks like a password/PIN/card/account number is never stored |
| what do you remember about me · what do you know about my manager | `recall_memories` |
| forget my old address | `forget_memory` |
| index my Notes folder · index D:\Projects | `index_folder` (background; MXB tells you when done; re-run to pick up changes) |
| ask my documents when is the SIH deadline · what do my notes say about X | `ask_documents`: answers only from your files, with `Sources:` |
| knowledge status | What's indexed |

Embeddings: `memory.embedding_provider = "auto"` uses Ollama (`ollama pull nomic-embed-text`) when it's running, otherwise a local keyword-hashing embedder. Your documents are never sent to the cloud unless you set it to `"nvidia"` yourself.

### v4: reminders, schedules, routines, recordings
| Say / type | Action |
| :--- | :--- |
| remind me in 20 minutes to stretch · remind me to call mom at 5 pm · remind me tomorrow at 9 am to submit the form | `set_reminder`: toast + voice + chat |
| remind me every 2 hours to drink water · every monday at 9 am remind me to send the report | Recurring reminders |
| schedule open outlook every weekday at 9 am · every day at 10 pm lock the pc | `schedule_command`: runs the command through the normal pipeline (risky ones still ask "yes"; unanswered = no) |
| list my reminders · cancel the reminder to call mom · cancel reminder 2 · cancel all reminders | Manage jobs |
| create a routine called work mode: open vs code; open chrome; set volume to 30 | `create_routine` (`;` or "then" separates steps) |
| run the work mode routine · run work mode | `run_routine` |
| start recording expense report … stop recording · run expense report | Record your clicks/typing and replay them. Clicks replay by element name, with the recorded spot as fallback. Password fields are never recorded; clicks in MXB's own window are ignored |
| list routines · delete the routine work mode | Manage |

### v4: phone remote
1. Say or type **"turn on phone remote"** and answer **yes**.
2. Scan the QR code shown in the chat window (or open the link) on a phone on the **same Wi-Fi**.
3. On the phone you can chat, follow live progress, press **Stop**, answer **Yes/No** questions, and tap **Screen** to peek at the PC.
"turn off phone remote" stops it; "new phone link" invalidates old links.

### v4: plugins
Drop a Python file into `plugins/`:
```python
from engine.skills import skill

@skill(name="open_github", patterns=[r"^open my github$"], description="Open my GitHub profile", target="none")
def open_github(target, ctx):
    ctx.executor.execute_action("open_url", "github.com/your-name")
    return "Opening your GitHub."
```
Restart MXB. The pattern runs instantly, and the skill also appears in the LLM's action list. `risk="confirm"` makes MXB ask first. Included examples: `quick_notes.py` ("note that…", "read my notes") and `youtube.py` ("play lofi on youtube"). "list plugins" shows what's loaded. **Plugins run with your permissions; only install code you've read.**

---

## 4. Safety model

1. **Confirmation before damage.** These actions always ask *"…? Say yes or no."* (voice, typed yes/no, or the chat buttons): delete, empty Recycle Bin, kill process, force-close an app, shutdown/restart/sleep/sign-out, overwriting an existing file, broad file-access grants, and reading vault secrets aloud. No answer within 30 s counts as **no**. "stop" counts as **no** and halts everything.
2. **No confirmation channel → no action.** If the executor is used without the bus (scripts, tests), risky actions are refused rather than run silently.
3. **File scope.** By default MXB uses only your personal folders (Desktop, Documents, Downloads, Pictures, Music, Videos, OneDrive). Other locations need a grant, which is saved in `permissions.json` and can be revoked by voice.
4. **OS folders are always read-only.** Even with full access, MXB never writes to Windows, Program Files or ProgramData. A misheard command must not be able to break the OS.
5. **Deletes are recoverable by default.** Normal deletes go to the Recycle Bin. Permanent deletion must be asked for explicitly.
6. **Wake word by default.** With `listening.mode: "always"` MXB acts on everything it hears, including a TV or other people in the room. Only switch it on in a quiet room.

7. **Phone remote is off by default** and needs a "yes" to turn on. Every request needs a 128-bit token, only private-network addresses are served, and 10 bad tokens block that address for 10 minutes. It's plain HTTP on your LAN, so don't enable it on public Wi-Fi. Set `remote.allow_screen: false` to disable screen peek.
8. **Memory never stores secrets.** Statements mentioning passwords, PINs, OTPs, card, Aadhaar or bank/account numbers are not learned. Memory and indexes stay on this PC (`mxb_memory.db`, `mxb_knowledge.db`).
9. **Recording is explicit and visible.** Only between "start recording" and "stop recording", never in password fields.
10. **Scheduled commands get no free pass.** A destructive scheduled command still asks for confirmation; if nobody answers, it's cancelled.

11. **Prompt-injection protection (agent mode).** Text MXB reads from the screen, web pages, files, the clipboard or your document index is untrusted. It's fenced with a random marker the page can't fake, and the model is told it's data, not instructions. On top of that, the executor enforces:
    - **A per-goal allowlist.** UI actions are allowed; file reading, volume, Bluetooth etc. only when your goal mentions them. Deleting, the vault, power, terminal, routines, schedules, updates, autostart and memory changes are never available during a screen task: ask for those directly.
    - **Typed-text provenance.** If the agent wants to type something that isn't from your request, you're asked first.
    - **Risky buttons.** Clicking Send, Pay, Delete, Allow, Install, Share and the like asks first unless your goal said so.
    - **Suspicious mode.** If the screen contains instruction-like text ("ignore previous instructions", "send the file to…"), MXB warns you and asks before every non-read action for the rest of the task.
12. **Audit log.** Every action, block and refusal is appended to `audit.log.jsonl` in the data folder with the time, source (voice, text, phone, schedule, agent) and outcome. Passwords, OTPs and card or account numbers are redacted; vault actions are fully hidden. Ask *"show the audit log"* or *"what did you do today?"*. It rotates at 5 MB (3 old files kept).

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
| `llm.streaming` / `llm.use_tool_calling` | `true` / `true` | Speak while streaming (voice) / native tool calling (text, agent) |
| `voice.tts_engine` | `"auto"` | `edge`, `piper`, `sapi` |
| `voice.edge_voice` | `en-IN-NeerjaNeural` | Any edge-tts voice, e.g. `en-IN-PrabhatNeural`, `en-US-AriaNeural` |
| `voice.piper_exe` / `voice.piper_model` | `""` | Paths for offline Piper TTS |
| `voice.barge_in` | `"auto"` | `headset`, `speaker`, `off` |
| `listening.engine` | `"transcript"` | `"openwakeword"` for the offline audio wake word |
| `listening.openwakeword_model` / `_threshold` | `hey_jarvis` / `0.5` | Pretrained name or path to a custom `.onnx` |
| `memory.embedding_provider` | `"auto"` | `ollama`, `nvidia`, `local` |
| `agent.max_marks` / `agent.max_stuck_turns` | `60` / `3` | Set-of-Marks size, stuck limit |
| `remote.enabled` / `remote.port` / `remote.allow_screen` | `false` / `8765` / `true` | Phone remote |
| `skills.enabled` / `skills.disabled` | `true` / `[]` | Plugin loading; disable by file name |
| `ui.start_with_windows` | `false` | Set by the wizard or "start with windows" (the Run entry is the source of truth) |
| `update.check_on_start` / `update.repo` | `true` / `"Madhu-36/MXB"` | Daily quiet update check; where releases come from |
| `llm.build_custom_model` | `false` | Build the old `mxb-brain` Ollama model on start (pulls a 4.7 GB base) |
| `setup_complete` | absent | Set after the first-run wizard; delete it to see the wizard again |

---

## 6. Measuring MXB (MXB-Bench)

```powershell
python -m bench.run                        # routing: precision, coverage, latency (tuned vs held-out set)
python -m bench.run --suite live --yes     # 27 real desktop tasks (Windows; uses your mouse and keyboard)
python -m bench.run --suite all --llm --update-readme   # everything, with the LLM, published to README
python -m bench.run --list                 # list live tasks and what they need
```

The live suite works in a sandbox folder (`Documents\MXB-Bench-<time>`) with its own memory, audit log and schedules, restores your volume, and closes what it opened. Move the mouse to the top-left corner to abort. The held-out routing set is never used for tuning, so its numbers are the honest ones.

---

## 7. Known limits

- **Bluetooth connect/disconnect** works for classic audio devices (earbuds, headphones, speakers) by toggling their audio profiles through the Win32 Bluetooth API. Some drivers require admin rights. BLE mice and keyboards can't be connected programmatically; MXB opens Bluetooth settings instead and says so.
- **Wi-Fi connect** works for networks Windows has already saved. For new networks MXB opens Wi-Fi settings so you can type the password yourself.
- **Brightness** works on laptop panels (WMI) and monitors with DDC/CI enabled.
- **Accessibility tree:** most Windows apps, Chrome, Edge and Firefox expose their controls. Games and custom-drawn UIs don't, so MXB falls back to OCR or shortcuts.
- **Switching the default audio output** has no public Windows API; MXB lists devices and opens Sound settings instead.
- **Barge-in on laptop speakers** relies on the echo filter (comparing what it heard with what it just said). Headsets interrupt instantly and are more reliable.
- **edge-tts needs internet**; when it fails MXB switches to Windows voices for the session. Use Piper for an offline neural voice.
- **The offline wake word** ships with pretrained phrases ("hey jarvis", "alexa", "hey mycroft"). A custom "hey MXB" needs a model trained with openWakeWord's training notebook.
- **Local hashing embeddings** match by keywords and phrases, not deep meaning. Run `ollama pull nomic-embed-text` for real semantic recall.
- **Unsigned installer.** SmartScreen may warn on first install (*More info → Run anyway*). The update checksum catches corrupted or tampered downloads, but only code signing protects against a compromised release account.
- **Injection detection is pattern-based.** A clever page may not trip it; the per-goal allowlist and confirmations are what actually stop harm.
- **Tool calling** depends on the model. If the hosted model rejects `tools`, MXB detects that once and uses JSON mode from then on.
