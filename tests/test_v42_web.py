"""
v4.2 MXB browser (Playwright). The browser tests drive a real headless Chrome/Edge against local
pages; they skip when no browser is available. Override with MXB_TEST_BROWSER=chrome|msedge|chromium.
"""
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from engine.web import WebController, describe, normalize_url, press_combo
from safety.injection import ALWAYS_DENIED, detect_injection, scope_for_goal, scoped, wrap_untrusted

FIXTURES = Path(__file__).resolve().parent.parent / "bench" / "fixtures"


def _channel() -> str:
    if os.environ.get("MXB_TEST_BROWSER"):
        return os.environ["MXB_TEST_BROWSER"]
    return "msedge" if sys.platform == "win32" else "chrome"


class TestWebLogic(unittest.TestCase):
    def test_normalize_url(self):
        self.assertEqual(normalize_url("github.com"), "https://github.com")
        self.assertEqual(normalize_url("docs.python.org/3/library"), "https://docs.python.org/3/library")
        self.assertEqual(normalize_url("https://x.dev/a?b=1"), "https://x.dev/a?b=1")
        self.assertEqual(normalize_url("file:///C:/a.html"), "file:///C:/a.html")
        self.assertEqual(normalize_url("localhost:8000"), "http://localhost:8000")
        self.assertIsNone(normalize_url("python tutorials"))
        self.assertIsNone(normalize_url(""))

    def test_press_combo(self):
        self.assertEqual(press_combo("enter"), "Enter")
        self.assertEqual(press_combo("ctrl+shift+t"), "Control+Shift+T")
        self.assertEqual(press_combo("alt + f4"), "Alt+F4")
        self.assertEqual(press_combo("esc"), "Escape")

    def test_describe(self):
        self.assertEqual(describe({"id": 3, "role": "textbox", "name": "Password", "tag": "input", "password": True}),
                         "[3] textbox 'Password' (password)")
        self.assertIn("(checked)", describe({"id": 1, "role": "checkbox", "name": "Remember", "tag": "input", "checked": True}))
        self.assertIn("= 'cats'", describe({"id": 2, "role": "textbox", "name": "Search", "tag": "input", "value": "cats"}))

    def test_label_for_uses_last_listing(self):
        w = WebController({})
        w.elements = {7: {"id": 7, "name": "Send"}}
        self.assertEqual(w.label_for("7"), "Send")
        self.assertEqual(w.label_for("[7]"), "Send")
        self.assertEqual(w.label_for("Sign in :: x"), "Sign in")
        self.assertEqual(w.label_for("9"), "")

    def test_unknown_action(self):
        self.assertIn("Unknown browser action", WebController({}).handle("web_dance"))


