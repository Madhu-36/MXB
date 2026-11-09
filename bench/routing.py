"""
Routing suite: does the instant (no-LLM) path pick the right action, and does it leave
everything else to the LLM? Runs anywhere in ~1 second, never touches the OS.

Metrics
- precision : of the decisions the fast path made (acting, answering locally, or correctly
              deferring), how many were right. A misroute ("my battery is fine" -> battery check)
              counts against it. CI fails if this drops below --min-precision.
- coverage  : share of actionable commands handled without the LLM (higher = faster, cheaper, offline).
- latency   : time for the fast path to decide (p50 / p95, ms).
With --llm, commands the fast path deferred are sent to the real planner and scored too.
"""
import statistics
import time
from types import SimpleNamespace
from unittest.mock import patch

from bench.routing_cases import CASES

LLM_SENTINEL = "__DEFERRED_TO_LLM__"


class RecordingExecutor:
    """Stands in for OSExecutionManager: records what the router asks for, does nothing."""

    def __init__(self):
        self.calls: list[tuple[str, str]] = []
        self.aborted = False
        recorder = self

        class _Planner:
            current_step = ""
            is_aborted = False

            def execute_plan(self, steps, feedback_callback=None, reset=True):
                for st in steps:
                    recorder.calls.append((st.get("action", ""), str(st.get("target", ""))))
                return ["ok"] * len(steps)

        self.planner = _Planner()
        self.journal = SimpleNamespace(seconds_since_last=lambda: None)
        self.routines = SimpleNamespace(find=lambda name: None)
        self.skills = SimpleNamespace(match=lambda text: None, describe=lambda: "No plugin skills.")
        self.semantic = SimpleNamespace(add=lambda *a, **k: True, recall_texts=lambda *a, **k: [])

    def execute_action(self, action, target=""):
        self.calls.append((action, "" if target is None else str(target)))
        return "ok"

    def abort_current_action(self):
        self.aborted = True


class SilentTTS:
    def __init__(self):
        self.spoken = []

    def speak(self, text, wait=False):
        self.spoken.append(text)

    def speaking_enabled(self):
        return False

    def stop(self):
        pass


class NullMemory:
    def remember(self, fact):
        return True

    def get_memories(self, query=None, limit=5):
        return []


def _pct(n: int, d: int) -> float:
    return round(100.0 * n / d, 1) if d else 0.0


def run_routing(use_llm: bool = False, cases=None) -> dict:
    from engine.router import IntentRouter

    cases = cases or CASES
    executor = RecordingExecutor()
    router = IntentRouter(executor=executor, tts=SilentTTS())
    router.memory = NullMemory()

    rows = []
    fast_times = []
    patches = [patch("engine.router.WeatherProbe.get_weather", return_value={"summary": "Weather unavailable in bench."})]
    if not use_llm:
        patches.append(patch.object(router, "_route_to_llm", side_effect=lambda text, feedback_callback=None: LLM_SENTINEL))
    for p in patches:
        p.start()
    try:
        for phrase, exp_action, exp_target, category in cases:
            executor.calls.clear()
            executor.aborted = False
            t0 = time.perf_counter()
            with patch.object(router, "_route_to_llm", wraps=router._route_to_llm) as llm_spy:
                out = router.route(phrase)
            elapsed_ms = (time.perf_counter() - t0) * 1000
            deferred = llm_spy.called or out == LLM_SENTINEL
            if executor.calls:
                got_action, got_target = executor.calls[0]
            else:
                got_action, got_target = ("LLM", "") if deferred else ("LOCAL", "")
            if not deferred:
                fast_times.append(elapsed_ms)

            target_ok = exp_target is None or got_target.strip() == str(exp_target).strip()
            if exp_action == "LLM":
                outcome = "deferred_ok" if deferred and not executor.calls else "misroute"
            elif deferred:
                if use_llm and executor.calls:
                    outcome = "llm_ok" if (got_action == exp_action) else "llm_wrong"
                else:
                    outcome = "deferred_miss"
            else:
                outcome = "correct" if (got_action == exp_action and target_ok) else "misroute"
            rows.append({"phrase": phrase, "category": category, "expected": exp_action, "expected_target": exp_target,
                         "got": got_action, "got_target": got_target, "outcome": outcome, "ms": round(elapsed_ms, 3)})
    finally:
        for p in reversed(patches):
            p.stop()

    count = lambda *names: sum(1 for r in rows if r["outcome"] in names)  # noqa: E731
    decisions = count("correct", "misroute", "deferred_ok")
    actionable = sum(1 for r in rows if r["expected"] != "LLM")
    handled_fast = sum(1 for r in rows if r["expected"] != "LLM" and r["outcome"] == "correct")
    summary = {
        "cases": len(rows),
        "precision": _pct(count("correct", "deferred_ok"), decisions),
        "coverage": _pct(handled_fast, actionable),
        "misroutes": count("misroute"),
        "deferred_to_llm": count("deferred_miss", "llm_ok", "llm_wrong"),
        "p50_ms": round(statistics.median(fast_times), 3) if fast_times else None,
        "p95_ms": round(sorted(fast_times)[max(0, int(len(fast_times) * 0.95) - 1)], 3) if fast_times else None,
    }
    if use_llm:
        summary["accuracy_with_llm"] = _pct(count("correct", "deferred_ok", "llm_ok"), len(rows))
    categories = {}
    for r in rows:
        c = categories.setdefault(r["category"], {"cases": 0, "correct": 0, "misroute": 0, "deferred": 0})
        c["cases"] += 1
        if r["outcome"] in ("correct", "deferred_ok", "llm_ok"):
            c["correct"] += 1
        elif r["outcome"] in ("misroute", "llm_wrong"):
            c["misroute"] += 1
        else:
            c["deferred"] += 1
    return {"suite": "routing", "summary": summary, "categories": categories, "rows": rows}
