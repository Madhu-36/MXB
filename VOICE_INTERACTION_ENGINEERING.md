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


## 3. Acoustic Echo Cancellation (AEC3) & Reference Loopback
When MXB speaks through the laptop speakers, its own voice leaks directly into the microphone. Without AEC, the assistant transcribes its own output, triggering an infinite conversational loop.

### AEC3 Reference Architecture
- **Reference Stream**: Windows WASAPI Loopback captures the exact PCM output buffer sent to the speakers.
- **Adaptive Filter**: AEC3 continuously computes room impulse response (RIR) transfer functions.
- **Echo Subtraction**: The synthesized signal is subtracted from the microphone capture with $> 45	ext{ dB}$ Echo Return Loss Enhancement (ERLE).

```c
// Feed speaker playback reference into AEC filter
ApmProcessReverseStream(apm_handle, speaker_pcm_16k, frame_size);
// Process microphone stream and subtract acoustic echo
ApmProcessStream(apm_handle, mic_pcm_16k, clean_output_pcm);
```


## 4. Multi-Channel Microphone Array Beamforming
Modern laptops and USB conference microphones feature 2-to-4 microphone arrays. MXB exploits spatial separation using Minimum Variance Distortionless Response (MVDR) beamforming.

### Spatial Filtering Pipeline
- **Delay-and-Sum Calibration**: Measures Time Difference of Arrival (TDOA) between mic capsules.
- **Steering Vector**: Directs an acoustic reception cone toward the user's angular direction ($\pm 30^\circ$).
- **Null Placement**: Steers deep acoustic nulls toward laptop cooling fan exhausts and internal chassis noise sources.


## 5. Dual-Stage Stationary & Neural Noise Suppression
Consumer environments contain both steady background noise (fans, PC cooling, refrigerator hum) and dynamic transient noise (dishes, traffic, pet sounds).

### Hybrid Suppression Stack
- **Stage 1 (Stationary Spectral Subtraction)**: Computes ambient noise floor profiles during silence frames and subtracts stationary frequencies.
- **Stage 2 (RNNoise Recurrent Neural Network)**: A lightweight GRU network (85,000 parameters) analyzes 22 Bark frequency bands to separate human vocal tract formants from non-stationary noise.

Execution overhead is under 0.8% CPU on a single core while delivering up to 24 dB Signal-to-Noise Ratio (SNR) improvements.


## 6. Adaptive Automatic Gain Control (AGC2)
Users speak at varying volumes—from quiet whispers late at night to loud speech across the room.

### AGC2 Dynamic Leveling
- **Target RMS Level**: Normalized to **-18 dBFS** for optimal Whisper Mel-spectrogram feature extraction.
- **Compression Knee**: Soft-knee limiter preventing digital clipping when users suddenly laugh or speak loudly.
- **Fast Attack, Slow Decay**: 10ms attack time prevents clipping, while 500ms release avoids volume pumping during short vocal pauses.


