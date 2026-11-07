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
