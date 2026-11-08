# MXB v4.3 Companion Guide

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

### v4.2: MXB browser (websites, reliably)
MXB opens its own browser window (your installed Edge, or Chrome) with its own profile in the data folder: sign in to your sites there once and MXB stays signed in. It works through the page itself, not your mouse, so you can keep typing elsewhere while it browses.

| Say | Does |
| :--- | :--- |
| "browse to github.com", "open wikipedia.org in MXB browser" | Opens the page |
| "show page elements" | Numbers every button, link and field: `[7] button 'Sign in'` |
| "web click 7", "web click sign in" | Clicks by number or visible text |
| "fill the search box with playwright", "type python into field 3" (planner) | Types into a field (`web_fill "3 :: python"`) |
| "read this page", "summarize this page", "what is this page about" | Reads or summarizes (the page is treated as data, never as instructions) |
| "list tabs", "go back", "close MXB browser" | Tabs and navigation |

MXB never types into password fields: click the field and type your password yourself, then say "continue". Agent tasks ("find the cheapest flight on…") use the same numbered elements. Set `web.browser` to `chrome`, or `web.cdp_url` to attach to a Chromium you started with `--remote-debugging-port=9222` (recent Chrome only allows that with a separate profile).

### v4.2: MCP tools (any app with an MCP server)
Add servers to `config.json` (same format as Claude Desktop), or set `"claude_desktop_config": true` to reuse Claude Desktop's list:
```json
"mcp": {
  "enabled": true,
  "trust": "ask",
  "servers": {
    "github": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
               "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}, "trust": "read_only"},
    "notion": {"url": "https://mcp.notion.com/mcp", "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"}}
  }
}
```
`${NAME}` is filled from your environment or MXB's `.env`. Servers connect in the background when MXB starts. Say *"list MCP tools"* to see them, *"reload MCP"* after editing the config, or just ask: *"using github, list my open issues"*.

Trust per server: `ask` (default) asks before every tool call; `read_only` runs tools that declare themselves read-only without asking; `auto` asks only for tools that declare themselves destructive. During agent tasks a server is only available if your goal names it. Server logs go to `logs/mcp-servers.log`.

### v4.2: clicking by looking (pixel grounding)
For icons, games and apps without accessibility info: *"visually click the gear icon"*, *"where is the recycle bin on the screen"*. Ordinary *"click Settings"* also falls back to looking when the accessibility tree and OCR can't find it.

Setup, either one:
- Local and private: install Ollama 0.12.7+ and `ollama pull qwen3-vl:4b` (3.3 GB).
- Cloud: your NVIDIA key is enough (uses `qwen/qwen3.5-122b-a10b`).
- Your own server: `"grounding": {"provider": "openai", "base_url": "http://localhost:8000/v1", "model": "<your model>"}`; set `"coord_mode": "absolute"` for models that answer in pixels (Qwen2.5-VL, UI-TARS).

### v4.2: Indian languages
Type or speak Kannada, Hindi, Telugu, Tamil, Malayalam, Marathi, Bengali or Gujarati. MXB answers in the same language with a neural voice for it (`voice.indic_voice_gender`: female/male). Native script is recognized automatically. For romanized commands ("notepad open maadi"), say *"speak in kannada"* (or set `voice.language`).

- **Best speech recognition:** add `SARVAM_API_KEY=...` to MXB's `.env`. Sarvam's Saaras model turns Indian-language speech straight into English and reports which language you spoke.
- **Offline:** with `voice.language` set to a language (or `auto`), MXB loads multilingual Whisper (`engine.whisper_model_multilingual`, default `small`). Restart after changing it. Hindi works well; Kannada and Telugu are much weaker on `small`, so use Sarvam or a larger model with a GPU.
- "Stop", "yes" and "no" work instantly in every supported language (ನಿಲ್ಲಿಸು, रुको, ఆపు, நிறுத்து; ಹೌದು / ಬೇಡ, हाँ / नहीं …), and the wake word MXB is understood in native script too.

