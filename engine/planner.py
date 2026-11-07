import time
import threading
from utils.logger import log


class ActionPlanner:
    """
    Multi-Step Action Pipeline for MXB with live interruptibility.
    Executes sequential compound tasks with step-level validation,
    adaptive delays, real-time feedback, and instant abort capability.

    While a plan runs it holds the executor's input lock, so a question answered
    in parallel (info lane) can never inject keystrokes into the middle of a plan.
    """

    def __init__(self, executor):
        self.executor = executor
        self._abort_event = threading.Event()
        self._depth = 0
        self._depth_lock = threading.Lock()
        self.current_step = ""

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
                try:
                    res = self.executor.execute_action(action, target)
                    results.append(res)
                except Exception as e:
                    err_msg = f"Failed step {idx} ({action}): {e}"
                    log.error(f"ActionPlanner: {err_msg}")
                    results.append(err_msg)
                    continue

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
