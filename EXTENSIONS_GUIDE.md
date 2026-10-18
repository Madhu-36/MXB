
## Plugin Topic 1: Initialize MXB Extensions & Plugin Developer Guide
Started comprehensive developer manual for creating third-party extensions and plugins for MXB V2.0.

## Plugin Topic 2: Define Plugin manifest schema (plugin.json) and metadata
Documented plugin.json manifest structure including plugin ID, name, version, author, entrypoint, and required permissions.

## Plugin Topic 3: Document BasePlugin class lifecycle (on_load, on_unload)
Outlined core BasePlugin class interface with synchronous setup and teardown lifecycle methods.

## Plugin Topic 4: Add Custom Voice Intent registration API (register_intent)
Documented voice command registration API enabling extensions to register new voice keywords and action handlers.

## Plugin Topic 5: Document Intent pattern matching and regex slot extraction
Detailed named entity slot extraction from transcribed speech using regex patterns and fuzzy matching.

## Plugin Topic 6: Add Event Bus hook subscription model (subscribe, emit)
Documented internal pub/sub event bus enabling decoupled communication between plugins and core engine components.

## Plugin Topic 7: Document Audio Stream filter interception callbacks
Added audio hook specification allowing plugins to process, filter, or record real-time raw PCM audio buffers.

## Plugin Topic 8: Add LLM prompt context injection hooks (on_prompt_build)
Documented hook for injecting custom dynamic context (e.g. calendar events, clipboard text) into the Llama 3.1 system prompt.

## Plugin Topic 9: Document LLM response post-processing middleware
Outlined filter pipeline allowing plugins to intercept, mutate, or format model responses before TTS audio synthesis.

## Plugin Topic 10: Add Custom App Launcher rule providers
Documented SmartAppLauncher provider interface for registering custom URI schemes, web bookmarks, and scripts.

## Plugin Topic 11: Document Subprocess Sidecar IPC over standard I/O (JSON-RPC)
Specified bidirectional JSON-RPC 2.0 protocol for running resource-intensive plugins in isolated subprocesses.

## Plugin Topic 12: Add PySide6 Custom HUD widget injection guidelines
Documented guidelines for attaching custom QWidget overlays and visual status badges to the floating glassmorphism HUD.

## Plugin Topic 13: Document SAPI5 and custom TTS voice output overrides
Outlined custom audio playback routing allowing plugins to substitute Piper or ElevenLabs neural TTS engines.