### v4.3: scam shield (India-first)
| Say | Does |
| :--- | :--- |
| "is this a scam" (after copying a message), "is this link safe", "is this a scam: *paste the message*" | Checks what you copied, else MXB's browser page, else the active window, and says what to do |
| "check this QR code" | Reads a QR code on screen (or an image file). A UPI QR code always **pays**: MXB says who it pays and how much |
| "report this scam" | Saves the message and a screenshot to `Documents\MXB Scam Reports` and opens Chakshu on Sanchar Saathi |
| "I got scammed", "I lost money to a scam" | Tells you to call **1930** right away and opens cybercrime.gov.in, with the evidence saved |

What it looks for: OTP/PIN requests (including "enter your PIN to receive"), remote-access apps, "digital arrest" and fake police/customs/courier calls, KYC and account-block threats, prize, refund, task-job and investment traps, pay-first fees, secrecy pressure, look-alike bank and government links (official domains, `*.bank.in`, `*.gov.in`), link shorteners, risky TLDs, punycode and raw-IP links, and UPI payment links dressed up as refunds. Each warning says why.

- Copying a high-risk message gets a spoken warning. That check is offline rules only: the copied text never leaves the PC (`scam_shield.watch_clipboard`).
- Opening a link that looks like a scam asks first, whoever asked to open it.
- On explicit checks an AI second opinion can raise the risk, never lower it, and the message is fenced as untrusted, so a scam can't talk its way to "safe".

### v4.3: meeting copilot
| Say | Does |
| :--- | :--- |
| "take meeting notes", "start notes for the DSA lecture", "transcribe this call" | Records what you hear (the other side, from your speakers or headset) and what you say (mic) as two streams, and writes the transcript live to `Documents\MXB Meetings\<date> <title>.md` |
| "what did they just say", "summarize the meeting so far" | Catch up in the middle of a call |
| "stop meeting notes", "the meeting is over" | Adds a summary, decisions, action items (who, what, by when) and open questions, and indexes the file so "ask my notes about the hackathon meeting" works |
| "list my meetings", "recap the last meeting", "what were the action items from the last meeting" | Past meetings |

Works with any app (Zoom, Meet, Teams, WhatsApp calls, YouTube lectures); no bot joins the call. **Tell the other people you're transcribing.** Consent rules for recording differ by place, and MXB reminds you each time. Hearing the other side needs PyAudioWPatch (in `requirements.txt`); without it MXB hears only your mic. Transcription uses the same Whisper model as voice commands, so an English-only model (`base.en`) won't transcribe Hindi or Kannada calls.

### v4.3: accessibility mode (blind and low-vision users)
| Say | Does |
| :--- | :--- |
| "turn on accessibility mode", "I can't see the screen" | MXB reads whatever gets keyboard focus as you Tab around: "Search, edit box" |
| "what's on my screen", "what am I looking at" | Describes the screen with the vision model. Without one, it summarizes the window from the accessibility tree and its text |
| "next button", "previous link", "first field", "next element" | Moves a reading cursor and reads "Send, button, 3 of 4" **without pressing anything**. "activate" clicks it |
| "read this" | Reads the selected text (your clipboard is put back), else the focused item |
| "what is focused" (and "where am I" in accessibility mode) | The window and the focused element |
| "speak faster", "speak slower", "speak at normal speed", "set your speech rate to 40" | Speaking speed for every voice engine, saved for next time |
| "turn on magnifier", "zoom in the screen", "magnifier off", "invert colors", "turn on high contrast", "turn on narrator" | Windows' own tools (Win+Plus, Win+Minus, Win+Esc, Win+Ctrl+C, Alt+Shift+PrtScn, Win+Ctrl+Enter) |

Commands work in the Indian languages above, and replies are spoken in your language. Win+Ctrl+C only works after you turn on *Keyboard shortcut for color filters* in Settings → Accessibility → Color filters. If you also run NVDA or Narrator, turn MXB's focus reading off ("turn off accessibility mode") so you don't hear everything twice; the other commands keep working.

