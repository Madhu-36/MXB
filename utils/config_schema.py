import json
from pathlib import Path
from typing import Any, Dict, Tuple

class ConfigSchema:
    """
    Schema validator and defaults manager for MXB configuration.
    Ensures safe initialization even if config.json is partially corrupted or missing keys.
    """

    DEFAULTS: Dict[str, Any] = {
        "audio_input_device": "auto",
        "hotkeys": {
            "push_to_talk": "ctrl+space",
            "kill_switch": "ctrl+alt+k"
        },
        "speech_recognition": {
            "provider": "nvidia",
            "model": "nvidia/parakeet-tdt-0.6b",
            "api_url": "https://integrate.api.nvidia.com/v1/audio/transcriptions"
        },
        "llm": {
            "provider": "nvidia",
            "model": "meta/llama-3.1-8b-instruct",
            "api_url": "https://integrate.api.nvidia.com/v1/chat/completions",
            "local_model": "llama3.2:1b"
        },
        "engine": {
            "whisper_model": "base.en",
            "microphone_sensitivity": "high",
            "vad_speech_prob_threshold": 0.35,
            "agc_target_level": 0.85,
            "max_gain": 60.0
        }
    }

    @classmethod
    def validate(cls, config: Dict[str, Any]) -> Tuple[bool, Dict[str, Any], list[str]]:
        """
        Validates config dict against schema. Fills in missing keys with defaults.
        Returns (is_valid, validated_config, warning_messages).
        """
        validated = {}
        warnings = []

        if not isinstance(config, dict):
            return False, cls.DEFAULTS.copy(), ["Config root must be a dictionary."]

        # 1. Audio input device
        validated["audio_input_device"] = config.get("audio_input_device", cls.DEFAULTS["audio_input_device"])

        # 2. Hotkeys
        user_hotkeys = config.get("hotkeys", {})
        if not isinstance(user_hotkeys, dict):
            warnings.append("Invalid 'hotkeys' block. Using defaults.")
            user_hotkeys = {}
        validated["hotkeys"] = {
            "push_to_talk": user_hotkeys.get("push_to_talk", cls.DEFAULTS["hotkeys"]["push_to_talk"]),
            "kill_switch": user_hotkeys.get("kill_switch", cls.DEFAULTS["hotkeys"]["kill_switch"])
        }

        # 3. Speech recognition
        user_sr = config.get("speech_recognition", {})
        if not isinstance(user_sr, dict):
            warnings.append("Invalid 'speech_recognition' block. Using defaults.")
            user_sr = {}
        validated["speech_recognition"] = {
            "provider": user_sr.get("provider", cls.DEFAULTS["speech_recognition"]["provider"]),
            "model": user_sr.get("model", cls.DEFAULTS["speech_recognition"]["model"]),
            "api_url": user_sr.get("api_url", cls.DEFAULTS["speech_recognition"]["api_url"])
        }

        # 4. LLM
        user_llm = config.get("llm", {})
        if not isinstance(user_llm, dict):
            warnings.append("Invalid 'llm' block. Using defaults.")
            user_llm = {}
        validated["llm"] = {
            "provider": user_llm.get("provider", cls.DEFAULTS["llm"]["provider"]),
            "model": user_llm.get("model", cls.DEFAULTS["llm"]["model"]),
            "api_url": user_llm.get("api_url", cls.DEFAULTS["llm"]["api_url"]),
            "local_model": user_llm.get("local_model", cls.DEFAULTS["llm"]["local_model"])
        }

        # 5. Engine parameters
        user_engine = config.get("engine", {})
        if not isinstance(user_engine, dict):
            warnings.append("Invalid 'engine' block. Using defaults.")
            user_engine = {}
        
        # Enforce range limits on VAD & AGC
        vad_thresh = float(user_engine.get("vad_speech_prob_threshold", cls.DEFAULTS["engine"]["vad_speech_prob_threshold"]))
        vad_thresh = max(0.05, min(0.95, vad_thresh))

        agc_target = float(user_engine.get("agc_target_level", cls.DEFAULTS["engine"]["agc_target_level"]))
        agc_target = max(0.1, min(1.0, agc_target))

        max_gain = float(user_engine.get("max_gain", cls.DEFAULTS["engine"]["max_gain"]))
        max_gain = max(1.0, min(100.0, max_gain))

        validated["engine"] = {
            "whisper_model": user_engine.get("whisper_model", cls.DEFAULTS["engine"]["whisper_model"]),
            "microphone_sensitivity": user_engine.get("microphone_sensitivity", cls.DEFAULTS["engine"]["microphone_sensitivity"]),
            "vad_speech_prob_threshold": vad_thresh,
            "agc_target_level": agc_target,
            "max_gain": max_gain
        }

        # 6. MXB v3 blocks and any extra keys pass through untouched (validated blocks win),
        #    so exporting/importing settings never silently drops companion settings.
        for key, value in config.items():
            if key not in validated:
                validated[key] = value
        for block in ("hotkeys", "llm", "speech_recognition", "engine"):
            extra = config.get(block)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    validated[block].setdefault(k, v)

        return len(warnings) == 0, validated, warnings

    @classmethod
    def export_to_file(cls, config: Dict[str, Any], file_path: str) -> bool:
        """Exports validated config to designated file path."""
        try:
            _, validated, _ = cls.validate(config)
            dest = Path(file_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(validated, f, indent=2)
            return True
        except Exception:
            return False

    @classmethod
    def import_from_file(cls, file_path: str) -> Tuple[bool, Dict[str, Any], list[str]]:
        """Imports and validates configuration from an external JSON file."""
        src = Path(file_path)
        if not src.exists() or not src.is_file():
            return False, cls.DEFAULTS.copy(), [f"File does not exist: {file_path}"]
        try:
            with open(src, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
            return cls.validate(raw_data)
        except Exception as e:
            return False, cls.DEFAULTS.copy(), [f"Failed to parse JSON: {e}"]
