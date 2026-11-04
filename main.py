import sys
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from ui.hud import FloatingHUD
from ui.tray import MXBTray
from engine.audio import VoicePipeline
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
    log.info("Starting Machine eXecutive Brain (MXB v2.0)...")
    log.info("=" * 55)

    # 1. Pre-flight Diagnostics
    health = SystemDiagnostics.get_health_report()
    if not health.get("microphone_active"):
        log.warning("[CRITICAL] No active microphone detected!")
    if not health.get("ollama_running") and not health.get("nvidia_build_active"):
        log.warning("[WARNING] Neither Ollama nor NVIDIA Build API is active. Voice reasoning may fail.")

    # 2. Ensure Local LLM Model is compiled if Ollama is running
    if health.get("ollama_running"):
        try:
            LLMBuilder().ensure_build()
        except Exception as e:
            log.warning(f"LLMBuilder notice: {e}")

    # 3. Qt Application
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = load_config()

    # 4. Floating HUD
    hud = FloatingHUD()
    hud.show()

    # 5. Core Voice Pipeline
    voice_pipeline = VoicePipeline(config)

    # Connect Voice Pipeline to HUD
    voice_pipeline.vad_status_changed.connect(hud.update_status)
    voice_pipeline.transcription_ready.connect(hud.update_transcript)
    voice_pipeline.action_feedback.connect(hud.update_action)
    voice_pipeline.mic_level_signal.connect(hud.update_mic_level)

    # Start audio thread
    voice_pipeline.start()

    # 6. System Tray Icon
    tray = MXBTray(hud, voice_pipeline)
    tray.show()

    # 7. Global Safety Controls & Hotkeys
    hotkeys = GlobalHotkeyListener(config, voice_pipeline)
    hotkeys.start()

    log.info("MXB v2.0 successfully initialized and active.")
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
