# MXB V2.0 - Heterogeneous Compute, NPU Offload & Multi-Accelerator Architecture

## 1. Executive Summary & Hardware Vision
MXB V2.0 is architected for the era of Copilot+ PCs and heterogeneous computing platforms. Rather than funneling all machine learning workloads into a power-hungry discrete GPU (dGPU) or saturating the host CPU, MXB partitions tasks across specialized hardware engines: **Neural Processing Units (NPUs)**, **Integrated Graphics (iGPUs)**, **Discrete GPUs (dGPUs)**, and **Hybrid CPU Cores (P-cores/E-cores)**.

```
+-----------------------------------------------------------------------------------+
|                     MXB Heterogeneous Hardware Workload Matrix                    |
|                                                                                   |
|  [ Microphones (16kHz Audio) ] ---> (NPU: Silero VAD Continuous Listening, <1.5W) |
|                                                   |                               |
|                                                   v                               |
|  [ Audio Chunks ] ==============> (iGPU: Whisper.cpp Int8 STT Inference)         |
|                                                   |                               |
|                                                   v                               |
|  [ Prompt & Memory Tokens ] ====> (dGPU: Llama-3.1 8B Q4_K_M Reasoning Engine)   |
|                                                   |                               |
|                                                   v                               |
|  [ Synthesized Tokens ] ========> (CPU E-Cores: Piper Neural TTS Voice Playback)  |
|                                                   |                               |
|                                                   v                               |
|  [ Windows Screen Capture ] ====> (NPU / iGPU: Local OCR & Vision Detection)      |
+-----------------------------------------------------------------------------------+
```

### Core Architecture Objectives
- **Sub-5W Battery Profile**: Sustains continuous background voice activity monitoring on battery power without spinning chassis fans.
- **Dynamic Accelerator Arbitration**: Automatically routes tensors to the highest-efficiency engine available on the host machine.
- **Zero-Copy Cross-Adapter Memory**: Employs Direct3D 12 shared surfaces to pass video frames and audio tensors without crossing PCIe bus bottlenecks.


## 2. Hardware Topology Discovery via DXGI & WMI
At application cold start, MXB probes the system topology to enumerate all compute adapters, memory buses, and neural acceleration capabilities.

### Enumeration Routine
```python
import win32com.client

def enumerate_compute_hardware():
    wmi = win32com.client.GetObject("winmgmts:")
    adapters = []
    
    # Query video controllers via WMI
    for gpu in wmi.InstancesOf("Win32_VideoController"):
        adapters.append({
            "name": gpu.Name,
            "vram_bytes": int(gpu.AdapterRAM or 0),
            "driver_version": gpu.DriverVersion
        })
        
    return adapters
```

In addition, the native DXGI (DirectX Graphics Infrastructure) COM interface queries adapter dedicated video memory, shared system memory, and compute tier compatibility flags.


