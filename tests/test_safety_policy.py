"""Safety policy, confirmation handshake and action catalog consistency."""
import re
import threading
import time
import unittest
from pathlib import Path

import tests._stubs  # noqa: F401
from engine.actions_catalog import CATALOG, action_names, risk_of, planner_system_prompt, uses_input
from safety.policy import SafetyPolicy, ConfirmationManager, classify_answer

ROOT = Path(__file__).parent.parent


class TestCatalog(unittest.TestCase):
    def test_names_unique(self):
        names = action_names(include_dynamic=False)
        self.assertEqual(len(names), len(set(names)))

    def test_every_catalog_action_is_handled_by_executor(self):
        source = (ROOT / "engine" / "executor.py").read_text(encoding="utf-8")
        from engine.web import WebController   # the executor delegates every web_* action to this table
        delegated = set(WebController.HANDLERS)
        missing = [n for n in action_names(include_dynamic=False)
                   if n != "wait" and n not in delegated and not re.search(rf'["\']{n}["\']', source)]
        self.assertEqual(missing, [], f"Executor does not handle: {missing}")
        broken = [a for a, method in WebController.HANDLERS.items() if not callable(getattr(WebController, method, None))]
        self.assertEqual(broken, [], f"Web handlers point at missing methods: {broken}")
        self.assertTrue(all(n.startswith("web_") for n in delegated))

    def test_destructive_actions_require_confirmation(self):
        for name in ("delete_file", "empty_recycle_bin", "kill_process", "power_action", "force_close_app",
                     "grant_file_access", "vault_get"):
            self.assertEqual(risk_of(name), "confirm", name)
        self.assertEqual(risk_of("open_app"), "safe")

    def test_input_flags(self):
        self.assertTrue(uses_input("type_text"))
        self.assertTrue(uses_input("search_on_screen"))
        self.assertFalse(uses_input("weather"))

    def test_prompt_lists_every_action(self):
        prompt = planner_system_prompt()
        for spec in CATALOG:
            self.assertIn(f'"{spec.name}"', prompt)


class TestPolicy(unittest.TestCase):
    def setUp(self):
        self.policy = SafetyPolicy({})

    def test_safe_action_needs_nothing(self):
        self.assertIsNone(self.policy.confirmation_reason("open_app", "notepad"))

    def test_recycle_vs_permanent_delete_wording(self):
        self.assertIn("Recycle Bin", self.policy.confirmation_reason("delete_file", "a.txt"))
        self.assertIn("cannot be undone", self.policy.confirmation_reason("delete_file", "a.txt :: permanent"))

    def test_overwrite_context(self):
        q = self.policy.confirmation_reason("create_file", "a.txt :: hi", {"overwrite": True, "path": "a.txt"})
        self.assertIn("Overwrite", q)

    def test_cancel_shutdown_is_safe(self):
        self.assertIsNone(self.policy.confirmation_reason("power_action", "cancel"))
        self.assertIsNotNone(self.policy.confirmation_reason("power_action", "shutdown"))

    def test_can_be_disabled(self):
        policy = SafetyPolicy({"safety": {"confirm_destructive": False}})
        self.assertIsNone(policy.confirmation_reason("delete_file", "a.txt"))


class TestAnswers(unittest.TestCase):
    def test_classify(self):
        for yes in ("yes", "Yes.", "yeah do it", "go ahead", "MXB yes", "confirm", "okay"):
            self.assertTrue(classify_answer(yes), yes)
        for no in ("no", "No!", "cancel", "don't", "nope", "no thanks"):
            self.assertFalse(classify_answer(no), no)
        for other in ("open chrome", "what is the weather", ""):
            self.assertIsNone(classify_answer(other), other)


class TestConfirmationManager(unittest.TestCase):
    def _ask_async(self, cm, **kw):
        result = {}
        t = threading.Thread(target=lambda: result.setdefault("v", cm.request("Delete?", **kw)))
        t.start()
        for _ in range(50):
            if cm.has_pending():
                break
            time.sleep(0.01)
        return t, result

    def test_yes_by_text(self):
        cm = ConfirmationManager(timeout=3)
        t, result = self._ask_async(cm)
        self.assertTrue(cm.answer_text("yes please"))
        t.join(2)
        self.assertTrue(result["v"])

    def test_no_by_button(self):
        cm = ConfirmationManager(timeout=3)
        t, result = self._ask_async(cm)
        self.assertTrue(cm.resolve(False))
        t.join(2)
        self.assertFalse(result["v"])

    def test_unrelated_text_not_consumed(self):
        cm = ConfirmationManager(timeout=3)
        t, result = self._ask_async(cm)
        self.assertIsNone(cm.answer_text("open notepad"))
        cm.cancel_pending()
        t.join(2)
        self.assertFalse(result["v"])

    def test_timeout_means_no(self):
        cm = ConfirmationManager(timeout=0.3)
        self.assertFalse(cm.request("Delete?"))
        self.assertFalse(cm.has_pending())

    def test_abort_event_cancels(self):
        cm = ConfirmationManager(timeout=5)
        ev = threading.Event()
        threading.Timer(0.2, ev.set).start()
        start = time.time()
        self.assertFalse(cm.request("Delete?", abort_event=ev))
        self.assertLess(time.time() - start, 2)

    def test_announce_called(self):
        cm = ConfirmationManager(timeout=0.2)
        heard = []
        cm.request("Shut down?", announce=heard.append)
        self.assertEqual(heard, ["Shut down?"])


if __name__ == "__main__":
    unittest.main()
