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


