"""
MCP client: MXB can use the tools of any Model Context Protocol server (files, GitHub, Notion,
Slack, databases, Spotify, home automation...) by voice or text.

config.json -> "mcp":
    "mcp": {
      "enabled": true,
      "servers": {
        "github":  {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}"}, "trust": "read_only"},
        "notion":  {"url": "https://mcp.notion.com/mcp", "headers": {"Authorization": "Bearer ${NOTION_TOKEN}"}}
      },
      "claude_desktop_config": false     # true (or a path): also load servers from Claude Desktop's config
    }
${VAR} in command, args, env, url and headers is filled from the environment (or MXB's .env).

Safety:
- Every tool becomes an action "mcp__<server>__<tool>". By default each call asks you first
  ("trust": "ask"). "read_only" runs tools that declare readOnlyHint without asking; "auto" runs
  everything except tools that declare destructiveHint. Unknown means "may change things".
- In agent (screen) tasks, only servers that your goal names are available at all.
- Tool output is untrusted data whenever it is given to an LLM.

One asyncio loop runs on a background thread. Each server lives in one long-running task that
enters and exits its transport in the same task (the SDK's anyio task groups require that).
"""
import asyncio
import json
import os
import re
import threading
from contextlib import AsyncExitStack
from pathlib import Path

from utils.logger import log

TRUST_LEVELS = ("ask", "read_only", "auto")
MAX_RESULT_CHARS = 4000


class MCPError(Exception):
    """User-facing MCP problem."""


def sanitize(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9_]", "_", (name or "").lower())).strip("_") or "x"


def action_name(server: str, tool: str) -> str:
    return f"mcp__{sanitize(server)}__{sanitize(tool)}"


def _attr(obj, *names, default=None):
    """Reads a field from MCP SDK v2 (snake_case) or v1 (camelCase) models, or plain dicts."""
    for n in names:
        if isinstance(obj, dict) and n in obj:
            return obj[n]
        if hasattr(obj, n):
            value = getattr(obj, n)
            if value is not None:
                return value
    return default


def expand_env(value):
    """'${TOKEN}' -> os.environ['TOKEN'] (recursively through lists and dicts)."""
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ.get(m.group(1), ""), value)
    if isinstance(value, list):
        return [expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: expand_env(v) for k, v in value.items()}
    return value


def claude_desktop_servers(path: str | Path | None = None) -> dict:
    """Servers from Claude Desktop's claude_desktop_config.json ("mcpServers"), if present."""
    if path in (None, True, ""):
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / "Claude" / "claude_desktop_config.json"
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return dict(data.get("mcpServers") or {})
    except Exception:
        return {}


def load_server_specs(config: dict) -> dict[str, dict]:
    cfg = (config or {}).get("mcp", {}) or {}
    servers: dict[str, dict] = {}
    desktop = cfg.get("claude_desktop_config")
    if desktop:
        servers.update(claude_desktop_servers(None if desktop is True else desktop))
    servers.update(cfg.get("servers") or {})
    return {name: spec for name, spec in servers.items() if isinstance(spec, dict) and not spec.get("disabled")}


def schema_summary(schema: dict, limit: int = 6) -> str:
    props = (schema or {}).get("properties") or {}
    if not props:
        return '""'
    required = set((schema or {}).get("required") or [])
    parts = []
    for i, (key, info) in enumerate(props.items()):
        if i >= limit:
            parts.append("...")
            break
        kind = (info or {}).get("type", "any")
        if isinstance(kind, list):
            kind = "|".join(map(str, kind))
        parts.append(f'"{key}": {kind}{" (required)" if key in required else ""}')
    return "JSON {" + ", ".join(parts) + "}"


def _coerce(value: str, kind):
    kind = kind[0] if isinstance(kind, list) and kind else kind
    try:
        if kind == "integer":
            return int(value)
        if kind == "number":
            return float(value)
        if kind == "boolean":
            return value.strip().lower() in ("true", "yes", "1", "on")
        if kind in ("array", "object"):
            return json.loads(value)
    except (ValueError, json.JSONDecodeError):
        raise MCPError(f"'{value}' isn't a valid {kind}.")
    return value


