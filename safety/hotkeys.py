import keyboard
import traceback
from PySide6.QtWidgets import QMessageBox

class GlobalHotkeyListener:
    def __init__(self, config, voice_pipeline):
        self.config = config
        self.voice_pipeline = voice_pipeline
        self.ptt_hotkey = config.get("hotkeys", {}).get("push_to_talk", "ctrl+space")
        self.kill_hotkey = config.get("hotkeys", {}).get("kill_switch", "ctrl+alt+k")
        
        self.is_muted = False

    def start(self):
        try:
            print("[Hotkeys] Attempting to register global hooks...")
            keyboard.add_hotkey(self.kill_hotkey, self._emergency_kill)
            keyboard.add_hotkey(self.ptt_hotkey, self._toggle_mute)
            print(f"[Hotkeys] Successfully registered: Kill={self.kill_hotkey}, Toggle Mute={self.ptt_hotkey}")
        except Exception as e:
            print(f"[Hotkeys] Warning: Failed to register global hotkeys: {e}")
            print("[Hotkeys] MXB will still work normally, but hotkeys require Administrator privileges on Windows!")
            traceback.print_exc()

    def _toggle_mute(self):
        self.is_muted = not self.is_muted
        if self.is_muted:
            self.voice_pipeline.pause_listening()
        else:
            self.voice_pipeline.resume_listening()

    def _emergency_kill(self):
        print("[Hotkeys] EMERGENCY KILL ACTIVATED!")
        self.voice_pipeline.pause_listening()
        self.is_muted = True
        self.voice_pipeline.action_feedback.emit("KILL-SWITCH ACTIVATED. ALL ACTIONS HALTED.")

    def request_destructive_action(self, action_description: str) -> bool:
        dialog = QMessageBox()
        dialog.setIcon(QMessageBox.Warning)
        dialog.setWindowTitle("Action Confirmation")
        dialog.setText(f"MXB wants to perform a destructive action:\n\n{action_description}")
        dialog.setInformativeText("Allow this?")
        dialog.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        dialog.setDefaultButton(QMessageBox.No)
        return dialog.exec() == QMessageBox.Yes
