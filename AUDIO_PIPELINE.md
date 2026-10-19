
## Audio Component 1: Initialize MXB Real-Time Audio Pipeline Architecture
Started comprehensive audio engineering specification for MXB real-time speech processing subsystems.

## Audio Component 2: Detail PortAudio backend driver enumeration and host APIs
Documented PyAudio binding architecture querying WASAPI, DirectSound, and MME host API endpoints on Windows.

## Audio Component 3: Document Windows WASAPI Exclusive vs Shared stream modes
Outlined latency benefits and exclusivity trade-offs when accessing low-level Windows WASAPI audio streams.

## Audio Component 4: Specify 48kHz hardware capture and PyAudio buffer sizing
Documented native Realtek 48,000 Hz 16-bit PCM capture stream configuration using 1024-sample frames.

## Audio Component 5: Document Torchaudio 16kHz resampler and downmixing math
Detailed real-time polyphase FIR filter downsampling converting 48kHz stereo to 16kHz mono audio tensors.

## Audio Component 6: Detail Voice Activity Detection sliding window ring buffer
Specified circular ring buffer holding the most recent 1.5 seconds of ambient audio for continuous speech onset detection.

## Audio Component 7: Document RMS volume energy calculation and noise floor baseline
Documented root-mean-square energy calculation measuring ambient acoustic decibels to adaptively calibrate thresholds.

## Audio Component 8: Detail dynamic silence hangover timer and speech segmentation
Configured 1.2-second trailing silence hangover timer preventing premature speech chunk truncation during natural pauses.

## Audio Component 9: Document Whisper STT audio tensor normalization
Outlined float32 conversion and amplitude normalization scaling PCM int16 values into continuous [-1.0, 1.0] ranges.

## Audio Component 10: Specify 30-second Mel spectrogram feature extraction
Documented 80-channel log-magnitude Mel-frequency filterbank feature extraction for Whisper transformer encoder.

## Audio Component 11: Document Whisper encoder forward pass and beam search decoding
Detailed greedy and beam search autoregressive token generation decoding audio features into transcribed English text.

## Audio Component 12: Detail hallucination filtering for silence audio frames
Documented compression ratio and no-speech probability heuristic filters discarding phantom transcriptions on silence.

## Audio Component 13: Document hotkey-triggered manual microphone mute overrides
Specified global Ctrl+Shift+M hardware mute bypass disconnecting audio ingestion streams at the driver level.

## Audio Component 14: Detail acoustic echo cancellation during TTS playback
Documented software AEC ducking incoming microphone gain while SAPI5 text-to-speech audio is actively outputting.

## Audio Component 15: Document SAPI5 COM speech synthesis threading architecture
Outlined Windows COM automation apartment threading rules requiring pythoncom.CoInitialize() within dedicated QThreads.

## Audio Component 16: Detail asynchronous QThread audio generation and UI safety
Specified decoupled worker thread lifecycle preventing PySide6 HUD animation stutter during synchronous speech synthesis.
