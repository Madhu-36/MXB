# MXB V2.0 - NVIDIA Build NIM Cloud & Hybrid Speech Intelligence Architecture

## 1. Executive Overview & System Topology
MXB V2.0 introduces a state-of-the-art **Hybrid Speech Intelligence Engine** leveraging **NVIDIA Build (NVIDIA NIM Microservices)** cloud acceleration paired with an autonomous local edge fallback.

```
+---------------------------------------------------------------------------------------+
|                    MXB V2.0 Hybrid Speech Intelligence Architecture                   |
|                                                                                       |
|  [ Realtek / Noise Airwave Mic ]                                                      |
|                 |                                                                     |
|                 v                                                                     |
|  [ Adaptive VAD (0.00035 RMS) + 480ms Pre-Roll Ring Buffer ]                          |
|                 |                                                                     |
|                 v                                                                     |
|  [ Digital AGC (40x Boost) + Peak Soft Limiter (0.85 Target) ]                        |
|                 |                                                                     |
|                 v                                                                     |
|       { Internet & NVIDIA API Key Active? }                                           |
|            /                         \                                               |
|          YES                          NO (Offline / Network Drop)                     |
|          /                             \                                             |
|         v                               v                                             |
|  [ NVIDIA Build Cloud ASR ]             [ Local Faster-Whisper CPU Int8 ]             |
|  - Model: Parakeet-TDT 0.6B             - Model: base.en                              |
|  - Latency: 0.20 seconds                - Latency: 1.5 seconds                        |
|  - Zero CPU Load                        - Offline Resilient                           |
|         |                               |                                             |
|         +-------------------------------+                                             |
|                         |                                                             |
|                         v                                                             |
|          [ Layer 1: Sub-Millisecond Deterministic Fast-Path ]                         |
|            - OS Apps, Window Control, Media Keys, Telemetry                           |
|                         |                                                             |
|                         v (Complex / Conversational Fallthrough)                      |
|       { Internet & NVIDIA API Key Active? }                                           |
|            /                         \                                               |
|          YES                          NO                                              |
|          /                             \                                             |
|         v                               v                                             |
|  [ NVIDIA Build Cloud LLM ]             [ Local Ollama Llama-3.1 8B ]                 |
|  - meta/llama-3.1-8b-instruct           - mxb-brain:latest                            |
|  - Latency: 0.25 seconds                - Latency: 45.0 seconds on CPU                |
+---------------------------------------------------------------------------------------+
```

### Core Architecture Milestones
- **Sub-300ms End-to-End Voice Cycle**: Cloud GPU transcription reduces audio turn-around from multi-second delays to real-time conversation.
- **Ultra-Sensitive Adaptive VAD**: Detects human speech down to 0.00035 RMS while rejecting static ambient hiss.
- **Fail-Safe Offline Autonomy**: If internet connectivity is interrupted, MXB seamlessly switches to local Whisper and deterministic routing without a restart.


## 2. NVIDIA Parakeet FastConformer ASR Architecture
The primary cloud automatic speech recognition (ASR) engine uses NVIDIA's **Parakeet** neural architecture built with the NeMo framework.

### Architecture Specifications
- **Backbone**: FastConformer encoder utilizing depthwise separable convolutions and multi-head self-attention.
- **Decoding Mechanism**: Token-and-Duration Transducer (TDT) and Connectionist Temporal Classification (CTC).
- **Acoustic Subsampling**: 8x subsampling rate minimizes compute footprint while preserving precise word boundary timestamps.
- **Vocabulary**: 1,024 SentencePiece byte-pair tokens trained over 65,000+ hours of multi-accented speech.


