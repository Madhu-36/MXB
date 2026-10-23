# MXB V2.0 - Performance Tuning & Sub-Millisecond Latency Optimization Guide

## 1. Executive Summary & Latency Budget
MXB V2.0 is engineered for real-time interaction. To achieve a fluid conversational experience matching human conversational pacing, the end-to-end voice-to-ear latency budget is capped at **850 milliseconds**.

```
+------------------------------------------------------------------------------------+
|                         Total Latency Budget: < 850 ms                              |
+------------------------------------------------------------------------------------+
| VAD End-of-Speech | STT Inference | Intent / LLM TTFT | Audio Synthesis | Output Delay |
|     (120 ms)      |   (220 ms)    |     (320 ms)      |    (110 ms)     |   (40 ms)    |
+------------------------------------------------------------------------------------+
```

This guide details subsystem-by-subsystem optimization techniques, memory layouts, compiler flags, and operating system scheduling parameters to hit deterministic latency targets on consumer hardware.


## 2. Windows Thread Scheduling & Process Priority Pinning
Voice capture and real-time audio threads are vulnerable to jitter when competing against background Windows services or game processes.

### Thread Priority Hardening
Audio capture and VAD processing loops are explicitly elevated to `ABOVE_NORMAL_PRIORITY_CLASS` or `HIGH_PRIORITY_CLASS` using Win32 API calls:

```python
import win32api
import win32process

def set_realtime_priority():
    pid = win32api.GetCurrentProcessId()
    handle = win32api.OpenProcess(win32process.PROCESS_ALL_ACCESS, True, pid)
    # Pin core engine to high priority to avoid audio buffer under-runs
    win32process.SetPriorityClass(handle, win32process.ABOVE_NORMAL_PRIORITY_CLASS)
```

### Core Pinning & E/P-Core Affinity
On hybrid Intel Alder Lake / Raptor Lake architectures, real-time worker threads are explicitly pinned to Performance cores (P-cores) via affinity bitmasks, avoiding scheduling delays on low-frequency Efficiency cores (E-cores).


## 3. VRAM Memory Pooling & Zero-Copy Allocation
Dynamic GPU memory allocation (`cudaMalloc` / `cudaFree`) introduces micro-stutters ranging between 5ms and 30ms during inference startup.

### PyTorch / ONNX Unified Memory Pool
MXB pre-allocates an explicit GPU memory pool at cold start:
```python
import torch

def configure_cuda_memory_pool():
    if torch.cuda.is_available():
        # Reserve a 2.5 GB contiguous VRAM chunk for inference buffers
        torch.cuda.set_per_process_memory_fraction(0.85)
        torch.cuda.empty_cache()
        # Enable CUDA caching allocator memory segment reuse
        os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "max_split_size_mb:128,garbage_collection_threshold:0.8"
```

This eliminates page fragmentation and locks inference buffers into persistent tensor caches across consecutive voice queries.


