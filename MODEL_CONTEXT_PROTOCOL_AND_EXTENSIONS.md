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


