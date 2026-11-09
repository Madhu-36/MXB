import os
import sys
import time
import unittest
from pathlib import Path

# Set up project root in sys.path
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

# Suites that only need plain Python + Qt (run on any OS via tests/_stubs.py).
PORTABLE_SUITES = [
    "tests.test_config_schema",
    "tests.test_file_search",
    "tests.test_memory_export",
    "tests.test_math_fastpath",
    "tests.test_file_preview",
    "tests.test_safety_policy",
    "tests.test_file_permissions",
    "tests.test_wake_word",
    "tests.test_command_bus",
    "tests.test_companion_router",
    "tests.test_ui_and_hardware_logic",
    "tests.test_chat_window",
    "tests.test_end_to_end_flow",
    "tests.test_v4_agent",
    "tests.test_v4_voice",
    "tests.test_v4_memory",
    "tests.test_v4_automation",
    "tests.test_section1",
    "tests.test_v42_web",
    "tests.test_v42_mcp",
    "tests.test_v42_grounding",
    "tests.test_v42_indic",
    "tests.test_v43_scam",
    "tests.test_v43_meetings",
    "tests.test_v43_accessibility",
    "tests.test_v43_focus",
    "tests.test_v43_integration",
    "tests.test_v43_listening",
    "tests.test_v44_brain",
    "tests.test_v44_voice",
    "tests.test_v44_turn",
]


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotate_failures(mod_name: str, res, limit: int = 10) -> list[str]:
    """On GitHub Actions, prints each failing test as an ::error annotation. Annotations show on the run's
    summary page (no log download needed), so a failure is readable at a glance, even from a phone."""
    lines = []
    for test, trace in (res.failures + res.errors)[:limit]:
        tail = [ln.strip() for ln in trace.strip().splitlines() if ln.strip() and not ln.startswith("Traceback")][-4:]
        lines.append(f"::error title={_escape(mod_name)}::{_escape(test.id() + ': ' + ' | '.join(tail))[:1500]}")
    if os.environ.get("GITHUB_ACTIONS") == "true":
        for line in lines:
            print(line, flush=True)
    return lines


def run_all_verifications(mode: str = "all"):
    print("=" * 65)
    print("   MACHINE EXECUTIVE BRAIN (MXB) - FULL SUITE VERIFICATION")
    print("=" * 65)

    test_modules = [
        "tests.test_architecture",
        "tests.test_config_schema",
        "tests.test_mouse_safety",
        "tests.test_keyboard_macros",
        "tests.test_screen_roi",
        "tests.test_file_search",
        "tests.test_memory_export",
        "tests.test_executor_apps",
        "tests.test_clipboard_monitor",
        "tests.test_active_window_crop",
        "tests.test_math_fastpath",
        "tests.test_network_diagnostics",
        "tests.test_file_preview",
        "tests.test_shortcut_validation",
        "tests.test_audio_feedback",
        "tests.test_power_manager",
        "tests.test_window_geometry",
        "tests.test_vault",
        "tests.test_weather",
        "tests.test_process_manager",
        "tests.test_color_picker",
        "tests.test_timer_manager",
        "tests.test_lock_and_trash",
        "tests.test_router_extensions",
        "tests.test_safety_policy",
        "tests.test_file_permissions",
        "tests.test_wake_word",
        "tests.test_command_bus",
        "tests.test_companion_router",
        "tests.test_ui_and_hardware_logic",
        "tests.test_chat_window",
        "tests.test_end_to_end_flow",
        "tests.test_v4_agent",
        "tests.test_v4_voice",
        "tests.test_v4_memory",
        "tests.test_v4_automation",
        "tests.test_section1"
    ]
    test_modules += [m for m in PORTABLE_SUITES if m not in test_modules]   # "all" really means all
    if mode == "portable":
        test_modules = PORTABLE_SUITES
    elif mode == "windows":
        test_modules = [m for m in test_modules if m not in PORTABLE_SUITES]
    print(f"Mode: {mode} ({len(test_modules)} suites)")

    total_tests = 0
    total_failures = 0
    total_errors = 0
    suite_timings = []
    t0 = time.time()

    for mod_name in test_modules:
        print(f"\n[RUNNING] {mod_name}...")
        t_mod = time.time()
        suite = unittest.defaultTestLoader.loadTestsFromName(mod_name)
        runner = unittest.TextTestRunner(verbosity=1)
        res = runner.run(suite)
        mod_elapsed = time.time() - t_mod
        suite_timings.append((mod_name, res.testsRun, mod_elapsed))
        annotate_failures(mod_name, res)
        total_tests += res.testsRun
        total_failures += len(res.failures)
        total_errors += len(res.errors)

    elapsed = time.time() - t0
    print("\n" + "=" * 65)
    print(f"VERIFICATION SUMMARY: {total_tests} tests in {elapsed:.2f}s")
    print(f"Failures: {total_failures} | Errors: {total_errors}")
    if suite_timings:
        slowest = sorted(suite_timings, key=lambda s: s[2], reverse=True)[:3]
        slow_lines = ", ".join(f"{name.split('.')[-1]} ({t:.1f}s)" for name, _, t in slowest)
        print(f"Top suites by duration: {slow_lines}")
    print("=" * 65)

    if total_failures == 0 and total_errors == 0:
        print(">>> ALL ARCHITECTURAL CHECKS & REGRESSIONS PASSED! [STATUS: GREEN]")
        return 0
    else:
        print(">>> SOME TESTS FAILED! [STATUS: RED]")
        return 1

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run MXB test suites.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--portable", action="store_true", help="only suites that run on any OS")
    group.add_argument("--windows", action="store_true", help="only the Windows hardware/integration suites")
    args = parser.parse_args()
    if args.portable:
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        import tests._stubs  # noqa: F401  (stand-ins for Windows-only packages off Windows)
    sys.exit(run_all_verifications("portable" if args.portable else "windows" if args.windows else "all"))
