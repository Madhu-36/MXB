# MXB V2.0 - Observability, Distributed Tracing & Diagnostics Architecture

## 1. Executive Summary & Telemetry Principles
MXB V2.0 incorporates an enterprise-grade, privacy-first observability platform. Designed to diagnose real-time audio pipeline anomalies, LLM latency spikes, and system resource exhaustion, the architecture couples structured logging with OpenTelemetry-compliant distributed tracing while maintaining strict zero-egress user privacy guarantees.

```
+---------------------------------------------------------------------------------+
|                        MXB Core Telemetry Architecture                          |
|                                                                                 |
|  [ Audio Stream ] ---> [ Whisper STT ] ---> [ LLM Inference ] ---> [ Piper TTS ]|
|         |                     |                     |                    |      |
|         v                     v                     v                    v      |
|  +---------------------------------------------------------------------------+  |
|  |           OpenTelemetry Tracing Context (TraceID / SpanID)                |  |
|  +---------------------------------------------------------------------------+  |
|         |                                           |                           |
|         v                                           v                           |
|  [ Structured JSON Logger ]                 [ In-Memory Flight Recorder ]       |
|  - Rotating Disk Handlers                   - Circular SQLite WAL Buffer        |
|  - Real-Time PII Scrubbing                  - AES-GCM Encrypted at Rest         |
|         |                                           |                           |
|         v                                           v                           |
|  [ Loopback Prometheus Exporter ]           [ Diagnostic HUD & 'mxb doctor' ]   |
+---------------------------------------------------------------------------------+
```

### Core Tenets
- **Zero-Egress by Default**: Diagnostic data is strictly stored locally on the user's workstation.
- **Microsecond Precision**: High-resolution monotonic timers (`time.perf_counter_ns`) track sub-millisecond pipeline latency.
- **Deterministic Redaction**: PII, passwords, paths, and raw user audio are scrubbed prior to log serialization.


