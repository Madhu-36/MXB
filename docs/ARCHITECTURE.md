# Machine eXecutive Brain (MXB) Architecture Specification (v4.3)

MXB is a high-performance local AI desktop executive companion designed for autonomous OS automation, privacy-first assistance, and low-latency voice interaction on Windows 10/11.

---

## 1. Subsystem Architecture Overview

```
                                 [ User Input ]
                                ┌──────┴──────┐
                         [ Voice / Mic ]   [ Text / Chat ]
                                │                 │
                       (VoicePipeline)            │
                        Silero VAD / AGC          │
                                │                 │
                                └───────┬─────────┘
                                        ▼
                                ┌────────────────┐
                                │   CommandBus   │
                                └───────┬────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
          [ Action Lane ]                                [ Info Lane ]
         (FIFO Execution)                             (Parallel Answering)
                 │                                             │
                 ├──────────────────────┬──────────────────────┤
                 ▼                      ▼                      ▼
        ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
        │  IntentRouter   │    │  AgentLoop      │    │  FocusCoach     │
        │  Tier 1/2 Match │    │  Set-of-Marks   │    │  Screen-Time    │
        └────────┬────────┘    └────────┬────────┘    └────────┬────────┘
                 │                      │                      │
                 ▼                      ▼                      ▼
       [ OSExecutionManager ]  [ UIAutomation ]       [ ActivityStore ]
       (Keyboard / Mouse)      (UIA Bounding Cache)   (SQLite Local DB)
                 │                      │
                 ├──────────────────────┼──────────────────────┐
                 ▼                      ▼                      ▼
        [ MCP Client ]         [ Scam Shield ]       [ MeetingCopilot ]
        (Ext. Tools / Stdio)   (UPI / Phishing)      (WASAPI Loopback)
```

---

## 2. Core Subsystems & Bus Topology

### 2.1 Decoupled Dual-Lane CommandBus
- **Action Lane (FIFO Worker)**: Sequentially executes desktop modifications, file operations, mouse/keyboard events, and agent loops to avoid race conditions.
- **Info Lane (Parallel Worker)**: Concurrently processes informational queries ("what's the weather", "who is X") while action tasks run in the background.
- **Telemetry**: Measures per-dispatch execution latency, maximum latency, and average response times.

### 2.2 Voice & Audio Ingestion Pipeline
- **Continuous VAD**: Powered by Silero Neural VAD running sub-0.2ms chunk inferences.
- **Microphone AGC**: Adaptive Input AGC normalizes quiet laptop microphones before VAD thresholding.
- **Buffer Overflow Guard**: Prevents latency buildup under heavy CPU load by dropping congested frames with telemetry logging.
- **Barge-In Echo Cancellation**: Automatically suppresses speaker audio feedback when the user speaks over TTS.

### 2.3 Intent Routing & Multi-Step Planner
- **Tier 1 (Deterministic Fast-Path)**: Sub-millisecond matching utilizing frozenset lookups and compiled regex for emergency voice stops, window snaps, and media control.
- **Tier 2 (Agent & LLM Planner)**: Leverages local Ollama (Llama 3.2 / Qwen 2.5) or NVIDIA Build APIs with strict schema validation and prompt injection defenses.

### 2.4 Prompt Injection & Sandbox Security
- **Fenced Untrusted Wrappers**: Fences screen text and external inputs with randomized nonces.
- **Sanitization Layer**: Strips escape delimiters (`<tool_call>`, `<<SYS>>`, fake role tags) from tool arguments.
- **Restricted Scopes**: File system destruction, registry mutation, and privilege escalation require explicit user confirmation.

### 2.5 Extended Modules (v4.0 - v4.3)
- **Indic Language Bridge**: Native translation and TTS routing for Kannada, Hindi, Tamil, Telugu, Marathi, and Bengali.
- **Scam Shield**: Offline heuristic and UPI rule engine guarding against collect requests, fake mandates, and digital arrest threats.
- **Meeting Copilot**: Dual-stream loopback recording separating "You" vs "Others" with markdown summary exports and action item checklists.
- **Focus & Study Coach**: Privacy-preserving activity tracker aggregating focus metrics into a 0-100 productivity score.
- **Accessibility Engine**: Voice-first screen reader with virtual cursor and high-contrast speech cues.
