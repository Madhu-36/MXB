# MXB V2.0 - Local Inference Engine & LLM Runtime Architecture

## 1. Executive Summary & Core Runtime Vision
MXB V2.0 embeds a high-performance, air-gapped Large Language Model inference engine optimized for consumer GPUs and multicore CPUs. By leveraging native C++ `llama.cpp` bindings, low-precision quantized weights (GGUF), and grammar-constrained decoding, MXB delivers real-time token generation with zero cloud latency and total privacy.

```
+-----------------------------------------------------------------------------------+
|                        MXB Local LLM Inference Pipeline                           |
|                                                                                   |
|  [ User Prompt + System Context ]                                                 |
|                 |                                                                 |
|                 v                                                                 |
|     [ Tokenizer / Vocab Map ]                                                     |
|                 |                                                                 |
|                 v                                                                 |
|   +-------------+-------------------------------------------------------------+   |
|   | KV-Cache Manager (Q8_0 Paged Allocation + Rolling Context Shift)          |   |
|   +---------------------------------------------------------------------------+   |
|                 |                                                                 |
|                 v                                                                 |
|   [ Tensor Forward Pass (CUDA / DirectML / AVX-512) ]                             |
|   - FlashAttention-2 Matrix Math                                                  |
|   - Split Layer Offloading: VRAM (GPU) <-> Pinned RAM (CPU)                       |
|                 |                                                                 |
|                 v                                                                 |
|   [ Logit Sampler + GBNF Grammar Filter (Strict JSON Tool Schema) ]               |
|                 |                                                                 |
|                 v                                                                 |
|   [ Streaming Token Yield ] ---> (PySide6 HUD + Piper Audio Synthesizer)          |
+-----------------------------------------------------------------------------------+
```

The runtime operates within strict VRAM budgets (3.5 GB to 8.0 GB), providing deterministic sub-300ms Time-To-First-Token (TTFT) and throughput upwards of 55 tokens/second.


