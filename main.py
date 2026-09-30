import sys
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from ui.hud import FloatingHUD
from ui.tray import MXBTray
from engine.audio import VoicePipeline
from safety.hotkeys import GlobalHotkeyListener
from utils.llm_builder import LLMBuilder

def load_config():
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        return json.load(f)

def main():
    LLMBuilder().ensure_build()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)

    config = load_config()

    # Initialize HUD
    hud = FloatingHUD()
    hud.show()

    # Initialize Engine
    voice_pipeline = VoicePipeline(config)
    
    # Connect Engine to HUD
    voice_pipeline.vad_status_changed.connect(hud.update_status)
    voice_pipeline.transcription_ready.connect(hud.update_transcript)
    voice_pipeline.action_feedback.connect(hud.update_action)
    
    # Start background voice pipeline
    voice_pipeline.start()

    # Initialize Tray Daemon
    tray = MXBTray(hud, voice_pipeline)
    tray.show()

    # Initialize Global Controls & Safety
    hotkeys = GlobalHotkeyListener(config, voice_pipeline)
    hotkeys.start()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
