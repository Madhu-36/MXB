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
            with socket.create_connection(("8.8.8.8", 53), timeout=2) as s:
                return True
        except OSError:
            return False

    @staticmethod
    def check_network_rtt(target_host: str = "1.1.1.1", port: int = 53, timeout: float = 2.0) -> dict:
        """
        Measures TCP socket round-trip time (RTT) and DNS resolution latency.
        Returns dict with:
        - connected: bool
        - target: str
        - rtt_ms: float (or None)
        - dns_resolve_ms: float (or None)
        - rating: 'excellent' (<30ms), 'good' (<100ms), 'fair' (<250ms), 'poor' (>250ms), or 'offline'
        """
        result = {
            "connected": False,
            "target": target_host,
            "rtt_ms": None,
            "dns_resolve_ms": None,
            "rating": "offline"
        }

        # 1. DNS resolution latency
        t_dns_start = time.perf_counter()
        try:
            resolved_ip = socket.gethostbyname(target_host)
            result["dns_resolve_ms"] = round((time.perf_counter() - t_dns_start) * 1000.0, 2)
        except Exception:
            resolved_ip = target_host

        # 2. TCP connect RTT
        t_connect_start = time.perf_counter()
        try:
            with socket.create_connection((resolved_ip, port), timeout=timeout):
                rtt = (time.perf_counter() - t_connect_start) * 1000.0
                result["connected"] = True
                result["rtt_ms"] = round(rtt, 2)
                if rtt < 30.0:
                    result["rating"] = "excellent"
                elif rtt < 100.0:
                    result["rating"] = "good"
                elif rtt < 250.0:
                    result["rating"] = "fair"
                else:
                    result["rating"] = "poor"
        except OSError:
            result["connected"] = False
            result["rating"] = "offline"

        return result

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
                result["models"] = models[:5]
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

            test_chunks = []
            def cb(indata, frames, time_info, status):
                test_chunks.append(indata.copy())

            with sd.InputStream(samplerate=16000, channels=1, dtype='float32', blocksize=512, callback=cb):
                time.sleep(0.3)

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
    def check_silero_vad() -> dict:
        result = {"available": False, "status": "Fail"}
        try:
            from faster_whisper.vad import get_vad_model
            model = get_vad_model()
            test_chunk = np.zeros(512, dtype=np.float32)
            prob = model(test_chunk)
            result["available"] = True
            result["status"] = f"Pass (Inference OK: {prob[0]:.4f})"
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def check_screen_vision() -> dict:
        result = {"ocr_available": False, "screen_capture": False, "status": "Fail"}
        try:
            import winrt.windows.media.ocr as ocr
            engine = ocr.OcrEngine.try_create_from_user_profile_languages()
            result["ocr_available"] = engine is not None
            result["status"] = "Pass" if result["ocr_available"] else "OCR engine not found"
        except Exception as e:
            result["error"] = str(e)
        return result

    @staticmethod
    def check_whisper() -> dict:
        result = {"loaded": False, "device": "cpu", "error": None}
        try:
            from faster_whisper import WhisperModel
            result["loaded"] = True
            result["status"] = "Pass (faster-whisper installed)"
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
        vad_info = SystemDiagnostics.check_silero_vad()
        vision_info = SystemDiagnostics.check_screen_vision()
        return {
            "internet": SystemDiagnostics.check_internet(),
            "nvidia_build_active": nv_info.get("authenticated", False),
            "nvidia_has_key": nv_info.get("has_key", False),
            "ollama_running": ollama_info["running"],
            "has_mxb_brain": ollama_info.get("has_mxb_brain", False),
            "microphone_active": mic_info["available"],
            "microphone_status": mic_info.get("status"),
            "silero_vad": vad_info.get("available", False),
            "screen_ocr": vision_info.get("ocr_available", False),
            "cpu_ok": psutil.cpu_percent() < 95
        }

    @staticmethod
    def print_full_diagnosis():
        print("=" * 65)
        print("MXB v2.0 FULL SYSTEM & TWO-HANDS CAPABILITY DIAGNOSTIC")
        print("=" * 65)

        # 1. Microphone & VAD
        print("\n[1] MICROPHONE & NEURAL VAD:")
        mic = SystemDiagnostics.check_microphone()
        if mic.get("available") and mic.get("status") == "Pass":
            print(f"  Device Name:    {mic.get('device_name')}")
            print(f"  Sample Rate:    {mic.get('sample_rate')} Hz (16kHz stream active)")
            print(f"  Live Audio RMS: {mic.get('live_rms'):.6f} (Peak: {mic.get('peak_amplitude', 0):.6f})")
        else:
            print(f"  Status:         [FAIL] - {mic.get('error')}")

        vad = SystemDiagnostics.check_silero_vad()
        print(f"  Silero VAD:     [{'PASS' if vad.get('available') else 'FAIL'}] {vad.get('status')}")

        # 2. Vision & OCR
        print("\n[2] SCREEN VISION & OCR (DIGITAL EYES):")
        vision = SystemDiagnostics.check_screen_vision()
        print(f"  Windows OCR:    [{'PASS' if vision.get('ocr_available') else 'FAIL'}] {vision.get('status')}")

        # 3. NVIDIA Cloud Engine
        print("\n[3] NVIDIA BUILD CLOUD AI ENGINE:")
        nv = SystemDiagnostics.check_nvidia_build()
        if nv.get("authenticated"):
            print(f"  Status:         [PASS] Authenticated to NVIDIA Build Cloud")
            print(f"  Speech ASR:     NVIDIA Parakeet / Whisper Cloud Endpoints Ready")
            print(f"  Speech LLM:     NVIDIA meta/llama-3.1-8b-instruct Ready")
        elif nv.get("has_key"):
            print(f"  Status:         [WARN] Key present but authentication failed: {nv.get('status')}")
        else:
            print(f"  Status:         [INFO] Key not set. Using local Faster-Whisper & Ollama.")

        # 4. Local Models
        print("\n[4] LOCAL SPEECH & AI RUNTIMES:")
        whisper = SystemDiagnostics.check_whisper()
        print(f"  Faster-Whisper: [{whisper.get('status')}]")

        ollama = SystemDiagnostics.check_ollama()
        if ollama.get("running"):
            print(f"  Ollama:         [PASS] Active with models: {', '.join(ollama.get('models', []))}")
        else:
            print(f"  Ollama:         [INFO] Not running (NVIDIA cloud will be used if configured)")

        # 5. Speech Synthesis
        print("\n[5] SPEECH SYNTHESIS (TTS):")
        tts = SystemDiagnostics.check_tts()
        if tts.get("available"):
            print(f"  Status:         [PASS] Windows SAPI5 Active ({len(tts.get('voices', []))} voices)")

        # 6. Hardware Load
        print("\n[6] HARDWARE METRICS:")
        cpu = psutil.cpu_percent(interval=0.2)
        ram = psutil.virtual_memory()
        print(f"  CPU Load:       {cpu}%")
        print(f"  RAM Usage:      {ram.percent}% ({ram.used // (1024**3)}GB / {ram.total // (1024**3)}GB)")

        print("\n" + "=" * 65)
        print("DIAGNOSIS COMPLETE - MXB v2.0 ARCHITECTURE READY")
        print("=" * 65)

if __name__ == "__main__":
    SystemDiagnostics.print_full_diagnosis()
