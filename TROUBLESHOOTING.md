
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
