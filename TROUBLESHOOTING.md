
## Troubleshooting Case 1: Initialize MXB Diagnostics & Troubleshooting Guide
Welcome to the MXB comprehensive diagnostics guide. This document provides step-by-step solutions for common operational issues.

## Troubleshooting Case 2: Diagnose Ollama daemon connection refused errors
Troubleshoot 11434 connection refused by verifying ollama serve status, firewall rules, and localhost bindings.

## Troubleshooting Case 3: Resolve CUDA out-of-memory errors on local GPU
Mitigate VRAM allocation limits by adjusting num_gpu offload layers and context size num_ctx in the Modelfile.

## Troubleshooting Case 4: Fix PyAudio PortAudio host API initialization failure
Address missing PortAudio DLLs and ensure 64-bit PyAudio wheels are installed in the virtual environment.

## Troubleshooting Case 5: Address WASAPI Realtek audio sample rate mismatch
Resolve Windows WASAPI hardware conflicts by querying device native sample rate and resampling to 16kHz via Torchaudio.

## Troubleshooting Case 6: Fix microphone silence and low input gain issues
Configure Windows Sound Control Panel microphone boost and calibrate PyAudio RMS threshold above noise floor.

## Troubleshooting Case 7: Diagnose Whisper model download timeout and SSL errors
Troubleshoot HuggingFace/OpenAI Whisper checkpoint downloads with retry proxies and manual weight staging.

## Troubleshooting Case 8: Resolve Voice Activity Detection (VAD) false triggers
Tweak silence hangover time (1.2s) and RMS energy thresholds to prevent continuous background triggering.

## Troubleshooting Case 9: Fix PySide6 Qt platform plugin windows errors
Address missing Qt DLL dependencies by setting QT_QPA_PLATFORM_PLUGIN_PATH within the active virtualenv.

## Troubleshooting Case 10: Resolve HUD glassmorphism transparency artifacting
Fix black backdrop glitches by enabling WA_TranslucentBackground and frameless window flags before show().

## Troubleshooting Case 11: Fix pyttsx3 COM SAPI5 initialization in background thread
Prevent silent voice synth hang by ensuring pythoncom.CoInitialize() is invoked before pyttsx3.init() in QThread.

## Troubleshooting Case 12: Resolve pynput global keyboard hook permissions on Windows
Address global hotkey interception failure under elevated Administrator windows and UAC boundaries.

## Troubleshooting Case 13: Fix win11toast notification center blockage
Ensure application app_id is registered with Windows Action Center to avoid silent notification suppression.

## Troubleshooting Case 14: Resolve DuckDuckGo search rate limit and captcha blocks
Implement exponential backoff retries and fallback query scrapers when DDGS encounters rate limiting.

## Troubleshooting Case 15: Fix IP-based geolocation lookup timeouts
Add fallback endpoints (ip-api, ipapi.co) and local GPS cache fallback when geolocation requests exceed timeout.

## Troubleshooting Case 16: Resolve Open-Meteo weather API serialization failures
Handle null values in hourly weather telemetry and gracefully degrade to standard temperature forecast.
