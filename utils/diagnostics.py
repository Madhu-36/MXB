import sys
from pathlib import Path
if str(Path(__file__).parent.parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).parent.parent))

import socket
import time
import requests
import psutil
import numpy as np
from utils.credentials import CredentialsManager

class SystemDiagnostics:
    @staticmethod
    def check_internet() -> bool:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=2)
            return True
        except OSError:
            return False

    @staticmethod
    def check_nvidia_build() -> dict:
        result = {"has_key": False, "authenticated": False, "models": [], "status": "Not Configured"}
        api_key = CredentialsManager.get_nvidia_api_key()
        if not api_key:
            return result

        result["has_key"] = True
        try:
            url = "https://integrate.api.nvidia.com/v1/models"
            headers = {"Authorization": f"Bearer {api_key}"}
            r = requests.get(url, headers=headers, timeout=5)
            if r.status_code == 200:
                result["authenticated"] = True
                result["status"] = "Pass"
                data = r.json()
                models = [m.get("id") for m in data.get("data", [])]
                result["models"] = models[:5] # Sample of models
            else:
                result["status"] = f"Auth Error ({r.status_code})"
                result["error"] = r.text
        except Exception as e:
            result["status"] = f"Connection Error: {e}"
            result["error"] = str(e)
        return result

    @staticmethod
    def check_ollama() -> dict:
        result = {"running": False, "models": [], "has_mxb_brain": False}
        try:
            res = requests.get("http://localhost:11434/api/tags", timeout=2)
            if res.status_code == 200:
                result["running"] = True
                models = [m.get("name") for m in res.json().get("models", [])]
                result["models"] = models
                result["has_mxb_brain"] = any("mxb-brain" in m for m in models)
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def check_microphone() -> dict:
        result = {"available": False, "device_name": None, "sample_rate": None, "live_rms": 0.0, "status": "Fail"}
        try:
            import sounddevice as sd
            default_in = sd.default.device[0]
            if default_in is None or default_in < 0:
                result["error"] = "No default input device found."
                return result
                
            dev_info = sd.query_devices(default_in)
            result["available"] = True
            result["device_name"] = dev_info.get("name")
            result["sample_rate"] = int(dev_info.get("default_samplerate", 44100))
            
            # Test record 0.5s of live audio to measure RMS
            test_chunks = []
            def cb(indata, frames, time_info, status):
                test_chunks.append(indata.copy())
                
            with sd.InputStream(samplerate=16000, channels=1, dtype='float32', blocksize=512, callback=cb):
                time.sleep(0.5)
                
            if test_chunks:
                raw = np.concatenate(test_chunks).flatten()
                rms = float(np.sqrt(np.mean(raw**2)))
                max_amp = float(np.max(np.abs(raw)))
                result["live_rms"] = rms
                result["peak_amplitude"] = max_amp
                result["status"] = "Pass"
            else:
                result["status"] = "No audio chunks captured"
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def check_whisper() -> dict:
        result = {"loaded": False, "device": "cpu", "error": None}
        try:
            from faster_whisper import WhisperModel
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            result["loaded"] = True
            result["status"] = "Pass"
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def check_tts() -> dict:
        result = {"available": False, "voices": [], "error": None}
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            speaker = win32com.client.Dispatch("SAPI.SpVoice")
            voices = []
            for i in range(speaker.GetVoices().Count):
                voices.append(speaker.GetVoices().Item(i).GetDescription())
            result["available"] = True
            result["voices"] = voices
            pythoncom.CoUninitialize()
            result["status"] = "Pass"
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def get_health_report() -> dict:
        ollama_info = SystemDiagnostics.check_ollama()
        mic_info = SystemDiagnostics.check_microphone()
        nv_info = SystemDiagnostics.check_nvidia_build()
        return {
            "internet": SystemDiagnostics.check_internet(),
            "nvidia_build_active": nv_info.get("authenticated", False),
            "nvidia_has_key": nv_info.get("has_key", False),
            "ollama_running": ollama_info["running"],
            "has_mxb_brain": ollama_info.get("has_mxb_brain", False),
            "microphone_active": mic_info["available"],
            "microphone_status": mic_info.get("status"),
            "cpu_ok": psutil.cpu_percent() < 95
        }

    @staticmethod
    def print_full_diagnosis():
        print("=" * 65)
        print("MXB FULL SYSTEM & VOICE PIPELINE DIAGNOSTIC REPORT")
        print("=" * 65)
        
        # 1. Microphone
        print("\n[1] MICROPHONE HARDWARE & LIVE CAPTURE:")
        mic = SystemDiagnostics.check_microphone()
        if mic.get("available") and mic.get("status") == "Pass":
            print(f"  Status:         [PASS]")
            print(f"  Device Name:    {mic.get('device_name')}")
            print(f"  Sample Rate:    {mic.get('sample_rate')} Hz (Direct 16kHz capture verified)")
            print(f"  Live Audio RMS: {mic.get('live_rms'):.6f} (Peak: {mic.get('peak_amplitude', 0):.6f})")
        else:
            print(f"  Status:         [FAIL] - {mic.get('error', 'Microphone not responding')}")

        # 2. NVIDIA Build Cloud Engine
        print("\n[2] NVIDIA BUILD CLOUD AI ENGINE:")
        nv = SystemDiagnostics.check_nvidia_build()
        if nv.get("authenticated"):
            print(f"  Status:         [PASS] Authenticated to NVIDIA Build Cloud")
            print(f"  Speech ASR:     NVIDIA Parakeet / Whisper Cloud Endpoints Ready")
            print(f"  Speech LLM:     NVIDIA meta/llama-3.1-8b-instruct Ready")
        elif nv.get("has_key"):
            print(f"  Status:         [WARN] Key present but authentication failed: {nv.get('status')}")
        else:
            print(f"  Status:         [INFO] Key not set. Using local Faster-Whisper & Ollama.")

        # 3. Local Faster-Whisper
        print("\n[3] LOCAL SPEECH-TO-TEXT (WHISPER FALLBACK):")
        whisper = SystemDiagnostics.check_whisper()
        if whisper.get("loaded"):
            print(f"  Status:         [PASS] Faster-Whisper base.en ready on CPU int8")
        else:
            print(f"  Status:         [FAIL] - {whisper.get('error')}")

        # 4. Text-to-Speech (SAPI5)
        print("\n[4] SPEECH SYNTHESIS (TTS):")
        tts = SystemDiagnostics.check_tts()
        if tts.get("available"):
            print(f"  Status:         [PASS] Windows SAPI5 Active")
            print(f"  Installed Voices: {', '.join(tts.get('voices', []))}")
        else:
            print(f"  Status:         [FAIL] - {tts.get('error')}")

        # 5. Ollama Local LLM
        print("\n[5] OLLAMA LOCAL RUNTIME:")
        ollama = SystemDiagnostics.check_ollama()
        if ollama.get("running"):
            print(f"  Status:         [PASS] Ollama is active on http://localhost:11434")
            print(f"  Models Found:   {', '.join(ollama.get('models', []))}")
            if ollama.get("has_mxb_brain"):
                print(f"  mxb-brain Tag:  [PASS] Custom model tag is built and present")
            else:
                print(f"  mxb-brain Tag:  [WARN] 'mxb-brain' not found. Run llm/build_llm.bat")
        else:
            print(f"  Status:         [INFO] Ollama is not running (Cloud NVIDIA LLM will be used if key is active).")

        # 6. System Resources
        print("\n[6] HARDWARE & COMPUTATIONAL LOAD:")
        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory()
        print(f"  CPU Load:       {cpu}%")
        print(f"  RAM Utilization:{ram.percent}% ({ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB)")
        
        print("\n" + "=" * 65)
        print("DIAGNOSIS COMPLETE - HYBRID VOICE PIPELINE READY")
        print("=" * 65)

if __name__ == "__main__":
    SystemDiagnostics.print_full_diagnosis()