def parse_arguments(target: str, schema: dict) -> dict:
    """JSON object, or plain text when the tool takes exactly one (required) parameter."""
    t = (target or "").strip()
    if not t or t in ('""', "{}"):
        return {}
    if t.startswith("{"):
        try:
            data = json.loads(t)
        except json.JSONDecodeError as e:
            raise MCPError(f"Those tool arguments aren't valid JSON ({e.msg}).")
        if not isinstance(data, dict):
            raise MCPError("Tool arguments must be a JSON object.")
        return data
    props = (schema or {}).get("properties") or {}
    required = list((schema or {}).get("required") or [])
    names = required if len(required) == 1 else (list(props) if len(props) == 1 else [])
    if names:
        key = names[0]
        return {key: _coerce(t, (props.get(key) or {}).get("type", "string"))}
    raise MCPError(f"This tool needs its arguments as JSON: {schema_summary(schema)}")


def format_result(result) -> str:
    parts = []
    for item in _attr(result, "content", default=[]) or []:
        kind = _attr(item, "type", default="")
        if kind == "text":
            parts.append(str(_attr(item, "text", default="")))
        elif kind == "image":
            parts.append("[image]")
        elif kind == "audio":
            parts.append("[audio]")
        elif kind == "resource":
            res = _attr(item, "resource", default=None)
            parts.append(str(_attr(res, "text", default="") or _attr(res, "uri", default="[resource]")))
        elif kind == "resource_link":
            parts.append(str(_attr(item, "uri", default="[link]")))
    text = "\n".join(p for p in parts if p).strip()
    if not text:
        structured = _attr(result, "structured_content", "structuredContent", default=None)
        if structured is not None:
            text = json.dumps(structured, ensure_ascii=False, default=str)
    text = text or "(the tool returned nothing)"
    if len(text) > MAX_RESULT_CHARS:
        text = text[:MAX_RESULT_CHARS] + " …(truncated)"
    if _attr(result, "is_error", "isError", default=False):
        return f"The tool reported an error: {text}"
    return text


def tool_risk(trust: str, tool) -> str:
    ann = _attr(tool, "annotations", default=None)
    read_only = _attr(ann, "read_only_hint", "readOnlyHint", default=None) is True
    destructive = _attr(ann, "destructive_hint", "destructiveHint", default=None) is True
    if trust == "auto":
        return "confirm" if destructive else "safe"
    if trust == "read_only":
        return "safe" if read_only and not destructive else "confirm"
    return "confirm"


