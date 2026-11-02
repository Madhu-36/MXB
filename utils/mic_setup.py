import sys
import os
import json
import time
from pathlib import Path
import numpy as np
import sounddevice as sd

CONFIG_PATH = Path(__file__).parent.parent / 'config.json'

def load_config():
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, 'r') as f:
            return json.load(f)
    return {}

def save_config(cfg):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(cfg, f, indent=2)

def list_microphones():
    devs = sd.query_devices()
    valid = []
    seen = set()
    for i, d in enumerate(devs):
        if d['max_input_channels'] > 0:
            name = d['name']
            api = d['hostapi']
            # Dedup same name & hostapi
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
    print(">>> SPEAK NOW to test your voice level! <<<\n")
    
    rms_levels = []
    peak_levels = []
    
    bar_width = 35
    start_time = time.time()
    
    def cb(indata, frames, time_info, status):
        raw = indata.flatten()
        rms = float(np.sqrt(np.mean(raw**2)))
        peak = float(np.max(np.abs(raw)))
        rms_levels.append(rms)
        peak_levels.append(peak)
        
        # Display live bar
        fill = int(min(rms * 1500, bar_width))
        bar = "#" * fill + "-" * (bar_width - fill)
        status_tag = "[SPEECH]" if rms > 0.0008 else "[AMBIENT]"
        try:
            sys.stdout.write(f"\rLevel: [{bar}] RMS: {rms:.6f} {status_tag} ")
            sys.stdout.flush()
        except Exception:
            pass

    try:
        with sd.InputStream(samplerate=rate, channels=ch, device=dev_index, dtype='float32', blocksize=512, callback=cb):
            time.sleep(duration_sec)
        print("\n\nTest Finished!")
    except Exception as e:
        print(f"\nError opening microphone: {e}")
        return None

    if not rms_levels:
        return None

    avg_rms = float(np.mean(rms_levels))
    max_peak = float(np.max(peak_levels))
    max_rms = float(np.max(rms_levels))
    
    print("-" * 50)
    print(f"Average Level: {avg_rms:.6f}")
    print(f"Max Speech RMS: {max_rms:.6f}")
    print(f"Max Peak Volume: {max_peak:.6f}")
    print("-" * 50)
    
    if max_rms < 0.0005:
        print("[ADVICE] Very low audio signal detected. Recommended sensitivity: HIGH.")
    elif max_rms < 0.003:
        print("[ADVICE] Moderate audio signal detected. Recommended sensitivity: HIGH or MEDIUM.")
    else:
        print("[ADVICE] Strong audio signal detected! Your microphone is working great.")
        
    return {"avg_rms": avg_rms, "max_rms": max_rms, "max_peak": max_peak}

def main():
    print("=" * 60)
    print("MXB MICROPHONE SETUP & CALIBRATION TOOL")
    print("=" * 60)
    
    cfg = load_config()
    current_dev = cfg.get("audio_input_device", "auto")
    current_sens = cfg.get("engine", {}).get("microphone_sensitivity", "high")
    
    print(f"Current Config Device: {current_dev}")
    print(f"Current Sensitivity:   {current_sens.upper()}")
    print("-" * 60)
    
    devices = list_microphones()
    print("Available Microphones on your system:")
    print("  [A] Auto-Select (Prioritize Bluetooth Headset if connected, else Realtek)")
    for idx, (dev_id, d) in enumerate(devices):
        api_name = ["MME", "DirectSound", "WASAPI", "WDM-KS"][d['hostapi']] if d['hostapi'] < 4 else f"API-{d['hostapi']}"
        print(f"  [{idx + 1}] {d['name']} ({api_name}) [ID: {dev_id}]")
        
    print("\nSelect an option to test and configure (or press Enter for Auto): ", end="")
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
    elif choice.lower() == "a" or choice == "":
        chosen_dev_name = "auto"
        # Find default or headset
        for dev_id, d in devices:
            if any(k in d['name'].lower() for k in ["noise", "airwave", "headset"]):
                test_id = dev_id
                break

    # Run 5-second test
    res = test_microphone_level(test_id, duration_sec=5)
    
    # Update config
    cfg["audio_input_device"] = chosen_dev_name
    if "engine" not in cfg:
        cfg["engine"] = {}
    cfg["engine"]["microphone_sensitivity"] = "high"
    save_config(cfg)
    
    print("\nSaved settings to config.json!")
    print(f"  Device:      {chosen_dev_name}")
    print(f"  Sensitivity: HIGH (0.00035 trigger threshold + AGC enabled)")
    print("=" * 60)
    print("MXB is now calibrated to catch your words perfectly!")

if __name__ == "__main__":
    main()
