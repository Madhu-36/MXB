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


