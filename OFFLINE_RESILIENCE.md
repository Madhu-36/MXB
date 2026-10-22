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


## 2. Local Model Weight Verification & SHA-256 Checksums
To prevent runtime segmentation faults or cryptic inference hangs caused by partially downloaded or corrupted model weights, the model loader verifies binary hashes prior to memory mapping.

### Validation Algorithm
```python
import hashlib
import json
from pathlib import Path

def verify_model_integrity(model_path: Path, expected_sha256: str) -> bool:
    sha256 = hashlib.sha256()
    with open(model_path, "rb") as f:
        while chunk := f.read(1024 * 1024 * 16):  # 16MB blocks
            sha256.update(chunk)
    digest = sha256.hexdigest().lower()
    return digest == expected_sha256.lower()
```

Verified hashes are cached in `model_manifest.json` alongside model quantization profiles (`Q4_K_M`, `Q5_K_S`) to bypass redundant re-hashing during rapid application warm starts.


## 3. High-Performance Local Speech-to-Text via whisper.cpp
When running detached from the internet, MXB leverages `pywhispercpp` bound to statically compiled AVX2/CUDA C++ binaries.

### Configuration Specification
- **Engine**: Whisper.cpp runtime bindings.
- **Model Target**: `ggml-base.en-q5_1.bin` (60MB) for low-power laptops; `ggml-small.en-q5_1.bin` (240MB) for desktop workstations.
- **Latency Budget**: < 220ms on 4-thread CPU; < 45ms on RTX GPU.
- **Memory Footprint**: Under 350MB VRAM / 500MB System RAM.

```python
from pywhispercpp.model import Model

stt_engine = Model(
    model="base.en",
    n_threads=4,
    print_realtime=False,
    print_progress=False
)
```


## 4. Local Neural Speech Synthesis with Piper VITS
Voice feedback is generated locally using Piper, an optimized neural text-to-speech system based on VITS and ONNX Runtime.

### Operational Characteristics
- **Engine**: Piper ONNX voice synthesizer with DirectML/CPU acceleration.
- **Sampling Rate**: 22,050 Hz high-fidelity PCM audio.
- **Real-Time Factor (RTF)**: 0.08x on average quad-core Intel Core i5 (12x faster than real time).
- **Zero Cloud Leakage**: Synthesis operates purely in-memory, streaming direct PCM chunks into Windows WASAPI ring buffers.

```bash
# Offline CLI Verification
echo "System offline mode active." | piper.exe --model en_US-lessac-medium.onnx --output_raw | aplay
```


## 5. Deterministic Regex Rule Engine for Extreme Starvation
Under severe thermal throttling, memory pressure, or when model weights are temporarily unloading, MXB gracefully degrades to a zero-overhead regex-based pattern matcher.

### Deterministic Action Map
```json
{
  "rules": [
    {"pattern": "^(?:open|launch)\\s+(?P<app>[a-zA-Z0-9_ ]+)$", "action": "os.launch_app"},
    {"pattern": "^(?:mute|unmute)\\s+(?:volume|audio)?$", "action": "audio.toggle_mute"},
    {"pattern": "^(?:set|change)\\s+volume\\s+to\\s+(?P<level>\\d{1,3})%?$", "action": "audio.set_volume"},
    {"pattern": "^(?:lock|secure)\\s+(?:screen|pc|workstation)$", "action": "system.lock_workstation"}
  ]
}
```

This ensures fundamental operating system control commands never stall or fail, regardless of system load.


## 6. Offline Application Indexing & Trie-Based Search
MXB maintains an offline index of all locally installed Win32, MSIX, and Windows Store applications without pinging online search providers or Windows Search index telemetry.

### Indexing Sources
1. Start Menu Directory Paths (`C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs`).
2. User Programs Directory (`%AppData%\\Microsoft\\Windows\\Start Menu\\Programs`).
3. App Execution Aliases (`%LocalAppData%\\Microsoft\\WindowsApps`).
4. Registry Software Uninstall Keys (`HKLM\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall`).

Indexed application paths are stored in an in-memory prefix trie with Levenshtein fuzzy matching, delivering match results within 2 milliseconds.


## 7. Embedded Vector Store Persistence via SQLite & sqlite-vss
Offline semantic retrieval and long-term conversation recall are powered by embedded SQLite with vector similarity search extensions (`sqlite-vss`), avoiding any reliance on external database daemons or cloud vector databases.

```sql
-- Local Embedded Vector Storage Schema
CREATE VIRTUAL TABLE IF NOT EXISTS memory_embeddings USING vss0(
    embedding(384),
    content TEXT,
    timestamp DATETIME,
    source TEXT
);

-- Cosine Distance Retrieval
SELECT rowid, distance, content 
FROM memory_embeddings 
WHERE vss_search(embedding, vss_search_params(?1, 10))
ORDER BY distance ASC;
```

