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


## 3. DirectML Execution Provider Architecture
To support hardware acceleration across AMD Radeon, Intel Arc, and NVIDIA GeForce adapters without vendor lock-in, MXB integrates Microsoft's **DirectML** execution provider in ONNX Runtime.

### DirectML Session Configuration
```python
import onnxruntime as ort

def create_directml_session(model_path: str, device_id: int = 0) -> ort.InferenceSession:
    providers = [
        ("DmlExecutionProvider", {
            "device_id": device_id,
            "enable_metacommands": True,
            "performance_preference": "high_performance"
        }),
        "CPUExecutionProvider"
    ]
    opts = ort.SessionOptions()
    opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    return ort.InferenceSession(model_path, sess_options=opts, providers=providers)
```

DirectML compiles HLSL compute shaders on-the-fly, executing tensor matrix multiplications directly over DirectX 12 hardware.


## 4. Qualcomm Hexagon NPU Offload via QNN SDK
On ARM64 Windows Copilot+ devices powered by Snapdragon X Elite and X Plus processors, MXB delegates tensor evaluation to the Qualcomm Hexagon NPU (45 TOPS).

### Qualcomm Neural Network (QNN) Pipeline
- **Execution Provider**: `QNNExecutionProvider` targeting the Hexagon Tensor Processor (HTP).
- **Supported Datatypes**: Native hardware execution of `INT8` and `INT16` quantized weights.
- **Latency Budget**: Silero VAD evaluation completes in **0.4 milliseconds** per 30ms audio frame with negligible CPU utilization.


## 5. Intel Core Ultra NPU Acceleration via OpenVINO
For Intel Meteor Lake, Lunar Lake, and Arrow Lake mobile architectures, MXB binds to the integrated Intel NPU via the OpenVINO NPU runtime plugin.

### OpenVINO NPU Pipeline Configuration
```python
from openvino.runtime import Core

def init_intel_npu_pipeline(model_xml: str):
    core = Core()
    # Check if Intel NPU device is available
    if "NPU" in core.available_devices:
        model = core.read_model(model_xml)
        compiled = core.compile_model(model, "NPU", {
            "PERFORMANCE_HINT": "LATENCY",
            "NPU_COMPILER_TYPE": "DRIVER"
        })
        return compiled
    return None
```

Offloading background OCR and audio preprocessing to the Intel NPU frees integrated graphics for UI glassmorphism rendering.


## 6. AMD XDNA 2 Ryzen AI NPU Acceleration
AMD Strix Point and Hawk Point mobile processors feature XDNA and XDNA 2 architecture NPUs delivering up to 50 TOPS of INT8 tensor processing.

### Hardware Binding
- **Driver**: AMD IPU (Intelligent Processing Unit) Windows WDDM driver.
- **Execution Provider**: `VitisAIExecutionProvider` inside ONNX Runtime.
- **Execution Target**: Background semantic embedding generation (`all-MiniLM-L6-v2`) executing in under **3.2 milliseconds** per document chunk.


## 7. Workload Partitioning & Device Assignment Matrix
Routing each task to its optimal accelerator minimizes latency and maximizes battery endurance.

### Workload Assignment Matrix
| Task / Model | Target Device | Precision | Execution Provider | Justification |
|--------------|---------------|-----------|--------------------|---------------|
| Silero VAD | NPU | INT8 | QNN / OpenVINO / DML | 24/7 background listening (<1.5W) |
| Whisper STT | iGPU / NPU | INT8 / FP16 | DirectML / OpenVINO | Fast streaming audio chunks (<200ms) |
| Llama-3.1 8B LLM | dGPU | Q4_K_M | CUDA / DirectML | High memory bandwidth (>50 tok/s) |
| Piper Neural TTS | CPU (E-Cores) | FP32 / INT8 | OneDNN / AVX2 | Low latency, zero GPU contention |
| MobileNet OCR | NPU | INT8 | DirectML / QNN | Parallel visual grounding |


