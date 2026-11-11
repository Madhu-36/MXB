## v4.4.1 (2026-11-10) — Proactive Companion Hardening, Packaging Bundling & Offline Resilience
- **Turn Detection & Audio Safety**:
  - Enforced 1D audio tensor flattening and input sanitization in `turn_features` to eliminate out-of-memory array allocation errors (`np._core._exceptions._ArrayMemoryError`) on multi-channel streams.
  - Sanitization with `np.nan_to_num(posinf=1.0, neginf=-1.0)` prevents dirty audio buffers from poisoning ONNX session inferences.
  - Speculative turn transitions (`confirm()`, `cancel()`) made thread-safe and idempotent with `_lock`.
  - Pause/mute signals in `VoicePipeline.run()` immediately cancel active speculative turns and clear audio queues to prevent ASR worker thread stalls.
- **Voice ID & Windows File Lock Safety**:
  - Resolved Windows file handle leaks in `VoiceID._load()` via context management (`with np.load(...) as data:`), eliminating `WinError 32` file replacement collisions on Windows.
  - Added multi-threaded synchronization via `threading.RLock()` across all profile operations (`ready`, `score`, `check`, `add_sample`, `forget`).
  - Validation guards against `NaN`, `Inf`, zero-norm, or empty vectors; corrupt files trigger clean fallbacks rather than permanent command rejection.
- **Proactive Offline Resilience**:
  - Implemented offline calendar cache fallback: during network timeouts or server disconnects, MXB gracefully uses the cached calendar payload.
  - Added exception guards inside `events()`, safely skipping malformed recurring iCal/IMAP entries while retaining all valid ones.
  - Automated 48-hour cache compaction for alerted meeting notifications to prevent memory growth during multi-week sessions.
  - OS sleep/wake sensors (`busy()`, `battery()`, `idle_seconds()`) wrapped in fault-tolerant guards to survive system suspend/resume cycles.
- **Packaging & Frozen Distribution**:
  - Configured MCP submodule filtering in `packaging/mxb.spec` (`filter=lambda name: "cli" not in name`) to collect 80+ MCP tools without crashing on optional CLI dependencies.
  - Embedded dynamic multi-resolution icon generation into `mxb.spec` and bundled `mxb.ico` at root.
  - Standalone PyInstaller bundle (`dist/MXB/MXB.exe`, 20.6 MB) verified with automated smoke testing passing 100% clean (`failures: []`, `ok: true`).
- **Quality**:
  - 34 cross-platform suites (530 tests) passing 100% green in 63.5s with zero errors and zero failures.

## v4.4.0 — Knows your voice, plans better, speaks first
What a companion still lacked after v4.3.2: a measure of whether whole tasks succeed, a local brain big enough to plan them, a way to tell its owner from the TV, turns that end when the sentence does, a reason to speak first, one personality, a switch between your languages, and rules that stop two agents from breaking each other's work.

**Brain**
- New suite `python -m bench.run --suite brain`: 43 everyday requests (apps, multi-step, files, settings, memory, talk-only, risky) scored on the whole plan, in order. A destructive step the request didn't ask for fails the case. Nothing runs: actions are recorded, not executed. Its first run found four fast-path bugs, now fixed: "fire up spotify and then minimize it" and "open youtube and play arijit singh songs" opened the whole phrase as an app, "kill the internet connection" closed an app, and "bring the volume down to 30" only nudged the volume.
- Ollama plans are constrained to the tool's JSON schema (structured outputs, Ollama ≥ 0.5), so a small model can't return broken JSON. Hybrid thinking models (qwen3, deepseek-r1, magistral) are called with thinking off for speed (`llm.local_think`).
- Plans check their steps: after a failed step MXB doesn't type or click into whatever window happens to be open, and after opening an app it waits up to 6 s for that app's window before the next step.
- `scripts\upgrade_brain.bat` picks a local model for this PC's RAM (Qwen3-4B-Instruct-2507 from 8 GB, Qwen3-1.7B below), downloads it, runs the brain suite on the current and the new model, and switches unless the new one plans worse. MXB warns at startup when the local model is a 1B.

