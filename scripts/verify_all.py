import sys
import time
import unittest
from pathlib import Path

# Set up project root in sys.path
root_dir = Path(__file__).parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

def run_all_verifications():
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
        "tests.test_v4_automation"
    ]

    total_tests = 0
    total_failures = 0
    total_errors = 0
    t0 = time.time()

    for mod_name in test_modules:
        print(f"\n[RUNNING] {mod_name}...")
        suite = unittest.defaultTestLoader.loadTestsFromName(mod_name)
        runner = unittest.TextTestRunner(verbosity=1)
        res = runner.run(suite)
        total_tests += res.testsRun
        total_failures += len(res.failures)
        total_errors += len(res.errors)

    elapsed = time.time() - t0
    print("\n" + "=" * 65)
    print(f"VERIFICATION SUMMARY: {total_tests} tests in {elapsed:.2f}s")
    print(f"Failures: {total_failures} | Errors: {total_errors}")
    print("=" * 65)

    if total_failures == 0 and total_errors == 0:
        print(">>> ALL ARCHITECTURAL CHECKS & REGRESSIONS PASSED! [STATUS: GREEN]")
        return 0
    else:
        print(">>> SOME TESTS FAILED! [STATUS: RED]")
        return 1

if __name__ == "__main__":
    sys.exit(run_all_verifications())
