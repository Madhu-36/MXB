# MXB V2.0 - Autonomous Offline Execution & Air-Gapped Resilience Manual

## 1. Executive Summary & Core Philosophy
MXB V2.0 is architected with a strict **Zero-Cloud Dependency Principle**. The primary user promise is that core desktop assistance—natural voice transcription, intent parsing, semantic reasoning, system tool execution, and neural speech synthesis—must operate at 100% capacity in completely air-gapped, zero-connectivity, or intermittent-network environments.

```
+---------------------------------------------------------------+
|                       MXB Run-Time Core                       |
|                                                               |
|  [ Microphones ] --> (Local Whisper.cpp)                      |
|                              |                                |
|                              v                                |
|                     [ Intent Dispatcher ]                     |
|                      /                 \                     |
|        (Ollama / llama.cpp)      (Regex Heuristics Rule Engine)|
|                      \                 /                     |
|                              v                                |
|                     [ Tool Executor ]                         |
|                              |                                |
|                              v                                |
|                      (Piper Local TTS) --> [ Speakers ]       |
+---------------------------------------------------------------+
```

All models, indexing structures, vector databases, and state stores reside in local NVMe storage without relying on remote RPCs or background telemetry heartbeats.


