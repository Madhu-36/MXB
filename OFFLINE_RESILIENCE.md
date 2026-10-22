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


