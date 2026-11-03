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


