import pyttsx3
import pythoncom
from PySide6.QtCore import QThread, Signal
import time

class TTSWorker(QThread):
    finished_speaking = Signal()

    def __init__(self, text):
        super().__init__()
        self.text = text

    def run(self):
        try:
            pythoncom.CoInitialize()
            engine = pyttsx3.init()
            voices = engine.getProperty('voices')
            for voice in voices:
                if "Zira" in voice.name or "Hazel" in voice.name or "Female" in voice.name:
                    engine.setProperty('voice', voice.id)
                    break
            engine.setProperty('rate', 175)
            engine.say(self.text)
            engine.runAndWait()
        except Exception as e:
            print(f"[TTS Error] {e}")
        finally:
            pythoncom.CoUninitialize()
            self.finished_speaking.emit()

class VoiceSynthesizer:
    def __init__(self):
        self.worker = None

    def speak(self, text: str, wait=False):
        """
        Asynchronously speaks the text using native Windows SAPI5 in a QThread.
        """
        print(f"[MXB Voice] {text}")
        if not text or text.strip() == "":
            return
            
        # Stop previous if still speaking (pyttsx3 doesn't easily stop, but we re-init)
        if self.worker and self.worker.isRunning():
            self.worker.wait(100)
            
        self.worker = TTSWorker(text)
        self.worker.start()
        
        if wait:
            self.worker.wait()
