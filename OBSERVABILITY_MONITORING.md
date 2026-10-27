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


## 9. Windows Performance Data Helper (PDH) Telemetry
To monitor background thread contention, MXB samples system CPU and NVMe disk performance using the Windows PDH API.

### Sampled Counters
- `\Processor Information(_Total)\% Processor Utility`
- `\Process(mxb)\% User Time`
- `\PhysicalDisk(_Total)\Avg. Disk sec/Read`
- `\Memory\Available MBytes`

Counters detect when anti-virus scanning or Windows updates compete with model loading I/O.


## 10. WASAPI Audio Buffer Under-Run & Dropout Tracking
Audio discontinuities cause speech recognition failures and crackling synthesized audio.

### Audio Stream Metrics
- **WASAPI Buffer Under-run Counter**: Tracks `AUDCLNT_E_BUFFER_ERROR` occurrences when the real-time thread misses its WASAPI render deadline.
- **Microphone Sample Drift**: Measures drift between hardware clock and software consumption buffer.
- **Zero-Crossing Silence Ratio**: Detects hardware microphone disconnections or muted inputs.


## 11. VAD Metric Logging & False-Trigger Analysis
Tracking VAD efficiency prevents assistant false wake-ups and trailing sentence cut-offs.

### Tracked Heuristics
- **False Trigger Rate (FTR)**: Audio segments flagged as speech that produce 0 words in Whisper.
- **End-Of-Speech (EOS) Latency**: Milliseconds between user silence onset and speech termination trigger.
- **Truncation Events**: Occurrences where speech was cut prematurely due to short silence thresholds.


## 12. Flight Recorder Circular Ring Buffer
To provide high-fidelity diagnostics without consuming gigabytes of disk space, MXB maintains an encrypted circular flight recorder in SQLite.

```sql
CREATE TABLE IF NOT EXISTS flight_recorder (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    subsystem TEXT,
    event_payload BLOB
);

-- Circular Pruning Trigger: Cap table to last 10,000 events
CREATE TRIGGER IF NOT EXISTS prune_flight_recorder
AFTER INSERT ON flight_recorder
BEGIN
    DELETE FROM flight_recorder WHERE id <= NEW.id - 10000;
END;
```

Payloads are encrypted with local AES-GCM-256 keys derived via Windows DPAPI.


## 13. Subprocess Heartbeat Daemon & Deadman Switch
Child processes (such as the Ollama inference backend or computer vision worker) must be monitored for deadlocks or frozen threads.

### Watchdog Architecture
```python
class ProcessWatchdog:
    def __init__(self, target_pid: int, timeout_sec: float = 5.0):
        self.target_pid = target_pid
        self.timeout = timeout_sec
        self.last_heartbeat = time.time()

    def record_pulse(self):
        self.last_heartbeat = time.time()

    def check_health(self):
        if time.time() - self.last_heartbeat > self.timeout:
            log.error(f"Child process PID {self.target_pid} missed heartbeat. Triggering restart.")
            self.terminate_and_respawn()
```


## 14. Automated Health Check Tool: 'mxb doctor'
The `mxb doctor` CLI command runs comprehensive self-diagnostics to verify runtime readiness before running workloads.

### Check Suite
```bash
$ mxb doctor
[✓] Windows OS: Windows 11 Build 22631 (64-bit)
[✓] Audio Input: Default WASAPI Capture Device Active (16kHz 16-bit Mono)
[✓] Audio Output: Default WASAPI Render Device Active (48kHz Stereo)
[✓] CUDA Acceleration: NVIDIA GeForce RTX 3060 (Compute Capability 8.6)
[✓] VRAM Availability: 8,192 MB Total / 6,140 MB Free
[✓] Local Model Files: llama-3.1-8b-q4_k_m.gguf (SHA-256 Verified)
[✓] Loopback Socket: 127.0.0.1 IPC Responsive (<0.5ms)
>> All 7 health checks passed successfully.
```


## 15. Real-Time HUD Diagnostic Overlay
Developers and power users can toggle an on-screen diagnostic overlay (`Ctrl+Shift+D`) inside the PySide6 glassmorphic HUD.

### Rendered Widgets
- **Live Waveform & RMS Visualizer**: Real-time microphone input gain.
- **Latency Sparkline**: Rolling 10-turn interaction latency chart.
- **Hardware Gauge**: Instantaneous CPU, VRAM, and GPU temperature dials.
- **Active Trace Inspector**: Drill-down view of the most recent pipeline span.


## 16. Memory Leak Profiling & PyObject Auditing
Long-running background assistant applications must maintain a flat memory footprint over weeks of continuous operation.

### Tracemalloc Snapshot Profiling
```python
import tracemalloc

def audit_memory_allocation(snapshot_baseline):
    current = tracemalloc.take_snapshot()
    stats = current.compare_to(snapshot_baseline, "lineno")
    
    for stat in stats[:5]:
        if stat.size_diff > 1024 * 1024:  # Leaks > 1MB
            log.warning(f"Memory growth detected: {stat}")
```

