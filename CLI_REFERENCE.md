
## CLI Command 1: Initialize MXB Command-Line Interface & Headless Manual
Started comprehensive CLI command reference and terminal automation manual for MXB V2.0.

## CLI Command 2: Document core executable flags (--headless, --debug, --version)
Documented root CLI flags for headless execution without PySide6 HUD, debug verbose logging, and SemVer version reporting.

## CLI Command 3: Add audio device enumeration command (mxb audio --list-devices)
Documented PyAudio host API querying and input/output index enumeration with supported sample rate reporting.

## CLI Command 4: Document microphone sensitivity calibration tool (mxb audio --calibrate)
Added instructions for interactive ambient noise floor measurement and optimal RMS threshold calculation.

## CLI Command 5: Add VAD energy threshold test mode (mxb audio --test-vad)
Documented real-time terminal VU meter visualization showing speech activation thresholds and silence hangover timers.

## CLI Command 6: Document Ollama inference ping command (mxb llm --ping)
Added connectivity verification command checking Ollama HTTP REST daemon availability on localhost:11434.

## CLI Command 7: Add Modelfile recompile trigger flag (mxb llm --recompile)
Documented manual re-compilation trigger for rebuilding the local Ollama Modelfile with updated system prompts.

## CLI Command 8: Document memory bank query tool (mxb memory --query <text>)
Documented terminal search command querying memory_bank.json using TF-IDF cosine similarity scoring.

## CLI Command 9: Add memory bank inspection and stats command (mxb memory --stats)
Documented metadata readout reporting total conversation count, unique vocabulary size, and memory file size.

## CLI Command 10: Document memory bank backup command (mxb memory --backup)
Documented timestamped snapshot generation creating atomic JSON archives in %APPDATA%\MXB\backups.

## CLI Command 11: Add memory bank pruning and purge flag (mxb memory --purge)
Documented retention cleanup utility for pruning memories older than N days or eradicating entire conversation histories.

## CLI Command 12: Document live desktop notification test (mxb notify --test)
Added CLI verification utility dispatching test Windows 11 Action Center toast notifications.

## CLI Command 13: Add active window tracker monitoring mode (mxb window --monitor)
Documented continuous terminal logger outputting Win32 active window titles, process names, and PID transitions.

## CLI Command 14: Document SmartAppLauncher fuzzy search utility (mxb app --search <query>)
Documented fuzzy match search utility querying installed Start Menu shortcuts and reporting resolve paths.

## CLI Command 15: Add Start Menu index rebuilding command (mxb app --reindex)
Documented background filesystem crawler refreshing the local cached shortcut registry in memory.

## CLI Command 16: Document DuckDuckGo headless query tool (mxb search --query <term>)
Documented headless search command retrieving raw search snippets and piped summaries via Llama 3.1.

## CLI Command 17: Add weather telemetry lookup command (mxb weather --current)
Documented standalone weather reporting tool fetching Open-Meteo forecasts for auto-detected GPS coordinates.

## CLI Command 18: Document system diagnostics telemetry readout (mxb diag --full)
Documented comprehensive system status report outputting CPU, GPU, RAM, VRAM, and thermal sensors via psutil.

## CLI Command 19: Add SAPI5 TTS speech test flag (mxb voice --speak <text>)
Documented terminal synthesis utility testing Microsoft SAPI5 voice output, speech rate, and volume.
