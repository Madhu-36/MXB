"""v4.2 MCP client: a real stdio MCP server subprocess (tests/fixtures/mcp_test_server.py) plus pure logic."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import tests._stubs  # noqa: F401
from engine.actions_catalog import get_spec
from engine.mcp_client import (
    MCPError, action_name, expand_env, format_result, load_server_specs, parse_arguments, schema_summary, tool_risk,
)
from safety.injection import scope_for_goal

SERVER = str(Path(__file__).resolve().parent / "fixtures" / "mcp_test_server.py")


def _have_mcp() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


class TestMCPLogic(unittest.TestCase):
    SCHEMA = {"type": "object", "properties": {"a": {"type": "integer"}, "b": {"type": "integer"}}, "required": ["a", "b"]}

    def test_names_and_schema_summary(self):
        self.assertEqual(action_name("My GitHub", "list-issues"), "mcp__my_github__list_issues")
        self.assertEqual(schema_summary(self.SCHEMA), 'JSON {"a": integer (required), "b": integer (required)}')
        self.assertEqual(schema_summary({}), '""')

    def test_argument_parsing(self):
        one = {"properties": {"limit": {"type": "integer"}}, "required": ["limit"]}
        flag = {"properties": {"on": {"type": "boolean"}}}
        self.assertEqual(parse_arguments('{"a": 1, "b": 2}', self.SCHEMA), {"a": 1, "b": 2})
        self.assertEqual(parse_arguments("5", one), {"limit": 5})
        self.assertEqual(parse_arguments("yes", flag), {"on": True})
        self.assertEqual(parse_arguments("", self.SCHEMA), {})
        with self.assertRaisesRegex(MCPError, "needs its arguments as JSON"):
            parse_arguments("5", self.SCHEMA)
        with self.assertRaisesRegex(MCPError, "aren't valid JSON"):
            parse_arguments('{"a": 1', self.SCHEMA)
        with self.assertRaisesRegex(MCPError, "isn't a valid integer"):
            parse_arguments("five", one)

    def test_result_formatting(self):
        ok = {"content": [{"type": "text", "text": "hello"}, {"type": "image"}, {"type": "resource_link", "uri": "file:///a"}]}
        self.assertEqual(format_result(ok), "hello\n[image]\nfile:///a")
        self.assertEqual(format_result({"content": [], "structured_content": {"n": 3}}), '{"n": 3}')
        self.assertEqual(format_result({"content": [{"type": "text", "text": "bad"}], "isError": True}),
                         "The tool reported an error: bad")
        self.assertTrue(format_result({"content": [{"type": "text", "text": "x" * 5000}]}).endswith("…(truncated)"))
        self.assertEqual(format_result({"content": []}), "(the tool returned nothing)")

    def test_error_text_formatting(self):
        from engine.mcp_client import MCPManager
        self.assertIn("executable not found", MCPManager._error_text(FileNotFoundError(2, "No such file", "server.exe")))
        self.assertEqual(MCPManager._error_text(BrokenPipeError("Pipe closed")), "server closed connection unexpectedly")
        self.assertEqual(MCPManager._error_text(ProcessLookupError()), "server process terminated prematurely")
        self.assertEqual(MCPManager._error_text(TimeoutError()), "server timed out")

    def test_trust_levels(self):
        ro = {"name": "t", "annotations": {"read_only_hint": True}}
        destructive = {"name": "t", "annotations": {"readOnlyHint": False, "destructiveHint": True}}
        unknown = {"name": "t"}
        self.assertEqual([tool_risk("ask", t) for t in (ro, destructive, unknown)], ["confirm"] * 3)
        self.assertEqual([tool_risk("read_only", t) for t in (ro, destructive, unknown)], ["safe", "confirm", "confirm"])
        self.assertEqual([tool_risk("auto", t) for t in (ro, destructive, unknown)], ["safe", "confirm", "safe"])

    def test_config_loading_and_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            desktop = Path(tmp) / "claude_desktop_config.json"
            desktop.write_text(json.dumps({"mcpServers": {"fs": {"command": "npx"}, "old": {"command": "x", "disabled": True}}}))
            specs = load_server_specs({"mcp": {"claude_desktop_config": str(desktop),
                                               "servers": {"gh": {"url": "https://example.com/mcp"}}}})
        self.assertEqual(sorted(specs), ["fs", "gh"])
        with patch.dict(os.environ, {"MXB_T_TOKEN": "abc"}):
            self.assertEqual(expand_env({"h": ["Bearer ${MXB_T_TOKEN}"], "n": 3}), {"h": ["Bearer abc"], "n": 3})
        self.assertEqual(load_server_specs({}), {})

    def test_policy_question_and_agent_scope(self):
        from safety.policy import SafetyPolicy
        from engine.actions_catalog import ActionSpec, register_dynamic, unregister_dynamic
        register_dynamic(ActionSpec("mcp__github__create_issue", "JSON", "[github] Create an issue", "mcp", risk="confirm"))
        try:
            q = SafetyPolicy({}).confirmation_reason("mcp__github__create_issue", '{"title": "bug"}')
            self.assertEqual(q, 'Use the github tool \'create_issue\' with {"title": "bug"}?')
            self.assertIn("mcp__github__create_issue", scope_for_goal("using github, file an issue about the crash").allowed)
            self.assertNotIn("mcp__github__create_issue", scope_for_goal("search youtube for cats").allowed)
        finally:
            unregister_dynamic("mcp__github__create_issue")


@unittest.skipUnless(_have_mcp(), "MCP SDK not installed")
class TestMCPLive(unittest.TestCase):
    """A real MCP server over stdio."""

    def setUp(self):
        for target in ("MouseController", "KeyboardExtended", "ScreenVision", "SmartAppLauncher"):
            p = patch(f"engine.executor.{target}")
            p.start()
            self.addCleanup(p.stop)
        from engine.executor import OSExecutionManager
        cfg = {"mcp": {"servers": {"test": {"command": sys.executable, "args": [SERVER], "trust": "read_only"},
                                   "broken": {"command": "definitely-not-a-real-binary-mxb"}}}}
        self.ex = OSExecutionManager(config=cfg)
        self.ex.audit = MagicMock()
        self.questions, self.answer = [], False
        self.ex.confirm_callback = lambda q: (self.questions.append(q), self.answer)[1]
        self.ex.mcp.connect_timeout = 30
        self.addCleanup(self.ex.shutdown)
        self.status = self.ex.execute_action("mcp_tools")

    def test_connects_lists_and_reports_broken_server(self):
        self.assertIn("test: connected (5 tools) — echo, add, read_note, delete_note, explode", self.status)
        self.assertIn("broken: failed:", self.status)
        self.assertEqual(get_spec("mcp__test__echo").risk, "safe")
        self.assertEqual(get_spec("mcp__test__delete_note").risk, "confirm")
        self.assertEqual(get_spec("mcp__test__explode").risk, "confirm")   # no hints: may change things
        self.assertIn("[test] Add two integers.", get_spec("mcp__test__add").description)

    def test_calls_through_the_executor(self):
        self.assertEqual(self.ex.execute_action("mcp__test__echo", "hello there"), "echo: hello there")
        self.assertEqual(self.ex.execute_action("mcp__test__add", '{"a": 2, "b": 40}'), "42")
        self.assertIn("needs its arguments as JSON", self.ex.execute_action("mcp__test__add", "5"))
        self.assertEqual(self.questions, [])                                  # read-only tools never ask
        self.answer = True
        self.assertIn("reported an error", self.ex.execute_action("mcp__test__explode", ""))

    def test_destructive_tool_needs_a_yes(self):
        res = self.ex.execute_action("mcp__test__delete_note", "groceries")
        self.assertTrue(res.startswith("Cancelled"), res)
        self.assertEqual(self.questions[-1], "Use the test tool 'delete_note' with groceries?")
        self.assertEqual(self.ex.execute_action("mcp__test__read_note", "groceries"), "milk, eggs")
        self.answer = True
        self.assertEqual(self.ex.execute_action("mcp__test__delete_note", "groceries"), "deleted")
        self.assertIn("no note called groceries", self.ex.execute_action("mcp__test__read_note", "groceries"))

    def test_reload_and_close_unregister(self):
        self.assertIn("connected", self.ex.execute_action("mcp_reload"))
        self.ex.mcp.close()
        self.assertIsNone(get_spec("mcp__test__echo"))
        self.assertNotIn("mcp__test__echo", self.ex.extension_handlers)
        self.assertIn("not supported", self.ex.execute_action("mcp__test__echo", "x"))


if __name__ == "__main__":
    unittest.main()