Automated hourly audits verify that UI pixmaps, vector embeddings, and audio buffers are garbage-collected properly.


## 17. End-to-End Latency Waterfall Visualization
Latency bottlenecks are dissected visually using waterfall timelines rendered from OpenTelemetry span dumps.

```
0ms         200ms        400ms        600ms        800ms
|------------|------------|------------|------------|
[ VAD: 110ms ]
             [ STT: 215ms ]
                          [ RAG: 38ms ]
                          [ LLM TTFT: 240ms ]
                                            [ TTS: 137ms ]
```

Pinpoints precisely whether delays originate in audio capture, neural generation, or disk I/O.


## 18. Network Circuit Breaker Telemetry
For optional cloud-enabled features (e.g. web search), circuit breaker telemetry records connection health.

### Telemetry Events
- `breaker.state_changed`: Emitted when transitioning between `CLOSED`, `OPEN`, and `HALF_OPEN`.
- `breaker.consecutive_failures`: Counter of failed socket/DNS handshakes.
- `breaker.fallback_invoked`: Counter of queries rerouted to local offline fallback.


## 19. Local LLM Generation Metrics Collection
Every local LLM completion computes precise throughput and prompt evaluation metrics:

### Metric Fields
- **Prompt Eval Speed**: Tokens per second during system prompt & context pre-fill ($TPS_{eval}$).
- **Token Generation Speed**: Output generation throughput ($TPS_{gen}$).
- **KV-Cache Hit Ratio**: Percentage of prompt tokens served from prefix cache ($0.0$ to $1.0$).


## 20. RAG Retrieval Telemetry & Relevance Scoring
To track knowledge retrieval accuracy over time, RAG queries log similarity scores without logging document text.

### Logged Parameters
- Number of candidate chunks retrieved from BM25 and vector search.
- Mean reciprocal rank of selected citations.
- Cosine similarity distance distribution of the top-5 retrieved chunks.


## 21. Privacy-Compliant Crash Report Packaging
If an unhandled exception occurs, MXB offers to package an anonymized diagnostic report.

### Packaging Flow
1. Bundle redacted JSON logs, mini-dump, and system hardware specifications.
2. Store package locally as `mxb_diagnostic_report.zip`.
3. Present interactive PySide6 preview dialog showing every file in the archive.
4. Transmission requires explicit user click; never automated.


## 22. Log Retention Policies & Automatic Compaction
To avoid unconstrained disk growth on small SSDs, MXB enforces strict storage limits.

### Retention Rules
- Total log directory (`%APPDATA%\MXB\logs`) capped at **250 MB**.
- Crash dumps older than 14 days are automatically pruned.
- Completed diagnostic archives are compressed using LZMA/gzip.


## 23. Immutable Audit Trail via Cryptographic Hash Chaining
High-risk automation events (e.g. system file deletions, password autofill, privilege elevation) are linked in a cryptographic blockchain-like ledger.

```python
def create_audit_entry(event_data: dict, previous_hash: str) -> dict:
    hasher = hashlib.sha256()
    payload = json.dumps(event_data, sort_keys=True)
    hasher.update((previous_hash + payload).encode("utf-8"))
    
    return {
        "event": event_data,
        "prev_hash": previous_hash,
        "entry_hash": hasher.hexdigest()
    }
```

Prevents tampering or retroactive manipulation of security audit logs.


## 24. Automated Observability Test Fixtures with Pytest
MXB verifies telemetry emission and redaction rules as part of its automated test suite.

```python
import pytest

def test_telemetry_redaction_pipeline():
    from engine.telemetry import redact_log_record
    
    sensitive_line = "Failed to load C:\\Users\\JohnDoe\\secret_key=ghp_123456789012345678901234567890123456"
    redacted = redact_log_record(sensitive_line)
    
    assert "JohnDoe" not in redacted
    assert "ghp_1234" not in redacted
    assert "[REDACTED_USER]" in redacted
    assert "[REDACTED_API_KEY]" in redacted
```


## 25. Architectural Verification & Compliance Sign-Off
The Observability, Distributed Tracing & Diagnostics Architecture is verified, benchmarked, and officially signed off for the October 27, 2026 milestone.

### Verification Checklist
- [x] Structured JSON Logging: Rotating file handlers with gzip compaction verified.
- [x] OpenTelemetry Context: Distributed tracing across audio, LLM, and TTS tested.
- [x] MiniDump Generation: Native unhandled crash handler verified with MiniDumpWriteDump.
- [x] PII Redaction: Deterministic scrubbing of usernames, API keys, and emails tested.
- [x] Real-Time Hardware Telemetry: NVML and Windows PDH sensor collection active.
- [x] 'mxb doctor' CLI: 7-point health check suite passed with 100% assertions.
- [x] Immutable Audit Trail: SHA-256 cryptographic chaining validated.

---
*Observability & Diagnostics Guide - Maintained by Madhu S for MXB V2.0 (October 27, 2026).*