Embedding vectors are generated using a local ONNX quantized `all-MiniLM-L6-v2` encoder (384 dimensions) with 15ms inference latency.


## 8. Encrypted Local Telemetry Queue & Crash Journal
To debug failures without exposing internal application state across unencrypted channels, diagnostic events are recorded into an encrypted local circular ring buffer.

### Ring Buffer Attributes
- **Format**: AES-GCM encrypted local SQLite database `telemetry_journal.db`.
- **Maximum Buffer Size**: 50 MB (auto-purging oldest non-fatal records when full).
- **Zero-Egress Mode**: In air-gapped configuration, external sync endpoints are permanently disabled, retaining records strictly for manual local diagnostic export.
- **Redaction**: All file paths and window names are scrubbed of personal usernames before disk commitment.


## 9. Dynamic Network State Listener & Seamless Mode Switching
MXB uses the Windows Network List Manager (NLM) COM API (`INetworkListManager`) to monitor active network interfaces without periodic network polling.

```python
def on_network_connectivity_changed(is_connected: bool):
    if not is_connected:
        log.warning("Network connection severed. Transitioning to Autonomous Offline Mode.")
        engine.set_inference_tier(InferenceTier.LOCAL_ONLY)
        network_pool.cancel_pending_cloud_tasks()
        ui.display_offline_badge(active=True)
    else:
        log.info("Network restored. Optional remote sync enabled.")
        ui.display_offline_badge(active=False)
```

Transition between online hybrid mode and full offline autonomy happens in less than 50 milliseconds with zero dropped voice frames.


## 10. DNS Timeout Isolation & Circuit Breaking
When hybrid features (such as real-time web search) are enabled but the network drops, connection hangs can freeze UI threads. MXB implements strict circuit breaking with rapid fail-fast timers.

### Circuit Breaker States
- **Closed**: Remote endpoints healthy; requests proceed with a 2.5s hard timeout.
- **Open**: After 2 consecutive socket/DNS timeouts, breaker trips to OPEN. All subsequent requests fail immediately to local fallback without issuing network socket calls.
- **Half-Open**: Periodic single probe allowed after a 60-second cooldown window.

```python
class CircuitBreakerOpenException(Exception): pass
```


## 11. Air-Gapped Firewall Rules & Outbound Isolation
For classified or high-security deployments, MXB can be placed in strict air-gap isolation through automated Windows Advanced Firewall rules.

### PowerShell Air-Gap Script
```powershell
# Block all outbound TCP/UDP traffic from MXB application binaries
New-NetFirewallRule -DisplayName "MXB Core Block Outbound" `
    -Direction Outbound `
    -Program "C:\Program Files\MXB\mxb.exe" `
    -Action Block `
    -Profile Any

# Permit local loopback IPC for Ollama local server
New-NetFirewallRule -DisplayName "MXB Permit Localhost IPC" `
    -Direction Outbound `
    -Program "C:\Program Files\MXB\mxb.exe" `
    -RemoteAddress 127.0.0.1 `
    -Action Allow
```


## 12. Offline Updates via Signed Binary Bundles (.mxbupdate)
Updates in air-gapped environments are delivered via cryptographically signed update bundles (`.mxbupdate`) transferred via authorized USB media.

### Update Workflow
1. The administrator loads `mxb_v2.1_update.mxbupdate`.
2. Binary signature is validated using the MXB offline RSA-4096 public root key.
3. Binary differential patches (`bsdiff4`) are applied against existing DLLs and executables in a staging directory.
4. An atomic directory rename completes the update upon next application restart.


## 13. Offline Document Ingestion Pipeline
MXB features an offline RAG (Retrieval-Augmented Generation) document processing pipeline that parses user documents directly on the local machine.

### Document Parsers
- **PDF Documents**: Extracted via `pdfplumber` using pure local Python parsing.
- **Markdown & Code**: AST parsing via standard Python `ast` and markdown splitters.
- **Chunking Strategy**: Recursive token splitter targeting 512 tokens with 64-token sliding window overlap.
- **Local Embedding**: Chunk vectors generated locally via ONNX Runtime using int8 quantized transformer weights.


## 14. Thermal Throttling & Hardware Resource Telemetry
Local model execution on laptops requires proactive thermal management to prevent hardware degradation and fan noise disruptions.

```python
class ThermalManager:
    def __init__(self, temp_threshold_celsius: float = 82.0):
        self.threshold = temp_threshold_celsius

    def evaluate_inference_throttle(self, current_gpu_temp: float) -> int:
        if current_gpu_temp >= self.threshold:
            # Drop context window and switch to smaller quantized draft model
            return 1024
        return 4096
```

The system continuously reads sensor data via Windows Management Instrumentation (WMI) and NVIDIA NVML C-bindings.


