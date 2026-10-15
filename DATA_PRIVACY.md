
## Privacy Standard 1: Initialize MXB Zero-Telemetry & Data Privacy Charter
Started zero-telemetry and data privacy charter establishing strict offline-first principles.

## Privacy Standard 2: Define Local-First offline inference processing boundaries
Established that all LLM inference and speech recognition execute exclusively on local hardware with zero cloud relay.

## Privacy Standard 3: Document Voice Audio ephemeral memory buffer lifecycle
Specified that microphone audio streams reside strictly in volatile RAM and are overwritten after inference.

## Privacy Standard 4: Specify zero audio disk persistence policy for raw PCM streams
Documented architectural guarantee that raw audio waveforms are never saved to disk under any operational state.

## Privacy Standard 5: Detail memory_bank.json local storage encryption mechanisms
Outlined optional AES-256 local file encryption for conversation memory bank persistent storage.

## Privacy Standard 6: Document user memory retention, redaction, and deletion policies
Documented CLI commands and voice actions for purging individual memories or entire memory banks.

## Privacy Standard 7: Outline DuckDuckGo anonymous search query scrubbing
Documented client-side query sanitization stripping user identifiers prior to web search dispatch.

## Privacy Standard 8: Document Open-Meteo non-tracking IP weather lookup policy
Specified non-commercial open API usage with zero tracking headers or API key telemetry.

## Privacy Standard 9: Detail active window title sanitization and sensitive app masking
Implemented process blacklist masking window titles from banking apps, password managers, and private browsers.

## Privacy Standard 10: Document clipboard privacy and password manager ignore list
Ensured clipboard history is never passively read or ingested into LLM context prompts.
