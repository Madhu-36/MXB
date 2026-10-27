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


## 4. Sub-Millisecond Span Timing & Span Hierarchy
Spans nested within the root interaction turn measure localized execution slices with microsecond granularity.

```
[ voice_interaction_turn : 740 ms ]
|-- [ vad_slice_detection : 110 ms ]
|-- [ whisper_stt_inference : 215 ms ]
|-- [ hybrid_rag_retrieval : 38 ms ]
|-- [ llm_ttft_generation : 240 ms ]
`-- [ piper_tts_audio_first_chunk : 137 ms ]
```

Span boundaries capture hardware state transitions, enabling instant isolation of performance regressions.


## 5. Native Windows Crash MiniDump Generation
Unrecoverable C++ segmentation faults or CUDA driver exceptions inside `llama.dll` or `whisper.dll` trigger the native Windows unhandled exception filter.

### MiniDump Capture Routine
```c
#include <windows.h>
#include <dbghelp.h>

LONG WINAPI MXBUnhandledCrashFilter(EXCEPTION_POINTERS* pExceptionPointers) {
    HANDLE hFile = CreateFileA("C:\\ProgramData\\MXB\\crashes\\crash.dmp", 
        GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile != INVALID_HANDLE_VALUE) {
        MINIDUMP_EXCEPTION_INFORMATION mei;
        mei.ThreadId = GetCurrentThreadId();
        mei.ExceptionPointers = pExceptionPointers;
        mei.ClientPointers = FALSE;
        MiniDumpWriteDump(GetCurrentProcess(), GetCurrentProcessId(), hFile, MiniDumpNormal, &mei, NULL, NULL);
        CloseHandle(hFile);
    }
    return EXCEPTION_EXECUTE_HANDLER;
}
```

Generates compact (80-150 KB) mini-dumps containing call stacks, thread states, and registers without memory page dumps.


## 6. Deterministic Privacy Redaction Pipeline
Diagnostic logs must never capture user credentials, local usernames, or confidential conversation transcripts.

### Redaction Engine Regex Rules
```python
import re

PATTERNS = [
    (re.compile(r"C:\\Users\\[^\\/]+", re.IGNORECASE), "C:\\Users\\[REDACTED_USER]"),
    (re.compile(r"(ghp_[a-zA-Z0-9]{36}|AIza[0-9A-Za-z-_]{35})"), "[REDACTED_API_KEY]"),
    (re.compile(r"\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{4}"), "[REDACTED_CARD]"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}"), "[REDACTED_EMAIL]")
]

def redact_log_record(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text
```


## 7. Loopback Prometheus & StatsD Exporter
For system administrators or local monitoring dashboards (e.g. Grafana on desktop), MXB exposes a Prometheus metrics endpoint.

### Configuration
- **Bind Address**: Strictly bound to `127.0.0.1:9095/metrics` (remote connections refused).
- **Core Metrics**:
  - `mxb_audio_latency_seconds`: Gauge of end-to-end turn latency.
  - `mxb_llm_tokens_per_second`: Instantaneous token generation rate.
  - `mxb_vram_used_bytes`: GPU memory allocated by local model runtime.
  - `mxb_vad_triggers_total`: Counter of voice activity events.


## 8. Real-Time GPU Hardware Telemetry via NVML
Accurate profiling of local LLM performance requires direct monitoring of GPU clock speeds, power draw, and VRAM utilization.

```python
import pynvml

def sample_gpu_telemetry(device_index: int = 0) -> dict:
    pynvml.nvmlInit()
    handle = pynvml.nvmlDeviceGetHandleByIndex(device_index)
    
    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
    temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
    power = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0  # Watts
    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
    
    return {
        "vram_used_mb": mem.used // (1024 * 1024),
        "gpu_temp_c": temp,
        "power_watts": power,
        "gpu_util_pct": util.gpu
    }
```