class MCPManager:
    def __init__(self, config: dict | None = None, register=None, unregister=None, handlers: dict | None = None,
                 connect_timeout: float = 45.0, call_timeout: float = 120.0):
        from engine.actions_catalog import register_dynamic, unregister_dynamic
        self.config = config or {}
        self._register = register or register_dynamic
        self._unregister = unregister or unregister_dynamic
        self.handlers = handlers if handlers is not None else {}
        self.connect_timeout = connect_timeout
        self.call_timeout = call_timeout
        self.default_trust = (self.config.get("mcp", {}) or {}).get("trust", "ask")
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self.sessions: dict[str, object] = {}
        self.tools: dict[str, list] = {}
        self.status: dict[str, str] = {}
        self.actions: dict[str, tuple[str, str, dict]] = {}   # action -> (server, tool, input schema)
        self._stops: dict[str, asyncio.Event] = {}
        self._tasks: dict[str, object] = {}
        self._lock = threading.Lock()
        self._errlog_file = None
        self.started = False

    # ------------------------------------------------------------------ loop thread
    def _ensure_loop(self):
        if self._loop is not None and self._thread is not None and self._thread.is_alive():
            return
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, name="mxb-mcp", daemon=True)
        self._thread.start()

    def _run(self, coro, timeout: float):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result(timeout)

    # ------------------------------------------------------------------ transports
    def _transport(self, spec: dict):
        spec = expand_env(spec)
        if spec.get("url"):
            headers = dict(spec.get("headers") or {})
            try:   # MCP SDK 2.x
                from mcp.client.streamable_http import streamable_http_client, create_mcp_http_client
                return streamable_http_client(spec["url"], http_client=create_mcp_http_client(headers=headers))
            except ImportError:   # MCP SDK 1.x
                from mcp.client.streamable_http import streamablehttp_client
                return streamablehttp_client(spec["url"], headers=headers)
        if not spec.get("command"):
            raise MCPError("Each MCP server needs either a 'command' or a 'url'.")
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client
        env = dict(os.environ)
        env.update({k: str(v) for k, v in (spec.get("env") or {}).items()})
        params = StdioServerParameters(command=spec["command"], args=[str(a) for a in spec.get("args", [])],
                                       env=env, cwd=spec.get("cwd") or None)
        return stdio_client(params, errlog=self._errlog())

    def _errlog(self):
        """Servers' stderr (their own logs, tracebacks) goes to logs/mcp-servers.log, not MXB's console."""
        if self._errlog_file is None or self._errlog_file.closed:
            try:
                from utils.paths import logs_dir
                self._errlog_file = open(logs_dir() / "mcp-servers.log", "a", encoding="utf-8", buffering=1)
            except Exception:
                self._errlog_file = open(os.devnull, "w", encoding="utf-8")
        return self._errlog_file

    async def _serve(self, name: str, spec: dict, ready: asyncio.Future):
        from mcp import ClientSession
        try:
            async with AsyncExitStack() as stack:
                streams = await stack.enter_async_context(self._transport(spec))
                read, write = streams[0], streams[1]     # SDK 1.x HTTP yields a third item
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
                tools, cursor = [], None
                while True:
                    if cursor:
                        try:
                            from mcp.types import PaginatedRequestParams
                            page = await session.list_tools(params=PaginatedRequestParams(cursor=cursor))
                        except (ImportError, TypeError):
                            page = await session.list_tools(cursor=cursor)
                    else:
                        page = await session.list_tools()
                    tools.extend(_attr(page, "tools", default=[]) or [])
                    cursor = _attr(page, "next_cursor", "nextCursor", default=None)
                    if not cursor or len(tools) > 500:
                        break
                self.sessions[name] = session
                self.tools[name] = tools
                if not ready.done():
                    ready.set_result(len(tools))
                await self._stops[name].wait()
        except BaseException as e:   # includes ExceptionGroup from anyio
            if not ready.done():
                ready.set_exception(e if isinstance(e, Exception) else RuntimeError(str(e)))
            else:
                log.warning(f"MCP: server '{name}' stopped: {e}")
        finally:
            self.sessions.pop(name, None)

    @staticmethod
    def _error_text(e: BaseException) -> str:
        inner = getattr(e, "exceptions", None)
        if inner:
            return MCPManager._error_text(inner[0])
        if isinstance(e, FileNotFoundError):
            return f"executable not found: {e.filename or e}"
        if isinstance(e, (BrokenPipeError, ConnectionResetError)):
            return "server closed connection unexpectedly"
        if isinstance(e, ProcessLookupError):
            return "server process terminated prematurely"
        if isinstance(e, (asyncio.TimeoutError, TimeoutError)):
            return "server timed out"
        return (str(e).strip().splitlines() or [type(e).__name__])[0][:200] or type(e).__name__

    async def _start_one(self, name: str, spec: dict):
        self._stops[name] = asyncio.Event()
        ready = asyncio.get_running_loop().create_future()
        self._tasks[name] = asyncio.ensure_future(self._serve(name, spec, ready))
        return await asyncio.wait_for(ready, self.connect_timeout)

    # ------------------------------------------------------------------ public API
    def start(self) -> str:
        """Connects to every configured server and registers its tools. Safe to call again."""
        with self._lock:
            if self.started:
                return self.describe()
            specs = load_server_specs(self.config)
            if not specs:
                self.started = True
                return "No MCP servers are configured. Add them under \"mcp\" → \"servers\" in config.json."
            try:
                import mcp  # noqa: F401
            except ImportError:
                return "MCP needs the MCP Python SDK: pip install mcp"
            self._ensure_loop()
            for name, spec in specs.items():
                try:
                    count = self._run(self._start_one(name, spec), self.connect_timeout + 5)
                    self.status[name] = f"connected ({count} tools)"
                    trust = spec.get("trust", self.default_trust)
                    self._register_tools(name, trust if trust in TRUST_LEVELS else "ask")
                except Exception as e:
                    self.status[name] = f"failed: {self._error_text(e)}"
                    log.warning(f"MCP: couldn't connect to '{name}': {self._error_text(e)}")
                    stop = self._stops.get(name)
                    if stop is not None:
                        self._loop.call_soon_threadsafe(stop.set)
            self.started = True
            return self.describe()

    def _register_tools(self, server: str, trust: str):
        from engine.actions_catalog import ActionSpec
        for tool in self.tools.get(server, []):
            tool_name = _attr(tool, "name", default="")
            schema = _attr(tool, "input_schema", "inputSchema", default={}) or {}
            if hasattr(schema, "model_dump"):
                schema = schema.model_dump()
            action = action_name(server, tool_name)
            desc = str(_attr(tool, "title", default="") or _attr(tool, "description", default="") or tool_name)
            desc = re.split(r"(?<=[.!?])\s", desc.strip(), 1)[0][:140]
            spec = ActionSpec(action, schema_summary(schema), f"[{server}] {desc}", "mcp", risk=tool_risk(trust, tool))
            self._register(spec)
            self.actions[action] = (server, tool_name, schema)
            self.handlers[action] = lambda target, a=action: self.call_action(a, target)

    def call_action(self, action: str, target: str) -> str:
        server, tool, schema = self.actions.get(action, (None, None, None))
        if server is None:
            return f"The tool {action} isn't available."
        try:
            args = parse_arguments(target, schema)
        except MCPError as e:
            return str(e)
        return self.call(server, tool, args)

    def call(self, server: str, tool: str, arguments: dict | None = None) -> str:
        session = self.sessions.get(server)
        if session is None:
            return f"The {server} MCP server isn't connected. Say 'reload MCP' to reconnect."
        try:
            result = self._run(session.call_tool(tool, arguments or {}), self.call_timeout)
        except TimeoutError:
            return f"The {server} tool '{tool}' didn't answer within {int(self.call_timeout)} seconds."
        except Exception as e:
            return f"The {server} tool '{tool}' failed: {self._error_text(e)}"
        return format_result(result)

    def describe(self) -> str:
        if not self.status:
            return "No MCP servers are configured."
        lines = []
        for server, state in self.status.items():
            names = [_attr(t, "name", default="?") for t in self.tools.get(server, [])] if state.startswith("connected") else []
            shown = ", ".join(names[:12]) + (f" and {len(names) - 12} more" if len(names) > 12 else "")
            lines.append(f"{server}: {state}" + (f" — {shown}" if shown else ""))
        return "\n".join(lines)

    def close(self):
        with self._lock:
            for action in list(self.actions):
                self._unregister(action)
                self.handlers.pop(action, None)
            self.actions.clear()
            if self._loop is not None:
                for stop in self._stops.values():
                    self._loop.call_soon_threadsafe(stop.set)
                tasks = [t for t in self._tasks.values()]
                if tasks:
                    try:
                        self._run(asyncio.wait(tasks, timeout=10), 15)
                    except Exception:
                        pass
                self._loop.call_soon_threadsafe(self._loop.stop)
                if self._thread is not None:
                    self._thread.join(5)
                try:
                    self._loop.close()
                except Exception:
                    pass
            self._loop = self._thread = None
            self.sessions.clear()
            self.tools.clear()
            self.status.clear()
            self._stops.clear()
            self._tasks.clear()
            if self._errlog_file is not None:
                try:
                    self._errlog_file.close()
                except Exception:
                    pass
                self._errlog_file = None
            self.started = False

    def reload(self) -> str:
        self.close()
        return self.start()
