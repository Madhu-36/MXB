import queue
import threading
import time
from PySide6.QtCore import QObject, QThread, Signal

SVSF_ASYNC = 1
SVSF_PURGE_BEFORE_SPEAK = 2


class TTSThread(QThread):
    started_speaking = Signal()
    finished_speaking = Signal()

    def __init__(self):
        super().__init__()
        self.text_queue = queue.Queue()
        self.is_running = True
        self._is_speaking = False
        self._interrupt = threading.Event()
        self.speaker = None

    def enqueue(self, text: str):
        if text and text.strip() and self.is_running:
            self.text_queue.put(text.strip())

    def _drain(self):
        while not self.text_queue.empty():
            try:
                self.text_queue.get_nowait()
            except queue.Empty:
                break

    def interrupt(self):
        """Stops the current sentence and drops queued speech, keeping the thread alive."""
        self._drain()
        self._interrupt.set()

    def stop(self):
        self.is_running = False
        self._drain()
        self._interrupt.set()
        self.text_queue.put(None)
        self.wait(1500)

    def _speak_sapi(self, text: str):
        # Async speak + polling lets the TTS thread itself purge speech on interrupt
        # (SAPI COM objects must only be touched from the thread that created them).
        self.speaker.Speak(text, SVSF_ASYNC)
        while not self.speaker.WaitUntilDone(50):
            if self._interrupt.is_set() or not self.is_running:
                self.speaker.Speak("", SVSF_ASYNC | SVSF_PURGE_BEFORE_SPEAK)
                break

    def run(self):
        import pythoncom
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
            self.speaker.Rate = 1  # Clear, natural pacing
        except Exception as e:
            print(f"[TTS SAPI Init Error] {e}")

        while self.is_running:
            try:
                text = self.text_queue.get(timeout=0.1)
                if text is None or not self.is_running:
                    break

                self._interrupt.clear()
                self._is_speaking = True
                self.started_speaking.emit()
                print(f"[MXB Voice] {text}")

                if self.speaker:
                    try:
                        self._speak_sapi(text)
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
                self.speaker.Speak("", SVSF_PURGE_BEFORE_SPEAK)
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

    def interrupt(self):
        """Cut off current speech immediately ("stop", "shut up", kill switch)."""
        self._thread.interrupt()

    def stop(self):
        self._thread.stop()


class ModalityTTS:
    """
    Wraps a VoiceSynthesizer so each worker thread decides whether replies are
    spoken: voice commands get spoken + written replies, typed chat commands get
    written replies only (unless voice.speak_text_replies is true).
    All other attributes (signals, stop, interrupt) pass straight through.
    """

    def __init__(self, inner):
        self._inner = inner
        self._local = threading.local()

    @property
    def inner(self):
        return self._inner

    def set_thread_speaking(self, enabled: bool):
        self._local.enabled = bool(enabled)

    def speaking_enabled(self) -> bool:
        return getattr(self._local, "enabled", True)

    def speak(self, text: str, wait=False):
        if self.speaking_enabled():
            self._inner.speak(text, wait=wait)

    def speak_always(self, text: str, wait=False):
        self._inner.speak(text, wait=wait)

    def interrupt(self):
        fn = getattr(self._inner, "interrupt", None)
        if callable(fn):
            fn()

    def __getattr__(self, name):
        return getattr(self._inner, name)
