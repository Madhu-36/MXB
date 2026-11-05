import queue
import time
import pythoncom
from PySide6.QtCore import QObject, QThread, Signal

class TTSThread(QThread):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self):
        super().__init__()
        self.text_queue = queue.Queue()
        self.is_running = True
        self._is_speaking = False
        self.speaker = None

    def enqueue(self, text: str):
        if text and text.strip() and self.is_running:
            self.text_queue.put(text.strip())

    def stop(self):
        self.is_running = False
        # Drain any pending queued text
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break
        # Halt any ongoing speech immediately via SVSFPurgeBeforeSpeak
        if self.speaker:
            try:
                self.speaker.Speak("", 2)
            except Exception:
                pass
        self.text_queue.put(None)
        self.wait(1500)

    def run(self):
        pythoncom.CoInitialize()
        try:
            import win32com.client
            self.speaker = win32com.client.Dispatch("SAPI.SpVoice")
            # Select Zira or Hazel or female voice if available
            for v in self.speaker.GetVoices():
                desc = v.GetDescription()
                if "Zira" in desc or "Hazel" in desc or "Female" in desc:
                    self.speaker.Voice = v
                    break
            self.speaker.Rate = 1 # Clear, natural pacing
        except Exception as e:
            print(f"[TTS SAPI Init Error] {e}")

        while self.is_running:
            try:
                text = self.text_queue.get(timeout=0.1)
                if text is None or not self.is_running:
                    break
                    
                self._is_speaking = True
                self.started_speaking.emit()
                print(f"[MXB Voice] {text}")
                
                if self.speaker:
                    try:
                        # 0 = SVSFDefault (synchronous speaking so we know exactly when it finishes)
                        self.speaker.Speak(text, 0)
                    except Exception as spk_err:
                        print(f"[TTS Speak Error] {spk_err}")
                else:
                    # Fallback to pyttsx3 if SAPI COM dispatch failed
                    try:
                        import pyttsx3
                        engine = pyttsx3.init()
                        engine.setProperty('rate', 175)
                        engine.say(text)
                        engine.runAndWait()
                    except Exception as pyttsx_err:
                        print(f"[TTS Fallback Error] {pyttsx_err}")

                # If no more items are queued, signal that speaking has finished
                if self.text_queue.empty():
                    self._is_speaking = False
                    self.finished_speaking.emit()
                    
            except queue.Empty:
                if self._is_speaking and self.text_queue.empty():
                    self._is_speaking = False
                    self.finished_speaking.emit()
            except Exception as loop_err:
                print(f"[TTS Loop Error] {loop_err}")
                self._is_speaking = False
                self.finished_speaking.emit()
                
        self._is_speaking = False
        if self.speaker:
            try:
                self.speaker.Speak("", 2)
            except Exception:
                pass
            self.speaker = None
        pythoncom.CoUninitialize()

class VoiceSynthesizer(QObject):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self):
        super().__init__()
        self._thread = TTSThread()
        self._thread.started_speaking.connect(self.started_speaking.emit)
        self._thread.finished_speaking.connect(self.finished_speaking.emit)
        self._thread.start()

    @property
    def is_speaking(self) -> bool:
        return self._thread._is_speaking

    def speak(self, text: str, wait=False):
        """
        Asynchronously enqueues text to be spoken via native Windows SAPI.
        Emits started_speaking and finished_speaking signals cleanly.
        """
        if not text or not text.strip():
            return
            
        self._thread.enqueue(text)
        
        if wait:
            # Wait until queue drains and speech completes
            while self._thread._is_speaking or not self._thread.text_queue.empty():
                time.sleep(0.05)

    def stop(self):
        self._thread.stop()
