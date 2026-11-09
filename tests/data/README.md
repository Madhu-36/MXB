# Test data

- `speech_jfk_4s.wav`: the first 4 seconds of John F. Kennedy's 1961 inaugural address ("And so, my fellow
  Americans, ask not…"), 16 kHz mono. A public-domain recording, the same clip faster-whisper and OpenAI
  Whisper use in their own tests. `tests/test_v43_listening.py` plays it at a quiet laptop-microphone level
  through the real Silero voice detector.
