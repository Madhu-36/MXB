import time
from utils.logger import log

class ActionPlanner:
    """
    Multi-Step Action Pipeline for MXB.
    Executes sequential compound tasks with step-level validation,
    adaptive delays, and real-time execution feedback.
    """

    def __init__(self, executor):
        self.executor = executor

    def execute_plan(self, steps: list[dict], feedback_callback=None) -> list[str]:
        """
        Executes an ordered list of step dicts:
        Each step: {"action": "...", "target": "...", "duration": float (optional)}
        """
        results = []
        total = len(steps)
        log.info(f"ActionPlanner: Executing plan containing {total} sequential steps.")

        for idx, step in enumerate(steps, 1):
            action = step.get("action", "").lower().strip()
            target = step.get("target", "")
            duration = step.get("duration", 0.0)

            if not action:
                continue

            status_msg = f"Step {idx}/{total}: {action} -> {target}"
            log.info(f"ActionPlanner: {status_msg}")
            if feedback_callback:
                feedback_callback(status_msg)

            # Special case for pause/wait step
            if action in ["wait", "sleep", "pause"]:
                try:
                    sleep_sec = float(target) if target else float(duration or 1.0)
                    time.sleep(max(0.1, min(sleep_sec, 15.0)))
                    results.append(f"Waited {sleep_sec}s")
                except Exception:
                    time.sleep(1.0)
                    results.append("Waited 1.0s")
                continue

            # Standard OS action via Executor
            try:
                res = self.executor.execute_action(action, target)
                results.append(res)
            except Exception as e:
                err_msg = f"Failed step {idx} ({action}): {e}"
                log.error(f"ActionPlanner: {err_msg}")
                results.append(err_msg)
                # Keep executing subsequent steps if possible
                continue

            # Default micro-delay between atomic desktop interactions
            time.sleep(0.15)

        return results
