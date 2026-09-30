import json
from pathlib import Path
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QComboBox, QFormLayout
from PySide6.QtCore import Qt

class SettingsDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MXB Settings Dashboard")
        self.resize(400, 300)

        # Load config directly from file
        self.config_path = Path(__file__).parent.parent / 'config.json'
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)

        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # Audio Device
        self.audio_combo = QComboBox()
        self.audio_combo.addItems(["Default System Microphone"])
        form_layout.addRow("Audio Input:", self.audio_combo)

        # Model Selection
        self.model_combo = QComboBox()
        self.model_combo.addItems(["mxb-brain", "llama3", "mistral"])
        self.model_combo.setCurrentText(self.config.get("llm", {}).get("model", "mxb-brain"))
        form_layout.addRow("LLM Model:", self.model_combo)

        # Hotkey Configuration
        self.ptt_hotkey = QLineEdit(self.config.get("hotkeys", {}).get("push_to_talk", "ctrl+space"))
        form_layout.addRow("Push-to-Talk Hotkey:", self.ptt_hotkey)

        self.kill_hotkey = QLineEdit(self.config.get("hotkeys", {}).get("kill_switch", "ctrl+alt+k"))
        form_layout.addRow("Kill-Switch Hotkey:", self.kill_hotkey)

        layout.addLayout(form_layout)

        # Save Button
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_btn)

        self.setLayout(layout)

    def save_settings(self):
        # Update config dictionary
        self.config["llm"]["model"] = self.model_combo.currentText()
        self.config["hotkeys"]["push_to_talk"] = self.ptt_hotkey.text()
        self.config["hotkeys"]["kill_switch"] = self.kill_hotkey.text()
        
        # Write back to config.json
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
            
        print("Settings saved successfully.")
        self.close()
