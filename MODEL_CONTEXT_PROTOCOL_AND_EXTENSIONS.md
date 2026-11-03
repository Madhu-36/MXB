# MXB V2.0 - Model Context Protocol (MCP) & Extensible Agent Architecture

## 1. Executive Summary & Open Extensibility Vision
As MXB transitions into an autonomous Operating System Second Brain, direct hardcoding of tools and API endpoints within the core engine creates monolithic technical debt and security risks. MXB V2.0 adopts the **Model Context Protocol (MCP)**—an open standard developed to standardize how AI systems interface with local tools, external data repositories, and operating system capabilities.

```
+---------------------------------------------------------------------------------------+
|                      MXB Model Context Protocol (MCP) Client Topology                 |
|                                                                                       |
|  [ Voice / Multimodal Input ] ---> [ Intent Router & Cognitive LLM Brain ]            |
|                                                  |                                    |
|                                                  v                                    |
|                                  [ Unified MCP Client Aggregator ]                    |
|                                                  |                                    |
|         +-----------------------+----------------+-----------------------+            |
|         | (Stdio Transport)     | (Stdio Transport)      | (SSE Transport)       |            |
|         v                       v                        v                       v            |
|   +-----------+          +---------------+         +------------+         +-------------+     |
|   | OS & Win32|          | Filesystem &  |         | SQLite Vec |         | Developer & |     |
|   | Automation|          | Local Vaults  |         | Database   |         | GitHub Tool |     |
|   | Server    |          | Server        |         | Server     |         | Server      |     |
|   +-----------+          +---------------+         +------------+         +-------------+     |
+---------------------------------------------------------------------------------------+
```

### Core Architectural Goals
- **Standardized Interoperability**: Decouples tool implementation from the LLM provider, supporting Ollama, NVIDIA NIM, and Anthropic backends transparently.
- **Subprocess Isolation**: Runs community and third-party tools in dedicated out-of-process workers with zero access to MXB's private memory space.
- **Dynamic Context Injection**: Exposes real-time local resources (files, active application states, database rows) as first-class context primitives.


## 2. JSON-RPC 2.0 Protocol Specifications
All communications across MXB's MCP client and connected servers strictly adhere to the **JSON-RPC 2.0** specification over UTF-8 encoded text streams.

### Core Message Primitives
- **Requests**: Messages requiring an explicit response from the recipient, containing a unique integer or string `id`.
- **Responses**: Messages returning either a `result` payload or an `error` object corresponding to a previous request `id`.
- **Notifications**: One-way telemetry and state signals that do not contain an `id` and expect no acknowledgement.

```json
// Sample Tool Call Request
{
  "jsonrpc": "2.0",
  "id": 1042,
  "method": "tools/call",
  "params": {
    "name": "read_desktop_window",
    "arguments": {
      "filter_active": true
    }
  }
}

// Sample Tool Call Success Response
{
  "jsonrpc": "2.0",
  "id": 1042,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Active Window: 'Visual Studio Code - mxb_app'"
      }
    ],
    "isError": false
  }
}
```


## 3. Stdio Transport Architecture
The standard input/output (`stdio`) transport is the default communication mechanism for local tools. MXB spawns MCP server executables as child subprocesses, establishing bi-directional communication through standard anonymous pipes (`stdin` and `stdout`).

```
[ MXB Host Process ]                                   [ MCP Child Process ]
  |                                                      |
  |--- write(JSON-RPC\n) ---> [ Child STDIN Pipe ] ------> Read & Process
  |                                                      |
  |<-- read(JSON-RPC\n) <---- [ Child STDOUT Pipe ] <---- Emit Response
  |                                                      |
  |<-- stderr logging <------ [ Child STDERR Pipe ] <---- Diagnostic Logs
```

