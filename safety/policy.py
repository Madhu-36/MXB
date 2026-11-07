"""
MXB Safety Policy & Confirmation Manager.

Every action passes through OSExecutionManager.execute_action, which asks the
SafetyPolicy whether it needs the user's confirmation. If it does, the executor
calls its confirm_callback (wired to CommandBus.request_confirmation), which:
  1. announces the question by voice, HUD and chat,
  2. blocks the action worker until the user says/types "yes" or "no",
     presses a chat button, or the timeout expires (timeout = NO).
"""
import re
import threading
from engine.actions_catalog import risk_of

YES_WORDS = {
    "yes", "yeah", "yep", "yup", "sure", "ok", "okay", "confirm", "confirmed", "do it",
    "go ahead", "proceed", "yes please", "yes do it", "affirmative", "approve", "allow", "haan", "ha"
}
NO_WORDS = {
    "no", "nope", "nah", "cancel", "don't", "dont", "do not", "stop", "abort", "deny",
    "negative", "no thanks", "never mind", "nevermind", "reject", "nahi"
}


def classify_answer(text: str) -> bool | None:
    """Returns True for yes, False for no, None if the text isn't a yes/no answer."""
    clean = re.sub(r"[^\w\s']", " ", (text or "").lower())
    clean = re.sub(r"\s+", " ", clean).strip()
    # Drop a leading wake word / filler so "mxb yes" and "yes mxb" both work.
    clean = re.sub(r"^(?:hey\s+)?(?:mxb|m x b)\s+", "", clean)
    clean = re.sub(r"\s+(?:mxb|m x b)$", "", clean)
    if not clean:
        return None
    if clean in YES_WORDS:
        return True
    if clean in NO_WORDS:
        return False
    words = clean.split()
    if len(words) <= 4:
        if words[0] in {"yes", "yeah", "yep", "sure", "ok", "okay", "confirm"} and not any(w in NO_WORDS for w in words[1:]):
            return True
        if words[0] in {"no", "nope", "cancel", "don't", "dont", "stop"}:
            return False
    return None


class SafetyPolicy:
    """Decides which action invocations need explicit user confirmation."""

    def __init__(self, config: dict | None = None):
        safety = (config or {}).get("safety", {}) if isinstance(config, dict) else {}
        self.confirm_destructive = bool(safety.get("confirm_destructive", True))

    def confirmation_reason(self, action: str, target: str = "", context: dict | None = None) -> str | None:
        """
        Returns a human-readable question if confirmation is required, else None.
        context may carry facts discovered by the executor (e.g. {"overwrite": True}).
        """
        if not self.confirm_destructive:
            return None
        context = context or {}
        target = str(target or "").strip()

        if context.get("overwrite"):
            return f"'{context.get('path', target)}' already exists. Overwrite it?"

        if risk_of(action) != "confirm":
            return None
        if action == "power_action" and target.lower().replace(" ", "_") in {"cancel", "abort", "cancel_shutdown"}:
            return None  # cancelling a shutdown is always safe
        if action == "phone_remote":
            if target.lower().strip() not in {"on", "start", "enable"}:
                return None  # turning it off / checking status is always safe
            return "Turn on the phone remote? Anyone on this Wi-Fi with the secret link could control this PC."

        if action == "delete_file":
            path, _, mode = target.partition("::")
            if mode.strip().lower() == "permanent":
                return f"Permanently delete '{path.strip()}'? This cannot be undone."
            return f"Move '{path.strip()}' to the Recycle Bin?"
        if action == "empty_recycle_bin":
            return "Empty the Recycle Bin? Files in it will be gone for good."
        if action == "kill_process":
            return f"Terminate the process '{target}'? Unsaved work in it will be lost."
        if action == "force_close_app":
            return f"Force-close {target}? Unsaved work will be lost."
        if action == "power_action":
            return f"{target.replace('_', ' ').capitalize() or 'Power action'} the computer now?"
        if action == "grant_file_access":
            scope = "your entire file system" if target.lower() in {"all", "everything", "full", "*"} else f"'{target}'"
            return f"Give MXB access to {scope}?"
        if action == "install_update":
            return "Download and install the new MXB version now? MXB will restart."
        if action == "vault_get":
            return f"Reveal the secret '{target}' out loud and on screen?"
        return f"Run {action.replace('_', ' ')} on '{target}'?"


class ConfirmationManager:
    """Thread-safe single pending yes/no question shared by voice, chat and HUD."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = float(timeout)
        self._lock = threading.Lock()
        self._event: threading.Event | None = None
        self._result = False
        self.question = ""

    def has_pending(self) -> bool:
        with self._lock:
            return self._event is not None and not self._event.is_set()

    def request(self, question: str, announce=None, abort_event: threading.Event | None = None) -> bool:
        """Blocks the calling (worker) thread until answered, aborted or timed out."""
        with self._lock:
            if self._event is not None and not self._event.is_set():
                # Another question is already pending; refuse rather than stack questions.
                return False
            self._event = threading.Event()
            self._result = False
            self.question = question
            event = self._event

        if announce:
            try:
                announce(question)
            except Exception:
                pass

        waited = 0.0
        step = 0.1
        while waited < self.timeout:
            if event.wait(step):
                break
            if abort_event is not None and abort_event.is_set():
                break
            waited += step

        with self._lock:
            approved = bool(event.is_set() and self._result)
            event.set()
            self._event = None
            self.question = ""
        return approved

    def resolve(self, approved: bool) -> bool:
        """Answers the pending question. Returns False if nothing was pending."""
        with self._lock:
            if self._event is None or self._event.is_set():
                return False
            self._result = bool(approved)
            self._event.set()
            return True

    def answer_text(self, text: str) -> bool | None:
        """Feeds free text (voice/chat). Returns the decision if consumed, else None."""
        if not self.has_pending():
            return None
        decision = classify_answer(text)
        if decision is None:
            return None
        return decision if self.resolve(decision) else None

    def cancel_pending(self):
        self.resolve(False)
