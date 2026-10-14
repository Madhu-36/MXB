
## Configuration 1: Initialize Configuration & Environment Guide
Welcome to the MXB configuration manual. This guide outlines all environment variables and configuration options for V2.0.

## Configuration 2: Document Ollama host and port settings
Configure OLLAMA_HOST and port bindings (defaults to localhost:11434) for local inference connectivity.

## Configuration 3: Define Llama 3.1 model parameter overrides
Documented model context length (num_ctx=4096) and GPU offload layer parameters in the Modelfile.

## Configuration 4: Document temperature and top_p sampling configs
Detailed default temperature (0.2 for deterministic JSON routing) and top_p (0.9) parameters.

## Configuration 5: Add Whisper model size options (tiny, base, small)
Outlined Whisper STT model selection trade-offs between latency and word error rate on local CPU/GPU.

## Configuration 6: Document Voice Activity Detection (VAD) thresholds
Configured RMS audio volume activation floor (0.015) and silence hangover duration (1.2s).

## Configuration 7: Detail audio sample rate and downmixing settings
Documented 16,000 Hz target sample rate, 16-bit PCM format, and stereo-to-mono downmixing logic.

## Configuration 8: Add microphone input device index selection
Provided instructions for specifying default PyAudio input device indices via config.

## Configuration 9: Document PySide6 UI opacity and glassmorphism styling
Documented frameless window flags, translucency settings, and backdrop blur parameters in HUD.

## Configuration 10: Add HUD animation duration and easing curves
Configured QPropertyAnimation fade-in/fade-out curves (QEasingCurve.InOutQuad, 300ms).