class TestWebScope(unittest.TestCase):
    def test_agent_rules_cover_the_browser(self):
        scope = scope_for_goal("search github for playwright examples")
        self.assertEqual(scope.check("web_open", "github.com")[0], "allow")
        self.assertEqual(scope.check("web_open", "evil.example.com")[0], "confirm")
        self.assertEqual(scope.check("web_search", "playwright examples")[0], "allow")
        self.assertEqual(scope.check("web_search", "how to wire money")[0], "confirm")
        self.assertEqual(scope.check("web_fill", "3 :: playwright")[0], "allow")
        self.assertEqual(scope.check("web_fill", "3 :: my password is hunter2")[0], "confirm")
        self.assertEqual(scope.check("web_click", "4", label="Send")[0], "confirm")
        self.assertEqual(scope.check("web_click", "4", label="Next page")[0], "allow")
        self.assertEqual(scope.check("web_close")[0], "deny")
        self.assertIn("web_close", ALWAYS_DENIED)
        scope.mark_suspicious(["exfiltration"])
        self.assertEqual(scope.check("web_read")[0], "allow")
        self.assertEqual(scope.check("web_elements")[0], "allow")
        self.assertEqual(scope.check("web_click", "2", label="Docs")[0], "confirm")

    def test_executor_routes_and_checks_risky_web_buttons(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        from engine.executor import OSExecutionManager
        ex = OSExecutionManager(config={})
        ex.audit = MagicMock()
        ex._web = MagicMock()
        ex._web.handle.return_value = "Clicked Send."
        ex._web.label_for.return_value = "Send"
        asked = []
        ex.confirm_callback = lambda q: (asked.append(q), False)[1]
        with scoped(scope_for_goal("search for cats")):
            res = ex.execute_action("web_click", "4")
        self.assertTrue(res.startswith("Cancelled"), res)
        self.assertIn("'Send'", asked[0])
        ex._web.handle.assert_not_called()
        self.assertEqual(ex.execute_action("web_click", "4"), "Clicked Send.")   # direct command: no question
        ex._web.handle.assert_called_with("web_click", "4")


class TestWebRouting(unittest.TestCase):
    def test_voice_phrases(self):
        from bench.routing import run_routing
        res = run_routing(cases=[("browse to github.com", "web_open", "github.com", "web"),
                                 ("open wikipedia.org in mxb browser", "web_open", "wikipedia.org", "web"),
                                 ("close mxb browser", "web_close", "", "web"),
                                 ("web click 7", "web_click", "7", "web"),
                                 ("list mcp tools", "mcp_tools", "", "mcp"),
                                 ("visually click the gear icon", "click_visual", "gear icon", "screen"),
                                 ("where is the recycle bin on the screen", "locate_visual", "recycle bin", "screen"),
                                 ("speak in kannada", "set_language", "kannada", "voice")])
        bad = [r for r in res["rows"] if r["outcome"] != "correct"]
        self.assertEqual(bad, [])
        folder = run_routing(cases=[("browse the downloads folder", "LLM", None, "files")])["rows"][0]
        self.assertNotEqual(folder.get("got"), "web_open")


class TestRealBrowser(unittest.TestCase):
    """Real Playwright against local pages (headless)."""

    @classmethod
    def setUpClass(cls):
        try:
            import playwright.sync_api  # noqa: F401
        except ImportError:
            raise unittest.SkipTest("playwright not installed")
        cls.tmp = tempfile.mkdtemp()
        cls.web = WebController({"web": {"browser": _channel(), "headless": True, "profile_dir": cls.tmp,
                                          "timeout_ms": 8000}})
        first = cls.web.handle("web_open", "about:blank")
        if first.startswith(("I couldn't start a browser", "Browser control needs", "Browser error")):
            raise unittest.SkipTest(f"no browser here: {first[:120]}")
        cls.pages = Path(cls.tmp) / "pages"
        cls.pages.mkdir()
        (cls.pages / "login.html").write_text(
            "<html><head><title>Login</title></head><body><label for=u>User</label><input id=u>"
            "<label for=p>Password</label><input id=p type=password><button>Sign in</button></body></html>",
            encoding="utf-8")
        (cls.pages / "links.html").write_text(
            f"<html><head><title>Links</title></head><body><a href='{(FIXTURES / 'click.html').as_uri()}' "
            "target='_blank'>Open the click page</a><p>Some article text about MXB.</p></body></html>", encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.web.close()

    def title(self):
        return self.web._call(lambda: self.web._page.title())

    def test_numbers_clicks_by_number_and_text(self):
        self.assertIn("Opened MXB Bench Click", self.web.handle("web_open", (FIXTURES / "click.html").as_uri()))
        listing = self.web.handle("web_elements")
        self.assertIn("[1] button 'Alpha'", listing)
        self.assertIn("[3] button 'Gamma'", listing)
        self.assertEqual(self.web.handle("web_click", "2"), "Clicked Beta.")
        self.assertEqual(self.title(), "Clicked: Beta")
        self.web.handle("web_click", "gamma")
        self.assertEqual(self.title(), "Clicked: Gamma")
        self.assertIn("no element 99", self.web.handle("web_click", "99"))
        self.assertIn("can't find 'Delta'", self.web.handle("web_click", "Delta"))

    def test_form_fill_submit_and_enter(self):
        self.web.handle("web_open", (FIXTURES / "form.html").as_uri())
        self.assertEqual(self.web.handle("web_fill", "Name :: Srinivas"), "Typed into Name.")
        self.web.handle("web_fill", "2 :: Bengaluru")
        self.web.handle("web_click", "Submit")
        self.assertEqual(self.title(), "Submitted: Srinivas, Bengaluru")
        self.web.handle("web_open", (FIXTURES / "search.html").as_uri())
        self.web.handle("web_fill", "1 :: python tutorials")
        self.assertEqual(self.web.handle("web_press", "enter"), "Pressed Enter.")
        self.assertEqual(self.title(), "Searched: python tutorials")

    def test_never_types_passwords(self):
        self.web.handle("web_open", (self.pages / "login.html").as_uri())
        self.assertIn("(password)", self.web.handle("web_elements"))
        self.assertIn("don't type passwords", self.web.handle("web_fill", "Password :: hunter2"))
        self.assertIn("don't type passwords", self.web.handle("web_fill", "2 :: hunter2"))
        value = self.web._call(lambda: self.web._page.eval_on_selector("#p", "e => e.value"))
        self.assertEqual(value, "")
        self.assertEqual(self.web.handle("web_fill", "User :: srinivas"), "Typed into User.")

    def test_new_tab_link_becomes_current_and_tabs(self):
        self.web.handle("web_open", (self.pages / "links.html").as_uri())
        self.assertIn("article text", self.web.handle("web_read"))
        self.web.handle("web_click", "Open the click page")
        self.web._call(lambda: self.web._page.wait_for_load_state())
        self.assertEqual(self.title(), "MXB Bench Click")
        tabs = self.web.handle("web_tabs")
        self.assertIn("(current) MXB Bench Click", tabs)
        self.assertIn("Links", tabs)
        self.assertIn("Switched to Links", self.web.handle("web_switch_tab", "1"))
        self.assertIn("Closed", self.web.handle("web_close_tab", "2"))
        self.assertNotIn("MXB Bench Click", self.web.handle("web_tabs"))

    def test_agent_sees_page_inside_the_untrusted_fence(self):
        from engine.agent_loop import AgentLoop
        secret = Path(self.tmp) / "secret.txt"
        page = (FIXTURES / "injection.html.tmpl").read_text(encoding="utf-8").replace("{{SECRET_PATH}}", str(secret))
        (self.pages / "inject.html").write_text(page, encoding="utf-8")
        self.web.handle("web_open", (self.pages / "inject.html").as_uri())
        obs = {"window": "Edge", "marks": {}, "text": "", "web": self.web.observe()}
        self.assertTrue(obs["web"]["elements"])
        prompt = AgentLoop.build_prompt("summarize this page", [], obs, [])
        fence_start, fence_end = prompt.index("<<UNTRUSTED screen"), prompt.rindex("<<END")
        self.assertTrue(fence_start < prompt.index("MXB BROWSER PAGE") < fence_end)
        self.assertTrue(detect_injection(AgentLoop.haystack(obs)))

    def test_parallel_calls_are_serialized_on_one_thread(self):
        self.web.handle("web_open", (FIXTURES / "click.html").as_uri())
        results, threads = [], []
        for _ in range(4):
            t = threading.Thread(target=lambda: results.append(self.web.handle("web_elements")))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(30)
        self.assertEqual(len(results), 4)
        self.assertTrue(all("[2] button 'Beta'" in r for r in results))


class TestFenceHelper(unittest.TestCase):
    def test_page_text_wrap(self):
        self.assertTrue(wrap_untrusted("hello", "web page").startswith("<<UNTRUSTED web page "))


if __name__ == "__main__":
    unittest.main()
