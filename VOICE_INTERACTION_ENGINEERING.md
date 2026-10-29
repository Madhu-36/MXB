# MXB V2.0 - Voice Interaction Engineering & Full-Duplex Conversational Pipeline

## 1. Executive Summary & Acoustic Vision
MXB V2.0 re-engineers human-computer interaction by treating voice as a first-class, **full-duplex conversational stream**. Rather than employing a brittle "push-button, wait, listen" walkie-talkie paradigm, MXB continuously monitors acoustic environments, isolates user speech amidst background noise, and allows natural conversational barge-in without audio feedback loops.

```
+-----------------------------------------------------------------------------------+
|                        MXB Full-Duplex Acoustic Architecture                      |
|                                                                                   |
|  [ Microphones ]                                      [ System Audio Reference ]  |
|         |                                                         |               |
|         v                                                         v               |
|  +-----------------------------------------------------------------------------+  |
|  |               WebRTC APM (Acoustic Echo Cancellation - AEC3)                |  |
|  +-----------------------------------------------------------------------------+  |
|         |                                                                         |
|         v                                                                         |
|  [ Multi-Channel Beamforming & Dual-Stage Noise Suppression (RNNoise) ]           |
|         |                                                                         |
|         v                                                                         |
|  [ Silero Neural VAD ] ---> [ Speech Segmentation ] ---> [ Whisper.cpp Engine ]   |
|         |                                                         |               |
|         v (Barge-In Interrupt Event)                              v               |
|  [ Audio Playback Engine ] <============================= [ LLM + Piper TTS ]     |
|  (Instant Mute & Ducking)                                 (Streamed PCM Chunks)   |
+-----------------------------------------------------------------------------------+
```

### Core Conversational SLAs
- **Barge-In Interruption Latency**: < 45 milliseconds to mute active TTS playback upon user speech onset.
- **Far-Field Wakeup Sensitivity**: > 98.5% detection at 3.5 meters in 65 dBA ambient noise.
- **Audio Ducking Transition**: Smooth 20ms sigmoid attenuation of system media (Spotify/Games) by 18 dB.


## 2. Real-Time Acoustic Signal Pre-Processing via WebRTC APM
Raw microphone inputs suffer from room reverberation, DC offset, and non-linear harmonic distortion. MXB integrates the native WebRTC Audio Processing Module (APM) via C++ DLL bindings.

### Pre-Processing Stages
1. **High-Pass Filter (HPF)**: 80 Hz cutoff removing sub-bass rumble, air-conditioning hum, and mechanical desk vibrations.
2. **DC Offset Removal**: Normalizes hardware sample drift to 0.0V DC.
3. **Transient Suppression**: Detects and attenuates keyboard typing clicks and mouse switches before feeding the speech recognizer.

```python
import webrtc_apm

apm = webrtc_apm.AudioProcessor(
    sample_rate=16000,
    channels=1,
    high_pass_filter=True,
    typing_detection=True
)
```


