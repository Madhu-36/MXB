import keyboard
import traceback
from PySide6.QtWidgets import QMessageBox
from utils.logger import log

class GlobalHotkeyListener:
    def __init__(self, config, voice_pipeline):
        self.config = config
        self.voice_pipeline = voice_pipeline
        self.ptt_hotkey = config.get("hotkeys", {}).get("push_to_talk", "ctrl+space")
        self.kill_hotkey = config.get("hotkeys", {}).get("kill_switch", "ctrl+alt+k")
        self.is_muted = False

    def start(self):
        try:
            log.info("Hotkeys: Registering global keyboard hooks...")
            keyboard.add_hotkey(self.kill_hotkey, self._emergency_kill)
            keyboard.add_hotkey(self.ptt_hotkey, self._toggle_mute)
            log.info(f"Hotkeys: Registered Kill={self.kill_hotkey}, Toggle Mute={self.ptt_hotkey}")
        except Exception as e:
            log.warning(f"Hotkeys: Global hook registration notice: {e}")

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.voice_pipeline.pause_listening()
        else:
            self.voice_pipeline.resume_listening()

    def _emergency_kill(self):
        log.warning("Hotkeys: EMERGENCY KILL ACTIVATED! Halting voice processing.")
        self.voice_pipeline.pause_listening()
        self.is_muted = True
        self.voice_pipeline.action_feedback.emit("KILL-SWITCH ACTIVATED. ALL ACTIONS HALTED.")

    def request_destructive_action(self, action_description: str) -> bool:
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("MXB Action Confirmation")
        dialog.setText(f"MXB wants to perform a high-impact action:\n\n{action_description}")
        dialog.setInformativeText("Allow this execution?")
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec() == QMessageBox.Yes
