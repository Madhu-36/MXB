import time
import threading
from utils.logger import log

class ActionPlanner:
    """
    Multi-Step Action Pipeline for MXB with live interruptibility.
    Executes sequential compound tasks with step-level validation,
    adaptive delays, real-time feedback, and instant abort capability.
    """

    def __init__(self, executor):
        self.executor = executor
        self._abort_event = threading.Event()
        self._is_running = False

    @property
    def is_busy(self) -> bool:
        return self._is_running

    def abort(self):
        """Immediately aborts any active plan execution."""
        log.warning("ActionPlanner: ABORT SIGNAL RECEIVED! Halting plan execution.")
        self._abort_event.set()

    def reset(self):
        self._abort_event.clear()

    def execute_plan(self, steps: list[dict], feedback_callback=None) -> list[str]:
        """
        Executes an ordered list of step dicts:
        Each step: {"action": "...", "target": "...", "duration": float (optional)}
        Checks for abort signals between every single step and sub-step.
        """
        self.reset()
        self._is_running = True
        results = []
        total = len(steps)
        log.info(f"ActionPlanner: Executing plan containing {total} sequential steps.")

        try:
            for idx, step in enumerate(steps, 1):
                if self._abort_event.is_set():
                    log.warning(f"ActionPlanner: Plan aborted before step {idx}/{total}.")
                    results.append("Execution aborted by user interrupt.")
                    break

                action = step.get("action", "").lower().strip()
                target = step.get("target", "")
                duration = step.get("duration", 0.0)

                if not action:
                    continue

                status_msg = f"Step {idx}/{total}: {action} -> {target}"
                log.info(f"ActionPlanner: {status_msg}")
                if feedback_callback:
                    feedback_callback(status_msg)

                # Special case for pause/wait step (abortable in small chunks)
                if action in ["wait", "sleep", "pause"]:
                    try:
                        sleep_sec = float(target) if target else float(duration or 1.0)
                        sleep_sec = max(0.05, min(sleep_sec, 15.0))
                        elapsed = 0.0
                        while elapsed < sleep_sec and not self._abort_event.is_set():
                            time.sleep(0.05)
                            elapsed += 0.05
                        if self._abort_event.is_set():
                            results.append("Wait aborted by interrupt.")
                            break
                        results.append(f"Waited {sleep_sec:.1f}s")
                    except Exception:
                        time.sleep(0.5)
                        results.append("Waited 0.5s")
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
                for _ in range(3):
                    if self._abort_event.is_set():
                        break
                    time.sleep(0.05)

        finally:
            self._is_running = False

        return results
