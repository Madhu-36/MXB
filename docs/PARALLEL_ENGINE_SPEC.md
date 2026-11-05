# MXB v2.1 Parallel Engine Specification

## Architectural Overview

Machine eXecutive Brain (MXB) v2.1 is built on an asynchronous, decoupled multi-threaded pipeline designed to provide continuous voice comprehension and full desktop automation without audio frame loss or UI freezing.

```
+---------------------------------------------------------------------------------------+
|                                    USER AUDIO                                         |
+---------------------------------------------------------------------------------------+
                                           |
                                           v
               [ Stage 1: Continuous Audio Ingestion (sounddevice) ]
                 - Native 16 kHz, 32-bit Float, 512-sample blocks
                 - Low-latency callback -> Non-blocking push to raw_audio_queue
                                           |
                                           v
                    [ Stage 2: Real-time Neural VAD (Silero) ]
                 - Sub-0.2ms chunk evaluation (<0.6% CPU utilization)
                 - Adaptive Gain Control (AGC) + Soft tanh limiting
                 - Segments complete speech utterances -> utterance_queue
                                           |
                                           v
               [ Stage 3: Asynchronous Speech Recognition (Parallel ASR) ]
                 - Worker Thread: "MXB-Parallel-ASR"
                 - Cloud NVIDIA Build Riva / Local Faster-Whisper
                 - Immediate Voice Interruption Interceptor:
                   "stop", "cancel", "halt", "pause", "abort", "shut up"
                   -> Triggers instant OSExecutionManager.abort_current_action()
                 - Non-stop commands -> action_task_queue
                                           |
                                           v
               [ Stage 4: Asynchronous Action Execution (Parallel Action) ]
                 - Worker Thread: "MXB-Parallel-Action"
                 - Tier 1: Sub-millisecond deterministic fast-path
                 - Tier 2: LLM Multi-step Action Planner (llama3.2:1b / NVIDIA)
                 - Real-time step progress streaming to Floating Cyber HUD
                                           |
                                           v
                  [ Stage 5: "Two Hands" OS Automation Execution ]
                 - Mouse Controller (Click, Drag, Notch Scroll)
                 - Extended Keyboard (VK Mapping, Win Shortcuts, Fast Paste)
                 - Screen Vision (Hardware-accelerated grab + Native Windows OCR)
                 - Safe File Operations Manager (Desktop/Downloads/Create/Delete)
```

## Thread & Queue Contracts

| Stage | Thread Name | Input Queue | Output Queue | Max Latency |
| :--- | :--- | :--- | :--- | :--- |
| **Stage 1: Capture** | `PortAudio Callback` | Hardware Mic | `raw_audio_queue` (150 max) | < 2 ms |
| **Stage 2: VAD** | `VoicePipeline` (QThread) | `raw_audio_queue` | `utterance_queue` (10 max) | < 0.2 ms / chunk |
| **Stage 3: ASR** | `MXB-Parallel-ASR` | `utterance_queue` | `action_task_queue` (15 max) | ~ 200 - 800 ms |
| **Stage 4: Action** | `MXB-Parallel-Action` | `action_task_queue` | Action Execution | Variable (step-based) |
| **Stage 5: Audio Out**| `TTSThread` (QThread) | `text_queue` (Queue) | Windows SAPI SpVoice | Asynchronous |

## Emergency Interruption Safety Guarantee

When an action plan is executing (e.g. typing a long paragraph or navigating multiple windows), the microphone stream remains 100% active. If the user utters an emergency halt word:
1. `MXB-Parallel-ASR` intercepts the word directly from transcription.
2. `self.router.executor.abort_current_action()` sets `ActionPlanner._abort_event`.
3. The running plan detects the flag within 50 ms (via sliced delay polling), halts immediately, and drains all downstream pending tasks.
