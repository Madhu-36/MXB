"""
First-run setup wizard (also available from the tray: "Run Setup Wizard").

Pages: Welcome -> Microphone (pick + test) -> AI brain (NVIDIA key and/or Ollama) ->
Voice & listening (TTS engine, voice, wake word) -> Finish (start with Windows, updates).

All system probes are injectable (WizardProbes) so the wizard is unit-tested headless.
"""
import os
import threading
from PySide6.QtCore import Signal, QObject
from PySide6.QtWidgets import (
    QWizard, QWizardPage, QLabel, QVBoxLayout, QFormLayout, QComboBox, QPushButton, QProgressBar, QLineEdit,
    QCheckBox, QHBoxLayout,
)
from utils.paths import load_config, save_config, data_dir

EDGE_VOICES = [
    ("Neerja — Indian English, female", "en-IN-NeerjaNeural"),
    ("Prabhat — Indian English, male", "en-IN-PrabhatNeural"),
    ("Aria — US English, female", "en-US-AriaNeural"),
    ("Guy — US English, male", "en-US-GuyNeural"),
    ("Sonia — British English, female", "en-GB-SoniaNeural"),
]


class WizardProbes:
    """Real system checks. Tests pass a fake with the same methods."""

    def input_devices(self) -> list[str]:
        try:
            import sounddevice as sd
            names = []
            for d in sd.query_devices():
                if d.get("max_input_channels", 0) > 0 and d["name"] not in names:
                    names.append(d["name"])
            return names
        except Exception:
            return []

    def test_microphone(self, device_name: str, seconds: float = 1.5) -> float:
        import numpy as np
        import sounddevice as sd
        device = None
        if device_name and device_name != "auto":
            for i, d in enumerate(sd.query_devices()):
                if d["name"] == device_name and d.get("max_input_channels", 0) > 0:
                    device = i
                    break
        audio = sd.rec(int(16000 * seconds), samplerate=16000, channels=1, dtype="float32", device=device)
        sd.wait()
        return float(np.max(np.abs(audio))) if audio.size else 0.0

    def check_nvidia(self, key: str) -> tuple[bool, str]:
        import requests
        if not key.strip():
            return False, "No key entered."
        try:
            r = requests.get("https://integrate.api.nvidia.com/v1/models", timeout=8,
                             headers={"Authorization": f"Bearer {key.strip()}"})
            return (r.status_code == 200, "Key works." if r.status_code == 200 else f"NVIDIA said {r.status_code}.")
        except Exception as e:
            return False, f"Couldn't reach NVIDIA: {e}"

    def check_ollama(self) -> tuple[bool, list[str]]:
        import requests
        try:
            r = requests.get("http://localhost:11434/api/tags", timeout=3)
            models = [m.get("name", "") for m in r.json().get("models", [])] if r.status_code == 200 else []
            return r.status_code == 200, models
        except Exception:
            return False, []

    def speak_sample(self, engine: str, voice: str):
        from engine.tts import VoiceSynthesizer
        tts = VoiceSynthesizer({"tts_engine": engine, "edge_voice": voice})
        tts.speak("Hi, I'm MXB. This is how I'll sound.")
        return tts


class _Bridge(QObject):
    done = Signal(str, object)   # (kind, payload) from worker threads back to the GUI thread


def _page(title: str, subtitle: str = "") -> QWizardPage:
    page = QWizardPage()
    page.setTitle(title)
    if subtitle:
        page.setSubTitle(subtitle)
    return page