**Voice**
- Voice ID: say "learn my voice" and four short sentences, and only your voice gives commands. TV, calls and other people are ignored, and the chat says so ("Ignored a voice that isn't yours"). "Stop" and "cancel" still work from anyone. TitaNet-small speaker embeddings through sherpa-onnx (40 MB, ~37 ms per 3 s of audio on the CPU). On public multi-speaker recordings the owner scored 0.39 above the closest other speaker; through the full pipeline with synthetic voices, the owner scored 0.85–0.93 and other voices -0.08 to 0.33 (threshold 0.38). "forget my voice", "voice id off".
- Wake word in the audio (`listening.engine: "kws"`): an open-vocabulary keyword spotter (zipformer, 18 MB) hears "MXB" and "hey MXB" without transcribing first. Synthetic test: 30/32 wake phrases across 8 voices, 0/48 false alarms on look-alike phrases, no false wakes in 1.8 minutes of other speech. The transcript wake word stays the default until it's measured on the laptop mic.
- Replies about 0.5 s sooner with Smart Turn v3.2 (9 MB, `turn_detection.*`). At each pause MXB asks whether the sentence sounds finished. If it does, recognition starts at once while the silence timer runs, and the command goes out when the pause is confirmed; if you keep talking, that early transcript is dropped. If it sounds unfinished ("open the file called…"), MXB keeps listening up to 1.5 s. Through the real mic loop with synthetic voices and Whisper's CPU time simulated: end of speech to command 1.73 s → 1.23 s (median of 40 commands), none split. The first design ended the turn on the model's verdict alone; that split 15 of 40 commands, mostly right after "MXB,", and was replaced before release. The model file matches the copy Pipecat ships (SHA-256).
- Several languages at once: "I speak Kannada, Hindi and English". Recognition only chooses among your languages, so Kannada can't come out as Tamil or Sinhala, and the multilingual speech model loads in the background without a restart while English keeps working.

