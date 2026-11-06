import re
import time
import threading
from utils.logger import log
from utils.audio_feedback import audio_feedback

class TimerManager:
    """
    Voice-Activated Countdown Timers & Stopwatch Manager for MXB.
    Runs non-blocking background threads with automatic audio cues on completion.
    """

    TIME_REGEX = re.compile(
        r'(?:(\d+)\s*(?:hours?|hrs?|h))?\s*'
        r'(?:(\d+)\s*(?:minutes?|mins?|m))?\s*'
        r'(?:(\d+)\s*(?:seconds?|secs?|s))?',
        re.IGNORECASE
    )

    def __init__(self):
        self._timers: dict[str, dict] = {}
        self._lock = threading.Lock()

    @classmethod
    def parse_duration(cls, text: str) -> int:
        """Parses natural time strings into total seconds. Returns 0 if unparseable."""
        clean = text.lower().strip()
        if clean.isdigit():
            return int(clean)

        match = cls.TIME_REGEX.search(clean)
        if not match or not any(match.groups()):
            return 0

        hours = int(match.group(1)) if match.group(1) else 0
        minutes = int(match.group(2)) if match.group(2) else 0
        seconds = int(match.group(3)) if match.group(3) else 0

        return hours * 3600 + minutes * 60 + seconds

    def start_timer(self, label: str, duration_sec: int, on_complete = None) -> dict:
        """Starts a background countdown timer."""
        if duration_sec <= 0:
            return {"success": False, "error": "Timer duration must be greater than zero."}

        clean_label = label.strip() or f"Timer-{len(self._timers) + 1}"
        cancel_event = threading.Event()
        start_time = time.time()
        end_time = start_time + duration_sec

        def _timer_worker():
            # Wait until end time or cancel event
            while time.time() < end_time:
                if cancel_event.is_set():
                    log.info(f"TimerManager: Timer '{clean_label}' cancelled.")
                    return
                time.sleep(0.2)

            log.info(f"TimerManager: Timer '{clean_label}' ({duration_sec}s) finished!")
            audio_feedback.play("alert")

            with self._lock:
                self._timers.pop(clean_label, None)

            if on_complete and callable(on_complete):
                try:
                    on_complete(clean_label)
                except Exception as e:
                    log.warning(f"TimerManager: Callback error: {e}")

        th = threading.Thread(target=_timer_worker, name=f"MXB-Timer-{clean_label}", daemon=True)

        with self._lock:
            self._timers[clean_label] = {
                "label": clean_label,
                "duration_sec": duration_sec,
                "end_time": end_time,
                "cancel_event": cancel_event,
                "thread": th
            }

        th.start()
        log.info(f"TimerManager: Started timer '{clean_label}' for {duration_sec}s.")
        return {
            "success": True,
            "label": clean_label,
            "duration_sec": duration_sec,
            "summary": f"Timer '{clean_label}' set for {duration_sec} seconds."
        }

    def cancel_timer(self, label: str) -> bool:
        """Cancels an active timer."""
        with self._lock:
            timer_data = self._timers.pop(label, None)
            if timer_data:
                timer_data["cancel_event"].set()
                return True
        return False

    def get_remaining_seconds(self, label: str) -> int | None:
        """Returns seconds remaining on the specified timer."""
        with self._lock:
            timer_data = self._timers.get(label)
            if not timer_data:
                return None
            rem = int(timer_data["end_time"] - time.time())
            return max(0, rem)

    def list_active_timers(self) -> list[dict]:
        """Returns list of all active timers with remaining durations."""
        active = []
        with self._lock:
            now = time.time()
            for label, data in self._timers.items():
                rem = max(0, int(data["end_time"] - now))
                active.append({"label": label, "remaining_sec": rem, "total_sec": data["duration_sec"]})
        return active

# Global shared instance
timer_manager = TimerManager()