### v4.3: focus & study coach
| Say | Does |
| :--- | :--- |
| "start a 50 minute focus session for DSA practice", "help me focus", "focus on ML notes for an hour" | A focus session. After 10 seconds on a distraction: "You're on YouTube. 32 min left on 'DSA practice'. Back to it?" (again every 2 minutes if you stay). At the end: focused vs distracted minutes and a break suggestion |
| "start a strict study session for 1 hour, allow LeetCode" | Strict mode minimizes distracting windows (nothing is closed). "allow …" whitelists sites for that session |
| "how much time is left in my focus session", "stop the focus session" | Status, or end early with a summary |
| "track my screen time", then "how much screen time today", "screen time this week", "how much time did I spend on YouTube this week" | Local screen-time reports by category (focused, distracted, messages, meetings) |
| "remind me to rest my eyes", "… every 30 minutes", "turn off eye breaks" | 20-20-20 reminders after continuous screen time |
| "delete my screen time data" | Erases it (asks first) |

Privacy: nothing is tracked until you ask. `activity.db` in the data folder stores app and site names with seconds per day and your session goals, never window titles, URLs or content (a title is read for a moment to tell YouTube from LeetCode, then dropped). While the coach is running (a focus session, screen-time tracking or eye breaks), it offers once per call to take notes when you're in a Zoom, Teams or Meet call. If you study from YouTube lectures, add `"productive": ["YouTube"]` under `focus` or say "allow YouTube" for that session.

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

13. **Listening and tracking are your call.** Meeting notes, screen-time tracking, focus sessions, accessibility mode, speech settings and scam reports are never available to the agent, so a web page or document can't start them. Scam *checks* are allowed (read-only).
14. **Scam links need a yes.** Opening a link that scores as a likely scam asks first, whoever asked to open it: you, the agent or a schedule.

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
| `scam_shield.watch_clipboard` | `true` | Warn when something you copy looks like a scam (offline rules) |
| `scam_shield.check_links` | `true` | Ask before opening links that look like scams |
| `scam_shield.ai_second_opinion` | `true` | LLM second opinion on explicit checks (can only raise the risk) |
| `scam_shield.region` | `"IN"` | Reporting advice (India: Chakshu, 1930, cybercrime.gov.in) |
| `meetings.folder` / `meetings.capture_system_audio` | `""` (Documents\MXB Meetings) / `true` | Where notes go; hear the other side of calls |
| `accessibility.describe_with_vision` / `accessibility.move_mouse` | `true` / `true` | Describe the screen with the vision model; mouse follows the reading cursor |
| `voice.rate_percent` | absent | Speaking speed saved by "speak faster" (-50 to 100) |
| `focus.default_minutes` | `25` | Session length when you don't say one |
| `focus.track_activity` | `false` | Screen-time tracking (opt-in) |
| `focus.eye_break_minutes` | `0` | 20-20-20 reminders (0 = off) |
| `focus.productive` / `focus.distracting` | `[]` | Override app or site categories, e.g. `["YouTube"]` |

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
- **MXB browser** numbers elements in the main page, not inside iframes (embedded widgets, some payment forms): use web click with visible text, or the desktop tools.
- **MCP servers that need an OAuth browser login** aren't supported yet; use servers that take a token (env or header).
- **Visual clicking** is only as good as the model (Qwen3-VL-4B is strong on ordinary apps, weaker on dense professional software). In agent mode risky buttons still ask first.
- **Indian languages** add one translation round trip per command (cached); edge voices need internet.
- **Scam shield** is rules plus an optional AI opinion. New scam scripts can slip through and an unusual genuine message can be flagged; it always says why, so you can judge. It warns, it doesn't block payments.
- **Meeting copilot** loopback records everything your PC plays, notification sounds included. Speakers are labelled You and Others, not by name. Noisy calls and Indian-language calls need a bigger or multilingual Whisper model.
- **Accessibility mode** reads what apps expose through UI Automation. Custom-drawn apps and games expose little ("what's on my screen" still works by looking). It complements NVDA and Narrator; it isn't a full screen reader (no braille, no browse mode).
- **Focus coach** checks the foreground window every 5 seconds and names sites from page titles, so a YouTube lecture counts as YouTube unless you mark it productive.
- **Tool calling** depends on the model. If the hosted model rejects `tools`, MXB detects that once and uses JSON mode from then on.
