import sys
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from ui.hud import FloatingHUD
from ui.tray import MXBTray
from ui.chat import ChatWindow
from engine.audio import VoicePipeline
from engine.command_bus import CommandBus
from safety.hotkeys import GlobalHotkeyListener
from utils.llm_builder import LLMBuilder
from utils.diagnostics import SystemDiagnostics
from utils.logger import log


def load_config():
    config_path = Path(__file__).parent / 'config.json'
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        log.warning(f"Could not load config.json: {e}. Using defaults.")
        return {}


def main():
    log.info("=" * 55)
    log.info("Starting Machine eXecutive Brain (MXB v3.0 Companion)...")
    log.info("=" * 55)

    config = load_config()

    # 1. Pre-flight Diagnostics
    health = SystemDiagnostics.get_health_report()
    if not health.get("microphone_active"):
        log.warning("[CRITICAL] No active microphone detected! You can still use the chat window.")
    if not health.get("ollama_running") and not health.get("nvidia_build_active"):
        log.warning("[WARNING] Neither Ollama nor NVIDIA Build API is active. Only fast-path commands will work.")

    # 2. Ensure Local LLM Model is compiled if Ollama is running
    if health.get("ollama_running"):
        try:
            LLMBuilder().ensure_build()
        except Exception as e:
            log.warning(f"LLMBuilder notice: {e}")

    # 3. Qt Application
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    # 4. Floating HUD
    hud = FloatingHUD()
    hud.show()

    # 5. Command Bus: the single brain entry point shared by voice and text
    bus = CommandBus(config)

    # 6. Core Voice Pipeline (feeds transcripts into the bus, keeps listening while MXB works)
    voice_pipeline = VoicePipeline(config, bus=bus)
    voice_pipeline.vad_status_changed.connect(hud.update_status)
    voice_pipeline.transcription_ready.connect(hud.update_transcript)
    voice_pipeline.action_feedback.connect(hud.update_action)
    voice_pipeline.mic_level_signal.connect(hud.update_mic_level)
    bus.reply_ready.connect(lambda text, _src: hud.update_action(text.splitlines()[0] if text else ""))
    bus.confirmation_requested.connect(lambda q: hud.update_action(f"CONFIRM: {q}  (say yes / no)"))
    voice_pipeline.start()

    # 7. Chat window (type to MXB, see replies, Stop / Yes / No buttons)
    chat = ChatWindow(bus, voice_pipeline)
    if config.get("ui", {}).get("open_chat_on_start", True):
        chat.show()

    # 8. System Tray Icon
    tray = MXBTray(hud, voice_pipeline, chat=chat)
    tray.show()

    # 9. Global Safety Controls & Hotkeys
    hotkeys = GlobalHotkeyListener(config, voice_pipeline, on_open_chat=chat.toggle_requested.emit)
    hotkeys.start()

    log.info("MXB v3.0 successfully initialized: voice + text companion active.")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
