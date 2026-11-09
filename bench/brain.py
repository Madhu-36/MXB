"""
Brain suite: can MXB turn everyday requests into the right actions? Runs the real router and the
real planner model (Ollama or NVIDIA) against bench/brain_cases.py, records the actions it asks for
and executes nothing, so it is safe to run while someone uses the PC.

    python -m bench.run --suite brain                         # the configured model
    python -m bench.run --suite brain --model qwen3:4b        # compare another local model
    python -m bench.run --suite brain --local-only            # ignore the NVIDIA key

Metrics: accuracy (cases whose plan contains every expected step, in order, with nothing destructive
added), per category, how many the instant fast path handled, how many the model failed to answer
(timeouts, unreadable output) and planning latency (p50 / p95, seconds).
"""
import statistics
import time
from unittest.mock import patch

from bench.brain_cases import BRAIN_CASES, DESTRUCTIVE
from bench.routing import NullMemory, RecordingExecutor, SilentTTS

FAILED_REPLIES = ("could not reach my reasoning engine", "can't reach my reasoning engine", "too slow on this pc")


def _target_has(target: str, keyword: str) -> bool:
    target = target.lower()
    return any(alt.strip() and alt.strip() in target for alt in keyword.lower().split("|"))


def step_matches(call: tuple, alternatives) -> bool:
    action, target = call
    return any(action == want and all(_target_has(target, k) for k in keywords) for want, keywords in alternatives)


def score_plan(calls: list, steps: list) -> tuple[bool, str]:
    """(passed, reason). Expected steps must appear in order; no unexpected destructive action."""
    acted = [c for c in calls if c[0] not in ("conversation", "wait")]
    allowed = {want for alternatives in steps for want, _ in alternatives}
    bad = [a for a, _ in acted if a in DESTRUCTIVE and a not in allowed]
    if bad:
        return False, f"unrequested destructive action: {bad[0]}"
    if not steps:
        return (not acted), ("ok" if not acted else f"acted instead of answering: {acted[0][0]}")
    i = 0
    for call in acted:
        if i < len(steps) and step_matches(call, steps[i]):
            i += 1
    if i == len(steps):
        return True, "ok"
    want = " or ".join(f"{a}({', '.join(k)})" for a, k in steps[i])
    return False, f"missing step {i + 1}: {want}"


class RecordingMemory(NullMemory):
    """Memory writes count as the remember_fact action they stand for."""

    def __init__(self, calls: list):
        self.calls = calls

    def remember(self, fact):
        self.calls.append(("remember_fact", str(fact)))
        return True


def run_brain(cases=None, model: str | None = None, local_only: bool = False, router=None) -> dict:
    from engine.router import IntentRouter

    cases = cases or BRAIN_CASES
    executor = RecordingExecutor()
    if router is None:
        router = IntentRouter(executor=executor, tts=SilentTTS())
    else:
        router.executor = executor
    router.memory = RecordingMemory(executor.calls)
    executor.semantic.add = lambda text, *a, **k: executor.calls.append(("remember_fact", str(text))) or True
    if model:
        router.config.setdefault("llm", {})["local_model"] = model
        router.llm.local_model = model
    patches = [patch("engine.router.WeatherProbe.get_weather", return_value={"summary": "Weather unavailable in bench."})]
    if local_only:
        patches.append(patch("engine.llm_client.CredentialsManager.get_nvidia_api_key", return_value=None))
    for p in patches:
        p.start()
    rows, llm_times = [], []
    cloud = getattr(router.llm, "cloud_available", None)
    label = "NVIDIA cloud" if callable(cloud) and cloud() else getattr(router.llm, "local_model", "")
    try:
        for phrase, steps, category in cases:
            executor.calls.clear()
            t0 = time.perf_counter()
            with patch.object(router, "_route_to_llm", wraps=router._route_to_llm) as llm_spy:
                try:
                    out = router.route(phrase) or ""
                except Exception as e:                      # a crash is a failed case, not a failed run
                    out = f"error: {type(e).__name__}: {e}"
            seconds = time.perf_counter() - t0
            used_llm = llm_spy.called
            if used_llm:
                llm_times.append(seconds)
            failed = any(f in out.lower() for f in FAILED_REPLIES) or out.startswith("error:")
            passed, reason = score_plan(list(executor.calls), steps)
            if failed and not executor.calls:
                passed, reason = False, "model gave no plan: " + out[:80]
            rows.append({"phrase": phrase, "category": category, "passed": passed, "reason": reason,
                         "calls": [list(c) for c in executor.calls], "used_llm": used_llm,
                         "model_failed": failed, "seconds": round(seconds, 2)})
    finally:
        for p in reversed(patches):
            p.stop()

    n = len(rows)
    passed = sum(r["passed"] for r in rows)
    categories = {}
    for r in rows:
        c = categories.setdefault(r["category"], {"cases": 0, "passed": 0})
        c["cases"] += 1
        c["passed"] += r["passed"]
    ordered = sorted(llm_times)
    summary = {
        "cases": n,
        "accuracy": round(100.0 * passed / n, 1) if n else 0.0,
        "passed": passed,
        "fast_path": sum(not r["used_llm"] for r in rows),
        "model_failures": sum(r["model_failed"] for r in rows),
        "model": label,
        "p50_s": round(statistics.median(ordered), 2) if ordered else None,
        "p95_s": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2) if ordered else None,
    }
    return {"suite": "brain", "summary": summary, "categories": categories, "rows": rows}