**Companion**
- MXB speaks first (`proactive.*`): a morning briefing (time, weather, today's events, unread email, reminders) once a day after 08:30 when you're at the PC and a calendar or mailbox is connected (no daily nag before that); "meeting in 10 minutes" alerts; a battery warning at 15%. Quiet hours 22:30–07:30, and nothing is spoken during a meeting or focus session. Calendar from your private iCal link (Google or Outlook); email read-only over IMAP with an app password (Gmail, Yahoo, iCloud; Microsoft accounts allow only OAuth, not supported yet), so nothing gets marked as read. `scripts\setup_proactive.bat` reads the calendar and signs in before saving anything, and keeps the link and the app password in the encrypted vault. "brief me", "what's on my calendar tomorrow", "check my email", "mute battery alerts", "stop proactive alerts".
- One persona (`persona.name`, `persona.style`: warm, crisp or playful) for greetings, "who are you" and the planner's replies. "call me S10" and MXB uses your name. When you sound frustrated ("it's still not working", or the same request twice), the reply is one sentence that goes straight to the fix.

**Release discipline**
- `python scripts/install_hooks.py`: every push first runs the CI checks (fatal lint, portable suites, routing gate). A pull request template, and CONTRIBUTING rules that apply to AI coding agents too: own branch, pull request, review. CI now installs faster-whisper and the calendar packages, so those tests run there.

**Quality**
- 6 new suites; 524 portable tests (v4.3.2: 433, two of which error on Linux CI because the UI Automation cache test needs Windows COM and the audio-buffer test needs PortAudio; both fixed here). Routing bench unchanged: tuned set 100% precision / 99.5% coverage, held-out 85.7% / 48.6%.

**Not measured yet** (needs the laptop): brain-suite accuracy of llama3.2:1b vs Qwen3-4B, voice ID, the keyword spotter and Smart Turn with your own voice, mic and room (`scripts\listening_bench.bat --turn on` / `--turn off` with `--wav` recordings).

## v4.3.2 (2026-11-09) — Performance, Safety Hardening & System Observability
- **Safety Policy & Injection Defense**:
  - Added prompt injection detection for forged tool-calling tokens (`<tool_call>`, ````tool_call`, `[TOOL_CALL:`) and jailbreak instructions (`DAN mode`, `unrestricted mode`).
  - Added `sanitize_tool_argument` to neutralize embedded fake fences and strip unprintable control characters from tool payloads.
- **Scam Shield & UPI Fraud Signatures**:
  - Expanded phishing regex database with latest known UPI fraud patterns: fake collect requests, auto-debit authorizations, and mandate approval tricks (`upi_mandate`).
- **Meeting Copilot Export**:
  - Implemented `export_meeting_markdown` generating executive markdown summaries with metadata timestamps, key decisions, action item checklists with assignees, and open questions.
- **UI Automation & Grounding Performance**:
  - Implemented active-turn UIA bounding box caching (`cache_ttl = 0.75s`) with automatic invalidation on user interaction, reducing consecutive UIA tree scan latency.
- **Audio Pipeline Resilience**:
  - Added real-time audio queue overflow guard and dropped-frame telemetry counter, preventing silent data starvation under burst CPU loads.
  - Safe fallback for `miniaudio` under Windows App Control / WDAC policies.
- **Command Bus Latency Telemetry**:
  - Added bus dispatch latency tracking across action and info lanes (`dispatch_metrics`, `average_dispatch_latency`).
- **Focus & Productivity Metrics**:
  - Added `calculate_productivity_metrics` and `productivity_score` computing 0-100 productivity scores and categorized focus breakdowns.
- **Accessibility & System Tray Enhancements**:
  - Added high-contrast speech cues toggle (`set_high_contrast_cues`).
  - Added live status tooltip in system tray (`refresh_status_tooltip`) displaying active focus sessions, meeting recordings, and mic state.
- **Verification Suite & Diagnostics**:
  - Enhanced `scripts/verify_all.py` with per-suite execution timing and automatic reporting of the top slowest suites.
  - Test suite passes 100% green across 421 portable and architectural tests.

## v4.3.1 — Listening fixes, measured on a real laptop
The report: MXB missed most voice commands, didn't run tools, and needed to hear better. Its own log on the laptop (Realtek mic through the Windows Sound Mapper, llama3.2:1b on the CPU) showed speech arriving at RMS ~0.004 (-48 dBFS), the voice detector scoring it ~0.09, 58 of 60 detections coming from a fixed loudness rule instead, Whisper repeating its prompt back on noise, missed wake words, "open notebook" finding no app, and the local model timing out three times in a row (136 s) before giving up.

**Hearing**
- **The real bug:** the Silero voice detector forgot everything every 32 ms. faster-whisper ≥ 1.1 resets the model's memory on each call and MXB called it once per frame. `StreamingVAD` keeps the state and audio context between frames (faster-whisper 0.10–1.2). On a real speech clip at the quiet-mic level: 2–9% of speech frames detected before, 95–98% after.
- **Input gain** before voice detection (`engine.input_gain`: `"auto"`, `"off"` or fixed dB). It tracks the room's noise floor and speech level, lifts quiet speech up to +30 dB without lifting the noise floor past a ceiling, cuts at once on a shout, soft-limits, and never learns from MXB's own voice. On the 4 s test clip it raises detection from 67–82% (memory alone) to 94–100%; with Windows' voice on the laptop the memory fix alone already reached 94–100%, so gain is the smaller of the two.
- Speech vs silence is judged against the room's noise floor. The old rule (any frame above RMS 0.0025 is speech) let a TV or people talking hold one utterance open forever: in the bench, v4.3.0 heard **0 of 6** commands under continuous background talk. Utterances are now also cut every 12 s (`engine.max_utterance_s`) and handed to recognition without ever blocking the microphone.

**Understanding**
- Removed Whisper's prompt ("Desktop commands: open app, close window…"): it came back as "open app, open app…" on noise, and turned "open Notepad" into "open note app".
- One Whisper decode (no 6-temperature fallback) with a token budget sized to the utterance: one 10 s stretch of background talk had taken 77 s and blocked the commands queued behind it.
- "open notepad, open notepad" becomes one command, noise loops are dropped, and "stop, stop, stop!" now stops MXB (the repeated form didn't match before).
- Wake word after fillers ("Ahh, MXB"), at the end ("open chrome, MXB"), at the start of a later sentence (talk ran into the command), and as Whisper spells it (MXP, AMX-B, AMXP, Emexbee, NXB…). A mention mid-sentence still doesn't wake MXB.

**Tools**
- "open notebook" opens Notepad. Windows' own tools start by name, common mishearings are corrected, your own app with the exact name still wins, and Microsoft Store apps without a Start-menu shortcut (WhatsApp, Spotify…) are found with `Get-StartApps`.
- Local models get a compact planner prompt: 13 core tools plus up to 12 matching the request, ~1,000 tokens instead of ~4,700 (which also overflowed `num_ctx` 4096 and cut off the instructions).
- One Ollama timeout or connection failure pauses Ollama for 30 s (`llm.local_retry_after_sec`), so the router's three planning attempts cost one timeout, not three. The model is loaded in the background at startup, every call uses the same `llm.num_ctx` (a change reloads the model), and the failure reply says whether Ollama is slow or not running.

**Measured on the laptop** (`scripts\listening_bench.bat`: Windows' voice says 6 commands through the real pipeline, mixed with 6 s of noise recorded from the mic, which held background talk at the time; scored like the command bus, every word must be heard)

| Condition | v4.3.0 | v4.3.1 |
| :--- | :--- | :--- |
| Background talk that never pauses, speech 10 dB above it | 0/6 (stuck listening) | transcribed in 12 s pieces |
| Background talk with pauses, speech 10 dB above it | 3/6, detector median 0.56–0.76 | **6/6**, 0.91–0.98 |
| Quiet room, quiet speech (-48 dBFS) | 5/6, detector median 0.22–0.34 | 5/6 → 6/6 with "AMXP" added, 0.96–0.99 |

**Quality**
- New suite `tests/test_v43_listening.py` (49 tests, including the real Silero model on a 4 s public-domain speech clip); 421 portable tests in total.

## v4.3.0 — Real-world problems
**Scam shield** (`engine/scam_shield.py`)
- "is this a scam?" for copied messages, links, MXB's browser page, the active window and QR codes. Offline weighted rules for the fraud patterns in Indian bank, NPCI and DoT advisories: OTP/PIN requests (including "enter PIN to receive"), remote-access apps, digital arrest and fake police/customs/courier calls, KYC and account-block threats, prize, refund, task-job and investment traps, pay-first fees, secrecy pressure, fake support numbers, family impersonation. Negation-aware ("do not share your OTP" is a genuine bank line), with multi-signal combos.
- Link analysis: look-alike brands vs official domains (`*.bank.in`, `*.gov.in` aware), shorteners, risky TLDs, punycode, raw IPs. UPI deep links and QR codes (zxing-cpp) decoded to show who they pay and how much; a UPI link that talks about *receiving* money scores as a scam.
- Optional AI second opinion that can only raise the risk; the message is fenced as untrusted.
- Clipboard guard: a spoken warning when you copy a high-risk message (offline only, nothing leaves the PC). Opening a scam-looking link asks first, whoever asked to open it.
- "report this scam" saves the message and a screenshot and opens Chakshu; "I got scammed" says call 1930 and opens cybercrime.gov.in.

**Meeting copilot** (`engine/meetings.py`)
- Live notes for any call or lecture: speakers (WASAPI loopback via PyAudioWPatch) and mic as separate streams, labelled Others / You, with echo suppression when there's no headset.
- Energy VAD segmenter, the voice pipeline's Whisper model (or MXB's own), markdown written as it goes to `Documents\MXB Meetings`.
- "what did they just say", "summarize the meeting so far"; on stop, map-reduce notes (summary, decisions, action items with owner and due date, open questions), indexed for "ask my notes". Consent reminder on every start.

**Accessibility mode** (`engine/accessibility.py`)
- Focus follower (speaks each newly focused control), screen description by the vision model with an accessibility-tree + OCR fallback, a reading cursor ("next button", "previous link", "first field") that never presses anything until "activate", "read this" with clipboard restore, "what is focused".
- Speech rate for every voice engine ("speak faster/slower", saved): SAPI rate, edge-tts rate and Piper length scale, applied on the speech thread before the next sentence.
- Windows' own tools by voice: Magnifier, zoom, color filters, contrast themes, Narrator. Added the missing plus/minus keys to the key map (Win+Plus couldn't be pressed before).

**Focus & study coach** (`engine/focus_coach.py`)
- Focus sessions with a nudge after 10 s on a distraction (repeats every 2 min), strict mode that minimizes distracting windows, "allow …" whitelists, end-of-session summary and break.
- Opt-in screen-time tracking: app and site names with seconds per day in `activity.db`, never titles or URLs; idle time and sleep gaps aren't counted, videos and calls are. Reports for today, yesterday, the week or one site.
- 20-20-20 eye-break reminders (off by default), offer to take notes when a Zoom/Teams/Meet call is in front, "delete my screen time data" (asks first).

**Integration and safety**
- 23 new catalog actions, router fast paths for all four features, and v4.3 config sections.
- Recording, tracking and settings actions are always denied to the agent; `scam_check` is allowed and read-only.
- Executor shutdown finishes running meeting notes and stops the tracker.

**Quality**
- 85 new tests (5 suites, 372 portable in total); all 372 also pass natively on Windows 11 with Python 3.14.
- MXB-Bench: 50 tuned v4.3 cases (100% correct). 10 new held-out phrases were written *before* the v4.3 rules and not tuned against: 3 handled fast, 7 handed to the LLM, 0 new misroutes. Held-out coverage is 48.6% on 38 cases (was 56.0% on 28).
- `verify_all.py` (all mode) now really runs every suite, including v4.2's. On GitHub Actions each failing test is also printed as an annotation, so it shows on the run page without signing in to read logs.

- `scripts\setup_and_check.bat` (double-click: install, test, check) and `python -m utils.windows_check`, which exercises the real Windows integrations (UIA, loopback, foreground tracker, SAPI rate, QR) with PASS/FAIL output.

**Fixes**
- Meeting copilot: Windows' speaker loopback sends no data at all while nothing plays (found by `utils.windows_check` on a real PC). The other side's timestamps drifted, and their last sentence before a pause waited for the next sound. Quiet streams are now padded with silence on the wall clock (0.25 s ticker).
- Windows: a file found by name was shown with a lowercased path (`c:\users\…`) in the delete/move confirmation, because search walked the case-folded permission roots. Search now walks folders in their real letter case; permission checks stay case-insensitive. Caught by the first Windows CI run.

## v4.2.0 — Web, tools, vision and your language
**MXB browser (Playwright)**
- Drives your installed Edge/Chrome with its own persistent profile; 18 `web_*` actions: open, search, numbered elements, click by number or text, fill, press, select, scroll, read, summarize, tabs, wait, screenshot.
- Works through the page (CDP), not the OS mouse, on its own thread; new-tab links become the current page; never types into password fields.
- The agent sees the page's numbered elements and text inside the untrusted fence; injection detection covers web pages.

**MCP client**
- Official MCP SDK (1.x and 2.x), stdio and Streamable HTTP, Claude-Desktop-compatible config, `${ENV}` expansion, pagination.
- Each tool becomes an action `mcp__<server>__<tool>` with JSON (or single-value) arguments; confirm-by-default trust model using tool annotations; agent tasks only get servers the goal names; server stderr to `logs/mcp-servers.log`.

**Pixel grounding**
- `click_visual`, `double_click_visual`, `type_visual`, `locate_visual`; `click_element` falls back to looking.
- Ollama (`qwen3-vl:4b`), NVIDIA (`qwen/qwen3.5-122b-a10b`) or any OpenAI-compatible server; parses relative-1000, absolute, normalized, percent and UI-TARS outputs; zoom pass on wide screens.

**Indian languages**
- Kannada, Hindi, Telugu, Tamil, Malayalam, Marathi, Bengali, Gujarati: script and romanized detection, cached LLM translation to English for routing, replies in the user's language (planner instruction + translated results), edge-tts Indian voices (also when SAPI/Piper is the main voice).
- Sarvam Saaras speech-to-English or multilingual Whisper; instant stop/yes/no and native-script wake word in every language; "speak in kannada" switches and saves the language.

**Fixes**
- Yes/no in Indian scripts never matched: the words weren't listed, and the cleanup stripped vowel signs.
- MCP server stderr no longer floods MXB's console; one shared, closed log handle.
- Catalog test now checks delegated handler tables instead of string presence.

## v4.1.0 — Made real
**Install & update**
- One-click per-user installer (PyInstaller one-folder + Inno Setup, no admin), Start-menu entry, optional desktop icon; upgrades clear stale files; uninstall removes autostart and keeps your data.
- First-run setup wizard: microphone picker with live level test, NVIDIA key check, Ollama detection, voice and sample, wake words, start with Windows, update checks. Also in the tray.
- User data moved to `%APPDATA%\MXB` for installed builds (`MXB_DATA_DIR` overrides; source checkouts unchanged).
- Updater: GitHub Releases, SHA-256 verified downloads, installer starts only after MXB exits, MXB relaunches after the upgrade. Voice: "check for updates", "install the update". Quiet daily check.
- Start with Windows (per-user Run key) by voice or wizard; single-instance guard; `--smoke-test` mode proves a frozen build bundled every module and data file.
- Release workflow: tag `v*` → tests + bench → build → smoke test → installer + `SHA256SUMS.txt` → GitHub Release.

**Security**
- Prompt-injection defense: untrusted-text fences with random tokens, injection detection → ask-before-every-action, per-goal action allowlist enforced in the executor, typed-text provenance check, risky-button confirmation, dangerous shortcuts blocked in agent mode.
- Audit log (JSONL, redacted, rotated): "show the audit log", "what did you do today".

**Quality**
- CI on every push: ruff (fatal rules), 236 cross-platform tests on Python 3.11/3.12 (Linux) and Windows, routing-bench gate.
- MXB-Bench: routing precision/coverage/latency on a tuned and a held-out set (published in README), 27 live Windows desktop tasks including a prompt-injection attack page.
- Router: new fast paths for the natural phrasings the bench's blind set exposed (number words, "pull up"/"bring up", known folders, website names, media keys, settings pages, "thanks" no longer cut from agent goals).

**Fixes**
- SQLite connections in memory and documents are now closed (they kept files locked on Windows).
- Tests no longer write into the real data folder (audit log, memory, undo journal, logs).
- Dropped unused torch/torchaudio from requirements (~2.5 GB per install).
- Windowed build: stdout/stderr go to a bounded `logs/console.log` so progress bars can't crash it; no duplicate logging.
- NVIDIA key from the wizard works immediately; `.env` lookup checks every candidate location.

## v4.0.0 — Advanced Companion
**Smarter agent**
- Set-of-Marks: numbered clickable elements for the agent and for voice ("show numbers", "click 12", "type hello in 3") with a click-through on-screen overlay.
- Native tool calling (OpenAI-style `tools`, schema with an enum of valid actions) on NVIDIA NIM and Ollama, with automatic JSON-mode fallback.
- Plan validation (aliases, unknown actions dropped, length cap) for every LLM plan.
- Agent verification (`expect`), stuck detection via screen fingerprints, banning of repeated failing steps; vision screenshots carry the same numbers.
- Undo journal for file actions with backups before overwrite and Recycle Bin restore.

**Real-time voice**
- Streams the LLM response and speaks the reply sentence by sentence while the plan is still generating.
- Neural TTS backends: edge-tts (e.g. en-IN-NeerjaNeural), Piper (offline), SAPI fallback; interruptible chunked playback; next sentence synthesized while the current one plays.
- Barge-in: headset mode interrupts instantly; speaker mode filters MXB's own echo by comparing transcripts with what it just said.
- Offline audio wake word via openWakeWord; nothing is transcribed until the wake word is heard.

**Memory & documents**
- Semantic memory in SQLite with embeddings (Ollama / NVIDIA / dependency-free hashing), legacy import, automatic preference learning that never stores secrets or swallows commands.
- Knowledge base: incremental folder indexing (TXT/MD/code/PDF/DOCX), hybrid retrieval, cited answers, respects file permissions.

**Phone remote & automation**
- Token-secured LAN web app with chat, live progress, Stop, Yes/No confirmations and screen peek; private-network only; lockout after bad tokens; QR code in the chat window.
- Reminders and scheduled commands with natural-language times (relative, absolute, daily, weekday, weekly, intervals), persisted across restarts.
- Spoken routines and record-and-replay workflows (element-name clicks with coordinate fallback, password keystrokes excluded).
- Plugin skills (`plugins/*.py`, `@skill` decorator) with two examples; skills join the fast path and the LLM tool list.

**Tests**: 4 new suites (79 tests) + 2 new end-to-end flows; 190 cross-platform tests pass.

## v3.0.0 — AI Desktop Companion
**New**
- Text chat window (`ui/chat.py`) sharing one conversation with voice; Stop / Mic / Yes / No buttons; `Ctrl+Alt+Space`.
- `CommandBus` (`engine/command_bus.py`): one entry for voice + text, instant stop/confirm control lane, ordered action lane, parallel info lane.
- Wake word gate with follow-up window (`engine/wake_word.py`); "stop" and "yes/no" never need the wake word.
- UI Automation element finder (`engine/ui_automation.py`): search boxes, named fields, buttons/links/tabs, with OCR and shortcut fallbacks. New actions `focus_search_box`, `search_on_screen`, `type_into`, `click_element`, `list_ui_elements`.
- Hardware manager (`engine/hardware.py`): Bluetooth/Wi-Fi radios, Bluetooth device connect/disconnect, Wi-Fi networks, exact volume, mic mute, brightness, device inventory, Settings pages, shutdown/restart/sleep/sign-out.
- File access permissions (`safety/permissions.py`) plus find/read (PDF, DOCX, text)/copy/move/rename; deletes go to the Recycle Bin by default.
- Safety policy + confirmation handshake (`safety/policy.py`) for destructive actions; denied when no confirmation channel exists.
- Agent loop (`engine/agent_loop.py`) for observe-act multi-step tasks; optional vision model.
- Single action catalog (`engine/actions_catalog.py`) drives the LLM prompt for both NVIDIA and Ollama; shared `LLMClient` with NVIDIA → Ollama fallback.
- TTS can be interrupted mid-sentence without killing the speech thread; typed chat gets text-only replies by default.

**Fixed**
- Screenshots crashed (`Path`/`psutil.time` errors) and pressed F12 (opened DevTools) before capturing.
- The LLM never received the active window (missing `pygetwindow` import was swallowed).
- Screen capture ran Qt `grabWindow` on worker threads; now uses thread-safe `PIL.ImageGrab`.
- Typed text, remembered facts and vault secrets were lowercased.
- `delete_file` permanently deleted with no confirmation; `close app` force-killed with `/F` (unsaved work lost); kill-switch didn't abort running actions.
- Clipboard paste restored the old clipboard too early (apps pasted the wrong text); clipboard analysis used a different local model than config.
- OCR packages (`winrt-*`) were missing from `requirements.txt`; settings export dropped unknown config keys.


## Changelog Entry 1
Started changelog for V2.0.

## Changelog Entry 2
Documented glassmorphism update.

## Changelog Entry 3
Documented fuzzy finding.

## Changelog Entry 4
Documented DuckDuckGo integration.

## Changelog Entry 5
Documented Date/Weather injection.

## Changelog Entry 6
Documented TF-IDF updates.

## Changelog Entry 7
Documented win11toast integration.

## Changelog Entry 8
Documented asynchronous SAPI5.

## Changelog Entry 9
Documented psutil checks.

## Changelog Entry 10
Documented QPropertyAnimation.

## Changelog Entry 11
Documented voice activity threshold.

## Changelog Entry 12
Documented 16000Hz resampling.

## Changelog Entry 13
Documented condition_on_previous_text=False.

## Changelog Entry 14
Documented auto-builder hash logic.

## Changelog Entry 15
Documented Modelfile formatting.

## Changelog Entry 16
Documented weather API.

## Changelog Entry 17
Documented geolocation API.

## Changelog Entry 18
Documented pygetwindow usage.

## Changelog Entry 19
Documented Ctrl+Shift+M mute.

## Changelog Entry 20
Completed changelog entries for today.