### Pipe Management Implementation
```python
import subprocess
import json

class StdioTransport:
    def __init__(self, command: list[str], env: dict = None):
        self.process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # Line-buffered
            env=env
        )

    def send_message(self, message: dict):
        payload = json.dumps(message) + "\n"
        self.process.stdin.write(payload)
        self.process.stdin.flush()

    def read_message(self) -> dict:
        line = self.process.stdout.readline()
        if not line:
            raise EOFError("MCP Server closed stdout pipe.")
        return json.loads(line)
```


## 4. Server-Sent Events (SSE) & Remote HTTP Transport
For distributed tools, cloud-hosted microservices, and sandboxed Docker containers, MXB implements an asynchronous **Server-Sent Events (SSE)** transport layer over HTTP/HTTPS.

### SSE Message Lifecycle
1. **Handshake & Session Initiation**: Client issues an HTTP `GET /sse` request. The server holds the connection open, returning `Content-Type: text/event-stream` and emitting an `endpoint` event containing a unique session POST URI.
2. **Client-to-Server Requests**: All JSON-RPC client messages are posted to `/message?sessionId=<id>` using standard HTTP `POST` requests.
3. **Server-to-Client Streaming**: Responses, server-initiated notifications, and log streams flow down the open SSE connection.


## 5. Dynamic Tool Discovery & JSON Schema Validation
At startup or upon server attachment, MXB queries the server's registered tools via the `tools/list` protocol method.

### Tool Definition Schema
Each tool exposes its parameter definitions formatted as a strict **JSON Schema Draft 7** object, allowing MXB to inject valid tool definitions into both local Ollama models and cloud LLMs.

```json
{
  "name": "adjust_system_volume",
  "description": "Adjusts hardware master audio volume or toggles mute status.",
  "inputSchema": {
    "type": "object",
    "properties": {
      "level_delta": {
        "type": "integer",
        "description": "Percentage change in volume, e.g. +5 or -10."
      },
      "mute": {
        "type": "boolean",
        "description": "Set to true to toggle master audio mute."
      }
    },
    "required": []
  }
}
```


## 6. Resource Access Protocol & URI Routing
While tools represent executable actions with side-effects, **Resources** represent contextual data feeds that the LLM can inspect without mutating system state.

### URI Scheme Convention
MXB routes resource requests through standardized URI prefixes:
- `file:///path/to/local/file`: Local documents, workspace source code, or configuration files.
- `desktop://window/active`: Real-time metadata describing the currently focused desktop application.
- `system://telemetry/hardware`: Live CPU, RAM, GPU, and battery sensor data.
- `memory://facts/recent`: Semantic memory bank records retrieved from persistent storage.


## 7. Prompt Templating Protocol & Specialized Workflows
The MCP Prompt specification allows servers to expose parameterized conversational workflows, system prompt augmentations, and diagnostic routines directly to the client.

### Prompt Request & Parameter Binding
Servers declare dynamic prompts via `prompts/list`. When a user requests a pre-configured workflow (e.g. *"Debug my clipboard code"*), MXB calls `prompts/get`:
```json
{
  "method": "prompts/get",
  "params": {
    "name": "analyze_code_snippet",
    "arguments": {
      "language": "python",
      "optimization_goal": "memory"
    }
  }
}
```
The server returns formatted message arrays with bound arguments, avoiding client-side prompt maintenance.


## 8. Server Lifecycle Management & Connection Handshake
MCP defines a rigorous initialization and teardown sequence to guarantee version compatibility and clean subprocess teardown.

```
Client (MXB)                                    Server (Child Process)
     |                                                    |
     |---- initialize (Client Capabilities) ------------->|
     |<--- initialize response (Server Capabilities) -----|
     |---- notifications/initialized -------------------->|
     |                                                    |
     |                    [ Steady State ]                |
     |---- ping ----------------------------------------->|
     |<--- pong ------------------------------------------|
     |                                                    |
     |---- shutdown ------------------------------------->|
     |---- exit ----------------------------------------->|
```

### Heartbeat & Deadlock Prevention
MXB issues an idempotent `ping` request every 30 seconds. If a server fails to reply within 5.0 seconds, the child process is flagged as hung, force-terminated, and restarted.


