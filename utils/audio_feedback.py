import sys
import threading
from utils.logger import log

class AudioFeedback:
    """
    Non-blocking native Windows earcons (sound cues) for MXB Voice Assistant.
    Provides instant auditory feedback for voice wake, success, interruption, and errors.
    """

    SOUND_MAP = {
        "listen": "SystemAsterisk",
        "ping": "SystemAsterisk",
        "success": "SystemQuestion",
        "done": "SystemQuestion",
        "abort": "SystemExclamation",
        "cancel": "SystemExclamation",
        "error": "SystemHand",
        "alert": "SystemHand",
    }

    def __init__(self, enabled: bool = True):
        self.enabled = enabled
        self._lock = threading.Lock()

    def set_enabled(self, enabled: bool):
        self.enabled = enabled
        log.info(f"AudioFeedback: Sound cues {'enabled' if enabled else 'disabled'}")

    def play(self, sound_name: str) -> bool:
        """
        Plays a named system earcon asynchronously without blocking caller thread.
        Supported names: 'listen', 'ping', 'success', 'done', 'abort', 'cancel', 'error'.
        """
        if not self.enabled:
            return False

        if sys.platform != "win32":
            return False

        sound_alias = self.SOUND_MAP.get(sound_name.lower().strip())
        if not sound_alias:
            log.debug(f"AudioFeedback: Unknown sound cue '{sound_name}'")
            return False

        try:
            import winsound
            with self._lock:
                winsound.PlaySound(sound_alias, winsound.SND_ALIAS | winsound.SND_ASYNC)
            return True
        except Exception as e:
            log.warning(f"AudioFeedback: Could not play '{sound_alias}': {e}")
            return False

# Global shared instance
audio_feedback = AudioFeedback()
