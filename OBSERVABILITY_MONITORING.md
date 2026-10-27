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


## 2. Structured JSON Logging & Rotating File Handlers
All subsystem log records are formatted as structured JSON Lines (JSONL), ensuring machine-readability and zero parsing ambiguity.

### JSON Log Record Schema
```json
{
  "timestamp": "2026-10-27T14:15:30.124592Z",
  "level": "INFO",
  "subsystem": "engine.stt",
  "trace_id": "4bf92f3577b34da6a3ce929d0e0e4736",
  "span_id": "00f067aa0ba902b7",
  "message": "Whisper greedy transcription completed",
  "metrics": {
    "audio_duration_ms": 1420,
    "inference_duration_ms": 184,
    "rtf": 0.13
  }
}
```

Log files rotate automatically at 25 MB with a maximum retention of 5 archive generations (`mxb.log.1.gz` through `mxb.log.5.gz`).


## 3. OpenTelemetry Distributed Tracing Integration
MXB integrates OpenTelemetry (OTel) distributed tracing primitives across multi-threaded and asynchronous boundaries.

### Trace Context Propagation
A unique `TraceID` (128-bit hex) is generated the instant user speech is detected by the Voice Activity Detector (VAD). This context flows through:
1. Audio capture ring buffer.
2. Whisper C++ inference worker.
3. RAG semantic retrieval search.
4. Llama 3.1 token generation stream.
5. Piper neural TTS audio playback.

```python
from opentelemetry import trace

tracer = trace.get_tracer("mxb.core")

with tracer.start_as_current_span("voice_interaction_turn") as root_span:
    root_span.set_attribute("audio.input_device", "USB_Microphone_WASAPI")
    process_audio_pipeline(trace_context=root_span.get_span_context())
```