## 9. Capability Negotiation & Version Handshake
During the `initialize` exchange, both client and server negotiate supported protocol features through structured capability flags.

### Supported Capability Flags
- `tools`: `{"listChanged": true}` indicates server will emit `notifications/tools/list_changed` when new tools are added dynamically.
- `resources`: `{"subscribe": true}` allows MXB to subscribe to live file or sensor updates.
- `prompts`: Indicates prompt template support.
- `logging`: Allows server to emit standardized diagnostic log events to the host console.


## 10. Fine-Grained Permission Security & User Authorization
Executing arbitrary OS-level tools poses substantial security risks. MXB categorizes all MCP tool definitions into three permission tiers:

| Security Tier | Description | Execution Policy | Example Tools |
| :--- | :--- | :--- | :--- |
| **Tier 1: Read-Only** | Inspects context without modifying state. | Automatic execution | `resources/read`, `get_active_window` |
| **Tier 2: Safe Action** | Non-destructive system mutations. | Automatic execution with log | `volume_up`, `open_app`, `notify` |
| **Tier 3: Destructive** | File modifications, deletions, shell commands. | **Explicit Human-in-the-Loop Dialog** | `delete_file`, `kill_process`, `run_bash` |

When a Tier 3 action is invoked, MXB halts execution and presents an interactive PySide6 confirmation prompt.


## 11. Subprocess Isolation & Windows Job Object Sandboxing
To prevent runaway tool scripts from crashing MXB or consuming excessive RAM, all child MCP servers run within Windows **Job Objects**.

### Sandboxing Controls
- **Memory Ceiling**: Job object enforces a hard limit of **512 MB** per server process.
- **CPU Rate Limiting**: Throttles child processes to maximum 25% CPU core allocation.
- **Kill on Job Close**: Guarantees that terminating the primary MXB daemon automatically terminates all associated child processes and open handles.


## 12. Local Filesystem MCP Server Integration
The Filesystem MCP server provides MXB with safe, sandboxed inspection of local repositories, documentation trees, and workspace configuration files.

### Security Boundary Guarantees
- **Root Directory Lock**: Server strictly confines operations to pre-authorized directories (e.g., `C:\Users\Asus\OneDrive\Desktop\PROJECTS\MXB`).
- **Path Traversal Protection**: Rejects all path queries attempting relative traversal (`../`) outside authorized boundaries.
- **Binary Guard**: Prohibits reading non-text executable binaries directly into LLM context windows.


## 13. SQLite Database MCP Server Integration
For structured querying of local logs, user memory entries, and time-series telemetry, MXB integrates a local **SQLite MCP Server**.

### Features
- **Schema Reflection**: Discovers database tables, column types, and foreign key relationships via `PRAGMA table_info`.
- **Read-Only Enforced Mode**: Runs analytical queries within transactions marked `PRAGMA query_only = ON` to prevent accidental mutations.
- **Result Truncation**: Automatically caps tabular query results to 50 rows to preserve LLM token budgets.


## 14. Web Browser Automation MCP Server
For complex research, web page summarization, and form interactions, MXB interfaces with a local headless Chromium instance powered by **Playwright**.

### Capabilities
- `navigate(url)`: Loads web pages with full JavaScript execution and cookie handling.
- `extract_article_text(url)`: Strips advertisements and navigation chrome, returning clean markdown copy.
- `capture_page_screenshot(url)`: Captures full-page visual screenshots for vision model ingestion.


## 15. Git & GitHub Repository MCP Integration
MXB integrates local Git automation tools to allow developer interaction directly through natural speech.

### Registered Git Actions
- `git_status`: Returns staged, unstaged, and untracked files.
- `git_diff`: Summarizes recent code modifications formatted as unified diffs.
- `git_log`: Retrieves recent commit history, author attributions, and branch statuses.
- `git_create_commit`: Stages files and drafts atomic commit messages based on staged changes.


