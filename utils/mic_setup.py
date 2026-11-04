import sys
import os
import json
import time
from pathlib import Path
import numpy as np
import sounddevice as sd
from faster_whisper.vad import get_vad_model

CONFIG_PATH = Path(__file__).parent.parent / 'config.json'

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, indent=2)

def list_microphones():
    devs = sd.query_devices()
    valid = []
    seen = set()
    for i, d in enumerate(devs):
        if d['max_input_channels'] > 0:
            name = d['name']
            api = d['hostapi']
            key = (name, api)
            if key in seen:
                continue
            seen.add(key)
            valid.append((i, d))
    return valid

def test_microphone_level(dev_index, duration_sec=5):
    dev_info = sd.query_devices(dev_index)
    rate = int(dev_info['default_samplerate'])
    ch = min(1, dev_info['max_input_channels'])

    print(f"\nTesting Microphone: {dev_info['name']}")
    print(f"Sample Rate: {rate} Hz | Testing for {duration_sec} seconds...")
    print(">>> SPEAK NOW into your microphone to calibrate Neural VAD! <<<\n")

    vad_model = get_vad_model()
    rms_levels = []
    speech_probs = []

    bar_width = 30

    def cb(indata, frames, time_info, status):
        raw = indata.flatten()
        if len(raw) != 512:
            raw = np.resize(raw, 512).astype(np.float32)

        rms = float(np.sqrt(np.mean(raw**2)))
        rms_levels.append(rms)

        # Silero VAD probability
        try:
            prob = float(vad_model(raw)[0])
        except Exception:
            prob = 0.0
        speech_probs.append(prob)

        fill = int(min(prob * bar_width, bar_width))
        bar = "#" * fill + "-" * (bar_width - fill)
        status_tag = "[SPEECH DETECTED]" if prob > 0.40 else "[SILENCE/AMBIENT]"

        try:
            sys.stdout.write(f"\rProb: [{bar}] {prob*100:5.1f}% | RMS: {rms:.6f} {status_tag}   ")
            sys.stdout.flush()
        except Exception:
            pass

    try:
        with sd.InputStream(samplerate=16000, channels=ch, device=dev_index, dtype='float32', blocksize=512, callback=cb):
            time.sleep(duration_sec)
        print("\n\nTest Finished!")
    except Exception as e:
        print(f"\nError opening microphone: {e}")
        return None

    if not rms_levels:
        return None

    avg_rms = float(np.mean(rms_levels))
    max_prob = float(np.max(speech_probs))

    print("-" * 55)
    print(f"Average Ambient RMS:    {avg_rms:.6f}")
    print(f"Max Speech Probability: {max_prob * 100:.1f}%")
    print("-" * 55)

    if max_prob > 0.60:
        print("[RESULT] EXCELLENT! Neural VAD detected your voice clearly.")
    elif max_prob > 0.30:
        print("[RESULT] GOOD! Moderate voice signal detected. AGC will boost gain.")
    else:
        print("[RESULT] WEAK. Speak closer to the microphone or verify Windows mic input volume in Settings.")

    return {"avg_rms": avg_rms, "max_prob": max_prob}

def main():
    print("=" * 60)
    print("MXB v2.0 NEURAL MICROPHONE CALIBRATION TOOL")
    print("=" * 60)

    cfg = load_config()
    current_dev = cfg.get("audio_input_device", "auto")
    print(f"Current Device Setting: {current_dev}\n")

    devices = list_microphones()
    print("Available Microphones:")
    print("  [A] Auto-Select (Default / Bluetooth / Realtek)")
    for idx, (dev_id, d) in enumerate(devices):
        api_name = ["MME", "DirectSound", "WASAPI", "WDM-KS"][d['hostapi']] if d['hostapi'] < 4 else f"API-{d['hostapi']}"
        print(f"  [{idx + 1}] {d['name']} ({api_name}) [ID: {dev_id}]")

    print("\nSelect an option to test (or Enter for Auto): ", end="")
    try:
        choice = input().strip()
    except EOFError:
        choice = ""

    chosen_dev_name = "auto"
    test_id = sd.default.device[0]

    if choice.isdigit() and 1 <= int(choice) <= len(devices):
        selected_tuple = devices[int(choice) - 1]
        test_id = selected_tuple[0]
        chosen_dev_name = selected_tuple[1]['name']

    test_microphone_level(test_id, duration_sec=5)

    cfg["audio_input_device"] = chosen_dev_name
    if "engine" not in cfg:
        cfg["engine"] = {}
    cfg["engine"]["microphone_sensitivity"] = "high"
    save_config(cfg)
    print("\nSaved configuration to config.json!")

if __name__ == "__main__":
    main()
