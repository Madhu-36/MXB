import socket
import requests
import psutil

class SystemDiagnostics:
    @staticmethod
    def check_internet() -> bool:
        try:
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False

    @staticmethod
    def check_ollama() -> bool:
        try:
            res = requests.get("http://localhost:11434/", timeout=2)
            return res.status_code == 200
        except:
            return False

    @staticmethod
    def check_microphone() -> bool:
        try:
            import sounddevice as sd
            device_info = sd.query_devices(sd.default.device[0])
            return device_info is not None
        except:
            return False

    @staticmethod
    def get_health_report() -> dict:
        return {
            "internet": SystemDiagnostics.check_internet(),
            "ollama_running": SystemDiagnostics.check_ollama(),
            "microphone_active": SystemDiagnostics.check_microphone(),
            "cpu_ok": psutil.cpu_percent() < 95
        }
