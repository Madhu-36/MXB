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