class SetupWizard(QWizard):
    def __init__(self, config: dict | None = None, probes: WizardProbes | None = None, autostart=None, parent=None):
        super().__init__(parent)
        self.config = dict(config if config is not None else load_config())
        self.probes = probes or WizardProbes()
        self.autostart = autostart        # module-like object with enable()/disable(); None -> utils.autostart
        self.saved_key = ""
        self._bridge = _Bridge()
        self._bridge.done.connect(self._on_probe_done)
        self._sample_tts = None
        self.setWindowTitle("MXB Setup")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setMinimumSize(560, 460)
        self.addPage(self._welcome_page())
        self.addPage(self._mic_page())
        self.addPage(self._brain_page())
        self.addPage(self._voice_page())
        self.addPage(self._finish_page())
        self.finished.connect(self._on_finished)

    # ------------------------------------------------------------------ pages
    def _welcome_page(self):
        page = _page("Welcome to MXB", "Your voice + text desktop companion.")
        lay = QVBoxLayout(page)
        text = QLabel(
            "MXB can open apps, click and type for you, manage files, control Bluetooth, Wi-Fi, volume and "
            "brightness, remember your preferences, answer from your documents, and run routines.\n\n"
            "Your safety rules, always on:\n"
            "• It asks before deleting, shutting down, overwriting or installing anything.\n"
            "• It only uses your personal folders until you grant more.\n"
            "• Say \"stop\" or press Ctrl+Alt+K at any time.\n"
            "• Memory, documents and logs stay on this PC.")
        text.setWordWrap(True)
        lay.addWidget(text)
        return page

    def _mic_page(self):
        page = _page("Microphone", "Pick the mic MXB should listen to, then test it.")
        form = QFormLayout(page)
        self.mic_combo = QComboBox()
        self.mic_combo.addItem("Auto-detect (headset first)", "auto")
        for name in self.probes.input_devices():
            self.mic_combo.addItem(name, name)
        current = self.config.get("audio_input_device", "auto")
        idx = self.mic_combo.findData(current)
        self.mic_combo.setCurrentIndex(idx if idx >= 0 else 0)
        row = QHBoxLayout()
        self.mic_test = QPushButton("Test (say something)")
        self.mic_level = QProgressBar()
        self.mic_level.setRange(0, 100)
        self.mic_status = QLabel("")
        row.addWidget(self.mic_test)
        row.addWidget(self.mic_level, 1)
        self.mic_test.clicked.connect(self._test_mic)
        form.addRow("Microphone:", self.mic_combo)
        form.addRow(row)
        form.addRow(self.mic_status)
        return page

    def _brain_page(self):
        page = _page("AI brain", "Cloud (NVIDIA, fastest and smartest) and/or local (Ollama, private). One is enough.")
        form = QFormLayout(page)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setPlaceholderText("nvapi-… (free key from build.nvidia.com)")
        self.key_check = QPushButton("Check key")
        self.key_status = QLabel("")
        self.key_check.clicked.connect(self._check_key)
        self.ollama_combo = QComboBox()
        self.ollama_status = QLabel("Looking for Ollama…")
        ok, models = self.probes.check_ollama()
        local = self.config.get("llm", {}).get("local_model", "llama3.2:1b")
        if ok and models:
            for m in models:
                self.ollama_combo.addItem(m, m)
            idx = self.ollama_combo.findData(local)
            self.ollama_combo.setCurrentIndex(idx if idx >= 0 else 0)
            self.ollama_status.setText(f"Ollama is running with {len(models)} model(s).")
        else:
            self.ollama_combo.addItem(local, local)
            self.ollama_status.setText("Ollama not found. Optional: install it from ollama.com for a private local brain.")
        key_row = QHBoxLayout()
        key_row.addWidget(self.key_edit, 1)
        key_row.addWidget(self.key_check)
        form.addRow("NVIDIA API key:", key_row)
        form.addRow(self.key_status)
        form.addRow("Local model:", self.ollama_combo)
        form.addRow(self.ollama_status)
        return page

    def _voice_page(self):
        page = _page("Voice and listening")
        form = QFormLayout(page)
        voice_cfg = self.config.get("voice", {})
        listen_cfg = self.config.get("listening", {})
        self.engine_combo = QComboBox()
        for label, value in [("Auto (natural neural voice when online)", "auto"), ("Neural voice (edge-tts, online)", "edge"),
                             ("Offline neural voice (Piper)", "piper"), ("Windows voice (offline)", "sapi")]:
            self.engine_combo.addItem(label, value)
        self.engine_combo.setCurrentIndex(max(0, self.engine_combo.findData(voice_cfg.get("tts_engine", "auto"))))
        self.voice_combo = QComboBox()
        for label, value in EDGE_VOICES:
            self.voice_combo.addItem(label, value)
        self.voice_combo.setCurrentIndex(max(0, self.voice_combo.findData(voice_cfg.get("edge_voice", "en-IN-NeerjaNeural"))))
        self.sample_button = QPushButton("Play sample")
        self.sample_button.clicked.connect(self._play_sample)
        self.wake_edit = QLineEdit(", ".join(listen_cfg.get("wake_words", ["mxb"])[:3]))
        self.always_check = QCheckBox("Act on everything I say, without a wake word (only in a quiet room)")
        self.always_check.setChecked(listen_cfg.get("mode") == "always")
        form.addRow("Speech engine:", self.engine_combo)
        form.addRow("Voice:", self.voice_combo)
        form.addRow(self.sample_button)
        form.addRow("Wake word(s):", self.wake_edit)
        form.addRow(self.always_check)
        return page

    def _finish_page(self):
        page = _page("All set", "You can change any of this later in Settings or by running this wizard again from the tray.")
        lay = QVBoxLayout(page)
        self.autostart_check = QCheckBox("Start MXB when I sign in to Windows")
        self.autostart_check.setChecked(bool(self.config.get("ui", {}).get("start_with_windows", False)))
        self.chat_check = QCheckBox("Open the chat window when MXB starts")
        self.chat_check.setChecked(bool(self.config.get("ui", {}).get("open_chat_on_start", True)))
        self.updates_check = QCheckBox("Check for updates once a day (installs only when you say yes)")
        self.updates_check.setChecked(bool(self.config.get("update", {}).get("check_on_start", True)))
        tips = QLabel("Try: \"MXB, open notepad\" · \"show numbers\" then \"click 3\" · \"remind me in 10 minutes to stretch\"")
        tips.setWordWrap(True)
        for w in (self.autostart_check, self.chat_check, self.updates_check, tips):
            lay.addWidget(w)
        return page

    # ------------------------------------------------------------------ probes (threaded)
    def _test_mic(self):
        self.mic_status.setText("Listening for 1.5 s…")
        device = self.mic_combo.currentData()
        threading.Thread(target=lambda: self._bridge.done.emit("mic", self._safe(self.probes.test_microphone, device)),
                         daemon=True).start()

    def _check_key(self):
        self.key_status.setText("Checking…")
        key = self.key_edit.text()
        threading.Thread(target=lambda: self._bridge.done.emit("key", self._safe(self.probes.check_nvidia, key)),
                         daemon=True).start()

    def _play_sample(self):
        try:
            self._sample_tts = self.probes.speak_sample(self.engine_combo.currentData(), self.voice_combo.currentData())
        except Exception as e:
            self.sample_button.setText(f"Sample failed: {e}"[:60])

    @staticmethod
    def _safe(fn, *args):
        try:
            return fn(*args)
        except Exception as e:
            return e

    def _on_probe_done(self, kind: str, payload):
        if kind == "mic":
            if isinstance(payload, Exception):
                self.mic_status.setText(f"Mic test failed: {payload}")
                return
            level = int(min(1.0, payload * 4) * 100)
            self.mic_level.setValue(level)
            self.mic_status.setText("Great, I can hear you." if level >= 8 else
                                    "Very quiet. Speak up, pick another mic, or raise its level in Windows Sound settings.")
        elif kind == "key":
            if isinstance(payload, Exception):
                self.key_status.setText(f"Check failed: {payload}")
            else:
                ok, msg = payload
                self.key_status.setText(("✓ " if ok else "✗ ") + msg)

    # ------------------------------------------------------------------ result
    def result_config(self) -> dict:
        cfg = dict(self.config)
        cfg["audio_input_device"] = self.mic_combo.currentData() or "auto"
        cfg.setdefault("llm", {})["local_model"] = self.ollama_combo.currentData()
        voice = cfg.setdefault("voice", {})
        voice["tts_engine"] = self.engine_combo.currentData()
        voice["edge_voice"] = self.voice_combo.currentData()
        listen = cfg.setdefault("listening", {})
        words = [w.strip().lower() for w in self.wake_edit.text().split(",") if w.strip()]
        listen["wake_words"] = words or ["mxb"]
        listen["mode"] = "always" if self.always_check.isChecked() else "wake_word"
        ui = cfg.setdefault("ui", {})
        ui["start_with_windows"] = self.autostart_check.isChecked()
        ui["open_chat_on_start"] = self.chat_check.isChecked()
        cfg.setdefault("update", {})["check_on_start"] = self.updates_check.isChecked()
        cfg["setup_complete"] = True
        return cfg

    def apply(self) -> dict:
        cfg = self.result_config()
        save_config(cfg)
        key = self.key_edit.text().strip()
        if key:
            self._save_key(key)
        auto = self.autostart
        if auto is None:
            from utils import autostart as auto
        try:
            (auto.enable if cfg["ui"]["start_with_windows"] else auto.disable)()
        except Exception:
            pass
        self.config = cfg
        return cfg

    def _save_key(self, key: str):
        env = data_dir() / ".env"
        lines = []
        if env.exists():
            lines = [l for l in env.read_text(encoding="utf-8").splitlines() if not l.startswith("NVIDIA_API_KEY=")]
        lines.append(f"NVIDIA_API_KEY={key}")
        env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.environ["NVIDIA_API_KEY"] = key   # usable right away, no restart needed
        self.saved_key = key

    def _on_finished(self, result: int):
        if result == QWizard.DialogCode.Accepted:
            self.apply()
        else:
            # Don't nag every launch: keep defaults, mark setup as seen.
            cfg = dict(self.config)
            cfg["setup_complete"] = True
            save_config(cfg)
