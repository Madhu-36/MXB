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


