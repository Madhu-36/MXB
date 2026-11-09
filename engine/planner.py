import re
import time
import threading
from utils.logger import log

# Steps that act on whatever window is in front. After a failed step, or before the app a plan just
# opened has come to the front, running them could type into the wrong window.
INPUT_ACTIONS = {"type_text", "press_key", "shortcut", "paste_text", "select_all", "copy_text", "save_file", "undo",
                 "left_click", "right_click", "double_click", "click_element", "click_text", "click_mark",
                 "type_into", "type_mark", "search_on_screen", "focus_search_box", "manage_window"}
_FAILURE = re.compile(r"\b(could not|couldn't|cannot|can't|failed|failure|error|not found|no app|unable|"
                      r"don't have access|denied|refused|blocked|no window|not running|isn't running)\b", re.I)


def step_failed(result) -> bool:
    """Executor results are sentences; these are the ways they say a step didn't happen."""
    text = str(result or "")
    return bool(_FAILURE.search(text)) and not text.lower().startswith(("done", "ok"))


def foreground_window() -> int:
    """Handle of the window in front (0 when unknown, e.g. not on Windows)."""
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        return int(user32.GetForegroundWindow() or 0)
    except Exception:
        return 0


class ActionPlanner:
    """
    Multi-Step Action Pipeline for MXB with live interruptibility.
    Executes sequential compound tasks with step-level validation,
    adaptive delays, real-time feedback, and instant abort capability.

    While a plan runs it holds the executor's input lock, so a question answered
    in parallel (info lane) can never inject keystrokes into the middle of a plan.
    """

    def __init__(self, executor, launch_wait_s: float = 6.0):
        self.executor = executor
        self._abort_event = threading.Event()
        self._depth = 0
        self._depth_lock = threading.Lock()
        self.current_step = ""
        self.launch_wait_s = launch_wait_s
        self.foreground = foreground_window          # replaceable in tests

    def _wait_for_new_window(self, before: int) -> bool:
        """After launching an app: wait (abortably) until a different window is in front."""
        if not before:
            return True                                # can't tell on this platform; don't block
        deadline = time.monotonic() + self.launch_wait_s
        while time.monotonic() < deadline:
            if self._abort_event.is_set():
                return False
            now = self.foreground()
            if now and now != before:
                time.sleep(0.3)                       # let it finish drawing before keystrokes arrive
                return True
            time.sleep(0.1)
        return False

    @property
    def is_busy(self) -> bool:
        return self._depth > 0

    @property
    def is_aborted(self) -> bool:
        return self._abort_event.is_set()

    @property
    def abort_event(self) -> threading.Event:
        return self._abort_event

    def abort(self):
        """Immediately aborts any active plan execution."""
        log.warning("ActionPlanner: ABORT SIGNAL RECEIVED! Halting plan execution.")
        self._abort_event.set()

    def reset(self):
        self._abort_event.clear()

    def _sleep_abortable(self, seconds: float) -> bool:
        """Sleeps in 50ms slices. Returns False if aborted."""
        elapsed = 0.0
        while elapsed < seconds:
            if self._abort_event.is_set():
                return False
            time.sleep(0.05)
            elapsed += 0.05
        return not self._abort_event.is_set()

    def execute_plan(self, steps: list[dict], feedback_callback=None, reset: bool = True) -> list[str]:
        """
        Executes an ordered list of step dicts:
        Each step: {"action": "...", "target": "...", "duration": float (optional)}
        Checks for abort signals between every single step and sub-step.
        reset=False is used by nested callers (agent loop) so a "stop" said while
        the LLM was thinking is not wiped out.
        """
        if reset:
            self.reset()
        with self._depth_lock:
            self._depth += 1
        results = []
        total = len(steps)
        log.info(f"ActionPlanner: Executing plan containing {total} sequential steps.")

        input_lock = getattr(self.executor, "input_lock", None)
        if input_lock is not None:
            input_lock.acquire()
        try:
            for idx, step in enumerate(steps, 1):
                if self._abort_event.is_set():
                    log.warning(f"ActionPlanner: Plan aborted before step {idx}/{total}.")
                    results.append("Execution aborted by user interrupt.")
                    break

                if not isinstance(step, dict):
                    continue
                action = str(step.get("action", "")).lower().strip()
                target = step.get("target", "")
                duration = step.get("duration", 0.0)

                if not action or action in ("conversation", "none"):
                    continue

                status_msg = f"Step {idx}/{total}: {action} -> {target}"
                self.current_step = status_msg
                log.info(f"ActionPlanner: {status_msg}")
                if feedback_callback:
                    feedback_callback(status_msg)

                # Special case for pause/wait step (abortable in small chunks)
                if action in ["wait", "sleep", "pause"]:
                    try:
                        sleep_sec = float(target) if target else float(duration or 1.0)
                    except (TypeError, ValueError):
                        sleep_sec = 0.5
                    sleep_sec = max(0.05, min(sleep_sec, 15.0))
                    if not self._sleep_abortable(sleep_sec):
                        results.append("Wait aborted by interrupt.")
                        break
                    results.append(f"Waited {sleep_sec:.1f}s")
                    continue

                # Standard OS action via Executor
                later_input = any(str(s.get("action", "")).lower() in INPUT_ACTIONS
                                  for s in steps[idx:] if isinstance(s, dict))
                before = self.foreground() if action == "open_app" and later_input else 0
                try:
                    res = self.executor.execute_action(action, target)
                    results.append(res)
                except Exception as e:
                    res = f"Failed step {idx} ({action}): {e}"
                    log.error(f"ActionPlanner: {res}")
                    results.append(res)

                if later_input and step_failed(res):
                    msg = (f"Stopped after step {idx} ({action} {target}) didn't work, so I didn't type or click "
                           f"into whatever window is open instead.")
                    log.warning(f"ActionPlanner: {msg} Result was: {res}")
                    results.append(msg)
                    break
                if before and not self._wait_for_new_window(before):
                    if self._abort_event.is_set():
                        results.append("Execution aborted by user interrupt.")
                        break
                    msg = (f"{target} didn't come to the front within {self.launch_wait_s:.0f} seconds, "
                           f"so I stopped before typing into another window.")
                    log.warning(f"ActionPlanner: {msg}")
                    results.append(msg)
                    break

                # Micro-delay between desktop interactions (checking abort)
                self._sleep_abortable(0.15)

        finally:
            if input_lock is not None:
                input_lock.release()
            with self._depth_lock:
                self._depth -= 1
                if self._depth == 0:
                    self.current_step = ""

        return results
