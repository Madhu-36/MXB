import os
import json
import sounddevice as sd
from pathlib import Path
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, 
    QComboBox, QFormLayout, QProgressBar, QHBoxLayout
)
from PySide6.QtCore import Qt, QTimer
import numpy as np
from utils.credentials import CredentialsManager

class SettingsDashboard(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MXB Settings & Microphone Dashboard")
        self.resize(480, 480)

        # Load config directly from file
        self.config_path = Path(__file__).parent.parent / 'config.json'
        with open(self.config_path, 'r') as f:
            self.config = json.load(f)

        layout = QVBoxLayout()
        form_layout = QFormLayout()

        # NVIDIA API Key (Protected Password Echo)
        self.nv_key_input = QLineEdit()
        self.nv_key_input.setEchoMode(QLineEdit.PasswordEchoOnEdit)
        self.nv_key_input.setPlaceholderText("nvapi-...")
        current_nv_key = CredentialsManager.get_nvidia_api_key()
        if current_nv_key:
            self.nv_key_input.setText(current_nv_key)
        form_layout.addRow("NVIDIA Build API Key:", self.nv_key_input)

        # Audio Device Selector
        self.audio_combo = QComboBox()
        self.audio_combo.addItem("Auto-Detect (Headset if connected, else Built-in Mic)", "auto")
        
        devs = sd.query_devices()
        seen = set()
        for i, d in enumerate(devs):
            if d['max_input_channels'] > 0:
                name = d['name']
                if name not in seen:
                    seen.add(name)
                    self.audio_combo.addItem(name, name)
                    
        current_dev = self.config.get("audio_input_device", "auto")
        for i in range(self.audio_combo.count()):
            if current_dev.lower() in self.audio_combo.itemText(i).lower():
                self.audio_combo.setCurrentIndex(i)
                break
                
        form_layout.addRow("Microphone Device:", self.audio_combo)

        # Microphone Sensitivity
        self.sens_combo = QComboBox()
        self.sens_combo.addItem("High Sensitivity (Recommended for laptop mics / quiet speech)", "high")
        self.sens_combo.addItem("Medium Sensitivity (Balanced)", "medium")
        self.sens_combo.addItem("Low Sensitivity (Noisy rooms)", "low")
        
        current_sens = self.config.get("engine", {}).get("microphone_sensitivity", "high")
        for i in range(self.sens_combo.count()):
            if self.sens_combo.itemData(i) == current_sens:
                self.sens_combo.setCurrentIndex(i)
                break
                
        form_layout.addRow("Voice Sensitivity:", self.sens_combo)

        # Model Selection
        self.model_combo = QComboBox()
        self.model_combo.addItems(["meta/llama-3.1-8b-instruct (NVIDIA Cloud)", "mxb-brain (Local Ollama)"])
        form_layout.addRow("Speech Understanding Model:", self.model_combo)

        # Hotkey Configuration
        self.ptt_hotkey = QLineEdit(self.config.get("hotkeys", {}).get("push_to_talk", "ctrl+space"))
        form_layout.addRow("Toggle Mute Hotkey:", self.ptt_hotkey)

        self.kill_hotkey = QLineEdit(self.config.get("hotkeys", {}).get("kill_switch", "ctrl+alt+k"))
        form_layout.addRow("Emergency Stop Hotkey:", self.kill_hotkey)

        layout.addLayout(form_layout)

        # Live Volume Meter
        meter_label = QLabel("Microphone Level Monitor:")
        meter_label.setStyleSheet("font-weight: bold; margin-top: 10px;")
        layout.addWidget(meter_label)

        self.level_bar = QProgressBar()
        self.level_bar.setRange(0, 100)
        self.level_bar.setValue(0)
        self.level_bar.setStyleSheet("""
            QProgressBar {
                border: 1px solid #444;
                border-radius: 5px;
                text-align: center;
                height: 18px;
            }
            QProgressBar::chunk {
                background-color: #00E5FF;
                border-radius: 4px;
            }
        """)
        layout.addWidget(self.level_bar)

        self.level_status = QLabel("Speak into your microphone to test level.")
        self.level_status.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(self.level_status)

        # Live Test Timer & Stream
        self.test_stream = None
        self.test_timer = QTimer(self)
        self.test_timer.timeout.connect(self._update_meter)
        self._start_level_test()

        # Save Button
        self.save_btn = QPushButton("Save Settings")
        self.save_btn.setStyleSheet("background-color: #00E5FF; color: #000; font-weight: bold; padding: 8px; border-radius: 5px;")
        self.save_btn.clicked.connect(self.save_settings)
        layout.addWidget(self.save_btn)

        self.setLayout(layout)

    def _start_level_test(self):
        try:
            self.test_stream = sd.InputStream(samplerate=16000, channels=1, dtype='float32', blocksize=512)
            self.test_stream.start()
            self.test_timer.start(50)
        except Exception:
            pass

    def _update_meter(self):
        if not self.test_stream:
            return
        try:
            avail = self.test_stream.read_available
            if avail > 0:
                data, _ = self.test_stream.read(min(avail, 512))
                rms = float(np.sqrt(np.mean(data**2)))
                pct = int(min(rms / 0.005 * 100.0, 100))
                self.level_bar.setValue(pct)
                if pct > 15:
                    self.level_status.setText(f"Voice Detected! (RMS: {rms:.5f})")
                    self.level_status.setStyleSheet("color: #00FF88; font-size: 11px;")
                else:
                    self.level_status.setText(f"Ambient Level: {rms:.5f}")
                    self.level_status.setStyleSheet("color: #888; font-size: 11px;")
        except Exception:
            pass

    def closeEvent(self, event):
        self.test_timer.stop()
        if self.test_stream:
            try:
                self.test_stream.stop()
                self.test_stream.close()
            except Exception:
                pass
        super().closeEvent(event)

    def save_settings(self):
        # Update config dictionary
        selected_dev = self.audio_combo.currentData()
        if not selected_dev:
            selected_dev = "auto"
        self.config["audio_input_device"] = selected_dev
        
        if "engine" not in self.config:
            self.config["engine"] = {}
        self.config["engine"]["microphone_sensitivity"] = self.sens_combo.currentData()
        
        self.config["hotkeys"]["push_to_talk"] = self.ptt_hotkey.text()
        self.config["hotkeys"]["kill_switch"] = self.kill_hotkey.text()

        # Save NVIDIA API Key to .env file safely
        nv_key = self.nv_key_input.text().strip()
        if nv_key:
            env_path = Path(__file__).parent.parent / '.env'
            lines = []
            if env_path.exists():
                with open(env_path, 'r') as f:
                    lines = [l for l in f if not l.strip().startswith("NVIDIA_API_KEY=")]
            lines.append(f"NVIDIA_API_KEY={nv_key}\n")
            with open(env_path, 'w') as f:
                f.writelines(lines)
            os.environ["NVIDIA_API_KEY"] = nv_key
            print("[Settings] NVIDIA API Key saved to .env securely.")

        # Write back to config.json
        with open(self.config_path, 'w') as f:
            json.dump(self.config, f, indent=2)
            
        print("[Settings] Configuration saved successfully.")
        self.close()
