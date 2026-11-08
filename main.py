import os
import sys

if getattr(sys, "frozen", False):
    # A windowed build has no console (sys.stdout/stderr are None), and libraries that print
    # progress bars, like the first Whisper model download, would crash. Log that output instead.
    try:
        from utils.paths import logs_dir
        _console_path = logs_dir() / "console.log"
        if _console_path.exists() and _console_path.stat().st_size > 5 * 1024 * 1024:
            _console_path.replace(_console_path.with_name("console.log.1"))
        _console = open(_console_path, "a", encoding="utf-8", buffering=1)
    except Exception:
        _console = open(os.devnull, "w", encoding="utf-8")
    for _name in ("stdout", "stderr"):
        if getattr(sys, _name) is None:
            setattr(sys, _name, _console)

if __name__ == "__main__" and "--smoke-test" in sys.argv:
    # Build check (packaging/build.ps1): import everything, verify bundled files, exit 0/1. No UI.
    from utils.smoke_test import run_from_argv
    sys.exit(run_from_argv(sys.argv))

from PySide6.QtWidgets import QApplication, QMessageBox
from ui.hud import FloatingHUD
from ui.tray import MXBTray
from ui.chat import ChatWindow
from ui.marks_overlay import MarksOverlay
from engine.audio import VoicePipeline
from engine.command_bus import CommandBus
from safety.hotkeys import GlobalHotkeyListener
from utils.llm_builder import LLMBuilder
from utils.diagnostics import SystemDiagnostics
from utils.logger import log
from utils.paths import load_config as app_load_config
from utils.version import __version__


def load_config():
    config = app_load_config()
    if not config:
        log.warning("Could not load config.json. Using defaults.")
    return config


def run_first_time_setup(config: dict) -> dict:
    """Shows the setup wizard once (skipped with MXB_SKIP_SETUP=1). Returns the saved config."""
    if config.get("setup_complete") or os.environ.get("MXB_SKIP_SETUP"):
        return config
    from ui.setup_wizard import SetupWizard
    SetupWizard(config).exec()
    return load_config() or config


def main():
    log.info("=" * 55)
    log.info(f"Starting Machine eXecutive Brain (MXB v{__version__})...")
    log.info("=" * 55)

    # Qt first, so the first-run wizard shows before diagnostics, models and the microphone start
    app = QApplication(sys.argv)
    app.setApplicationName("MXB")
    app.setQuitOnLastWindowClosed(False)

    # One MXB at a time (autostart + a manual launch would fight over the mic and hotkeys)
    from utils.single_instance import acquire
    instance_lock = acquire()
    if instance_lock is None:
        log.info("MXB is already running; exiting this copy.")
        QMessageBox.information(None, "MXB", "MXB is already running. Look for its icon in the system tray.")
        return

    config = run_first_time_setup(load_config())

    # 1. Pre-flight Diagnostics
    health = SystemDiagnostics.get_health_report()
    if not health.get("microphone_active"):
        log.warning("[CRITICAL] No active microphone detected! You can still use the chat window.")
    if not health.get("ollama_running") and not health.get("nvidia_build_active"):
        log.warning("[WARNING] Neither Ollama nor NVIDIA Build API is active. Only fast-path commands will work.")

    # 2. Optional custom local model. Off by default: its Modelfile pulls the 4.7 GB llama3.1 base,
    #    and the router uses llm.local_model unless you point it at "mxb-brain".
    if health.get("ollama_running") and config.get("llm", {}).get("build_custom_model", False):
        try:
            LLMBuilder().ensure_build()
        except Exception as e:
            log.warning(f"LLMBuilder notice: {e}")

    # 4. Floating HUD
    hud = FloatingHUD()
    hud.show()

    # 5. Command Bus: the single brain entry point shared by voice and text
    bus = CommandBus(config)

    # 5b. v4 services: scheduler, phone remote (off until asked), plugins, number overlay
    overlay = MarksOverlay()
    bus.executor.ui_hooks["show_marks"] = overlay.show_requested.emit
    bus.executor.ui_hooks["hide_marks"] = overlay.hide_requested.emit
    bus.start_services()
    try:
        log.info(bus.executor.skills.describe())
    except Exception as e:
        log.warning(f"Plugins: {e}")

    # 5c. Local model: load it now, in the background, so the user's first command isn't the slow one
    if health.get("ollama_running") and not bus.router.llm.cloud_available():
        import threading
        threading.Thread(target=bus.router.llm.warm_up, name="llm-warmup", daemon=True).start()

    # 6. Core Voice Pipeline (feeds transcripts into the bus, keeps listening while MXB works)
    voice_pipeline = VoicePipeline(config, bus=bus)
    voice_pipeline.vad_status_changed.connect(hud.update_status)
    voice_pipeline.transcription_ready.connect(hud.update_transcript)
    voice_pipeline.action_feedback.connect(hud.update_action)
    voice_pipeline.mic_level_signal.connect(hud.update_mic_level)
    bus.reply_ready.connect(lambda text, _src: hud.update_action(text.splitlines()[0] if text else ""))
    bus.confirmation_requested.connect(lambda q: hud.update_action(f"CONFIRM: {q}  (say yes / no)"))
    voice_pipeline.start()
    # v4.3: meeting notes reuse the speech model the voice pipeline already loaded
    from engine.meetings import whisper_transcriber
    bus.executor.services["transcribe"] = whisper_transcriber(lambda: getattr(voice_pipeline, "whisper_model", None))

    # 7. Chat window (type to MXB, see replies, Stop / Yes / No buttons)
    chat = ChatWindow(bus, voice_pipeline)
    if config.get("ui", {}).get("open_chat_on_start", True):
        chat.show()

    # 8. System Tray Icon (also owns "quit", so a verified update can close MXB from a worker thread)
    tray = MXBTray(hud, voice_pipeline, chat=chat, bus=bus)
    bus.executor.ui_hooks["quit_app"] = tray.quit_requested.emit
    tray.show()

    # 8a. MCP servers from config connect in the background (their tools become MXB actions)
    from engine.mcp_client import load_server_specs
    if config.get("mcp", {}).get("enabled", True) and load_server_specs(config):
        import threading
        threading.Thread(target=lambda: log.info("MCP: " + bus.executor.mcp.start().replace("\n", " | ")),
                         name="mcp-start", daemon=True).start()

    # 8b. Quiet daily update check: announces in chat only when a newer release exists
    update_cfg = config.get("update", {})
    if update_cfg.get("check_on_start", True):
        from utils.updater import check_in_background
        check_in_background(lambda text: bus.announce(text, speak=False),
                            repo=update_cfg.get("repo", "Madhu-36/MXB"))

    # 9. Global Safety Controls & Hotkeys
    hotkeys = GlobalHotkeyListener(config, voice_pipeline, on_open_chat=chat.toggle_requested.emit)
    hotkeys.start()

    log.info(f"MXB v{__version__} initialized: voice + text + phone, agent, memory, automation active.")
    code = app.exec()
    instance_lock.unlock()
    sys.exit(code)


if __name__ == "__main__":
    main()
