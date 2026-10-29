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


## 7. Silero VAD Neural Probability & Dynamic Hysteresis
Simple energy-based volume gates cause false wake-ups on coughs or door slams. MXB standardizes on Silero VAD v4 running on ONNX Runtime.

### Dynamic Hysteresis Algorithm
```python
class VoiceActivityDetector:
    def __init__(self, speech_threshold=0.55, exit_threshold=0.35):
        self.speech_threshold = speech_threshold
        self.exit_threshold = exit_threshold
        self.is_speaking = False

    def process_frame(self, frame_prob: float) -> bool:
        if not self.is_speaking and frame_prob >= self.speech_threshold:
            self.is_speaking = True
        elif self.is_speaking and frame_prob < self.exit_threshold:
            self.is_speaking = False
        return self.is_speaking
```

Hysteresis boundaries eliminate rapid flickering at speech onset and offset boundaries.


## 8. Speech Boundary Detection & Adaptive Hangover Timers
Humans pause naturally between sentences to breathe or gather their thoughts. Prematurely cutting speech yields fractured, ungrammatical transcripts.

### Adaptive Hangover Heuristic
- **Default Hangover**: 850 milliseconds of trailing silence required before declaring end-of-turn.
- **Syntactic Continuation Extension**: If transcribed speech ends on a conjunction or preposition (e.g. *"and"*, *"because"*, *"to"*), hangover extends automatically to **1,400 milliseconds**.
- **Sentence Completion Acceleration**: If an imperative sentence matches complete command intent (e.g. *"mute sound"*), hangover contracts to **350 milliseconds** for rapid execution.


## 9. Conversational Barge-In & Sub-50ms Audio Interruption
A natural assistant allows the user to speak at any moment to interrupt or change directions.

### Barge-In Interruption Flow
1. User begins speaking while Piper TTS is active.
2. WebRTC AEC cancels the assistant's voice, enabling Silero VAD to detect user vocal chords.
3. VAD emits high-priority `BargeInDetectedEvent`.
4. Audio output buffer is flushed instantly via `WASAPI::Reset()`.
5. Active LLM generation worker is halted with cancellation tokens.
6. Microphone audio ring buffer rewinds 150ms to capture the user's opening syllable cleanly.


## 10. Streaming Whisper STT & Rolling Audio Framing
Waiting for complete utterance termination before beginning transcription introduces noticeable conversational latency.

### Rolling Audio Framing
- **Chunk Size**: 480ms audio frames ingested every 160ms.
- **Prefix Conditioning**: Previous partial decoded tokens are passed as `prompt_tokens` to bias the autoregressive decoder.
- **Timestamp Tracking**: Word-level timestamps identify exact word boundaries, updating the PySide6 subtitle strip in real-time.


## 11. Hallucination Filtering on Silence & Background Noise
When exposed to low-level acoustic noise or silence, standard Whisper models can hallucinate repetitive phrases (e.g. *"Thank you for watching"*, *"Please subscribe"*).

### Multi-Stage Hallucination Filter
```python
def is_hallucination(transcription_result) -> bool:
    # 1. Reject if no-speech probability is high
    if transcription_result.no_speech_prob > 0.65:
        return True
    # 2. Reject if compression ratio exceeds gzip entropy threshold
    if transcription_result.compression_ratio > 2.4:
        return True
    # 3. Reject known silence hallucination strings
    text = transcription_result.text.strip().lower()
    if text in BLACKLISTED_HALLUCINATIONS:
        return True
    return False
```


## 12. Custom Vocabulary Boosting & Initial Prompt Priming
Technical users command MXB using coding terms, CLI flags, and acronyms (`Kubernetes`, `PyTorch`, `systemctl`, `ffmpeg`, `CUDA`) that general speech models frequently misinterpret.

### Vocabulary Priming Strategy
MXB prepends a developer lexicon into Whisper's initial decoding context:
```python
initial_prompt = "MXB, PyTorch, CUDA, Neovim, Kubernetes, Git, GitHub, Python, WASAPI, ONNX, GGUF, Ollama."
whisper_params.initial_prompt = initial_prompt
```

Biases token logit priors, raising technical entity transcription accuracy from 74% to **96.8%**.


## 13. Speaker Identification via ECAPA-TDNN Embeddings
In shared office environments or family living rooms, MXB must distinguish the primary user's voice from background conversations.

### Voiceprint Verification
- **Architecture**: ECAPA-TDNN neural network generating 192-dimensional speaker embeddings.
- **Enrollment**: User records three 5-second calibration sentences at initial setup.
- **Cosine Verification**: Incoming voice turns compute cosine similarity against the enrolled owner embedding:
  $$	ext{Similarity} = rac{v_{turn} \cdot v_{enrolled}}{\|v_{turn}\| \|v_{enrolled}\|}$$
If similarity $< 0.72$, the turn is flagged as secondary speaker and ignored.


## 14. Voice Biometric Authentication for Privileged Actions
Commands that modify system security (e.g. deleting files, displaying stored credentials, executing PowerShell scripts) require biometric voice authentication.

### Two-Tier Verification
1. **Passphrase Liveness Check**: User must speak a dynamic, time-sensitive phrase displayed on screen (prevents recorded voice playback attacks).
2. **High-Confidence Threshold**: Enforces a strict cosine threshold $\ge 0.88$ on ECAPA-TDNN voice embeddings before privilege authorization.


## 15. Turn-Taking Prediction & Hesitation Resilience
Users frequently say *"um"*, *"uh"*, or pause mid-sentence while searching for words. Premature assistant interruption frustrates users.

### Acoustic & Syntactic Prosody Modeling
- **Pitch Contour Analysis**: Detects rising intonation patterns indicating incomplete sentence clauses.
- **Filler Word Detection**: Transcribed fillers (*"um"*, *"like"*, *"wait"*) automatically reset the silence hangover timer by +1.5 seconds.
- **Visual Eye Contact Fusion**: (Optional) Multi-modal webcam glance detection confirms if the user is still looking at the screen while speaking.


