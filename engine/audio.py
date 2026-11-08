import io
import time
import wave
import queue
import threading
import requests
import collections
import traceback
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from faster_whisper.vad import get_vad_model
from PySide6.QtCore import QThread, Signal
from engine.barge_in import BargeInDetector, is_probable_echo, resolve_mode
from engine.listening import (InputAGC, StreamingVAD, clean_transcript, energy_speech_prob, is_speech, max_tokens_for,
                              whisper_options)
from utils.credentials import CredentialsManager
from utils.logger import log

class VoicePipeline(QThread):
    """
    MXB v2.1 Decoupled Asynchronous Parallel Voice Pipeline.
    Architecture:
    1. Audio Ingestion: Non-blocking sounddevice callback feeding raw chunks.
    2. Real-time Neural VAD Worker: Silero VAD runs continuously (<0.2ms/chunk) without stalls.
    3. Asynchronous ASR Worker: Transcribes speech utterances without blocking audio capture.
    4. Asynchronous Action Worker: Dispatches and executes desktop actions in parallel.
    5. Live Voice Interruption: Intercepts 'stop' / 'cancel' immediately during active actions.

    v3: transcripts are handed to the shared CommandBus (same path as typed chat),
    which owns the wake-word gate, confirmations, stop handling and the parallel
    action/info lanes. The microphone never stops listening while MXB works.
    """

    vad_status_changed = Signal(str)
    transcription_ready = Signal(str)
    action_feedback = Signal(str)
    mic_level_signal = Signal(float)

    def __init__(self, config, bus=None):
        super().__init__()
        self.config = config
        self.is_running = True
        self.is_listening = True
        self.is_tts_speaking = False
        self.tts_finish_time = 0.0

        if bus is None:
            from engine.command_bus import CommandBus
            bus = CommandBus(config)
        self.bus = bus
        self.router = bus.router
        # Live step feedback from the bus also drives the HUD action line.
        self.bus.feedback.connect(self.action_feedback.emit)

        # Connect TTS signals for echo suppression
        self.router.tts.started_speaking.connect(self._on_tts_started)
        self.router.tts.finished_speaking.connect(self._on_tts_finished)

        self.sample_rate = 16000
        self.blocksize = 512

        # Thread-safe queues connecting the concurrent pipeline stages
        self.raw_audio_queue = queue.Queue(maxsize=150)
        self.utterance_queue = queue.Queue(maxsize=10)
        self.action_task_queue = self.bus.action_queue  # kept for backward compatibility

        # 800ms pre-roll audio ring buffer to preserve leading syllables
        self.preroll_buffer = collections.deque(maxlen=25)

        # v4.3.1: microphone gain BEFORE voice detection (quiet laptop mics reached the VAD at -48 dBFS)
        self.agc = InputAGC.from_config(config if isinstance(config, dict) else {})
        self._gain_log = (0.0, None)          # (time, dB) of the last gain line written to the log

        # Silero neural VAD model lazy loader (+ the streaming wrapper built in run())
        self._vad_model = None
        self._vad = None
        self.whisper_model = None

        # Worker threads
        self._asr_thread = None

        # v4: barge-in (talk over MXB) and offline audio wake word
        voice_cfg = config.get("voice", {}) if isinstance(config, dict) else {}
        self.barge_in_setting = voice_cfg.get("barge_in", "auto")
        self.barge_in_mode = "off"            # resolved once the microphone is known
        self.barge_detector = BargeInDetector()
        listen_cfg = config.get("listening", {}) if isinstance(config, dict) else {}
        self.wake_engine = None
        if listen_cfg.get("engine", "transcript") == "openwakeword":
            from engine.wake_engine import OpenWakeWordEngine, wake_phrase_words
            model = listen_cfg.get("openwakeword_model", "hey_jarvis")
            self.wake_engine = OpenWakeWordEngine(model, float(listen_cfg.get("openwakeword_threshold", 0.5)))
            for phrase in wake_phrase_words(model):
                self.bus.wake.add_wake_word(phrase)

    def _get_vad_model(self):
        if self._vad_model is None:
            try:
                log.info("Loading Silero Neural VAD engine...")
                self._vad_model = get_vad_model()
                log.info("Silero Neural VAD engine loaded successfully.")
            except Exception as e:
                log.error(f"Failed to load Silero VAD: {e}")
                self._vad_model = None
        return self._vad_model

    def _on_tts_started(self):
        self.is_tts_speaking = True
        self.barge_detector.reset()
        if self.barge_in_mode == "off":
            with self.raw_audio_queue.mutex:
                self.raw_audio_queue.queue.clear()

    def _on_tts_finished(self):
        self.tts_finish_time = time.time()
        self.is_tts_speaking = False
        if self.barge_in_mode == "off":
            with self.raw_audio_queue.mutex:
                self.raw_audio_queue.queue.clear()

    def audio_callback(self, indata, frames, time_info, status):
        """Non-blocking low-latency sounddevice capture callback."""
        if not self.is_listening:
            return
        if self.barge_in_mode == "off":
            if self.is_tts_speaking or (time.time() - self.tts_finish_time) < 0.35:
                return

        try:
            self.raw_audio_queue.put_nowait(indata.copy())
        except queue.Full:
            # Drop oldest frame if queue is congested
            try:
                self.raw_audio_queue.get_nowait()
                self.raw_audio_queue.put_nowait(indata.copy())
            except Exception:
                pass

    @staticmethod
    def calculate_adaptive_silence_threshold(speech_frames_count: int, trailing_rms: float, base_threshold: int) -> int:
        """
        Dynamically adjusts the required trailing silence frames before cutting an utterance:
        - Short snappy commands (< 18 frames) cut faster (base - 2) for minimum command latency.
        - Longer complex dictation (> 45 frames) receives extra breathing room (+4 frames).
        - Residual trailing energy above noise floor (+2 frames) avoids clipping terminal consonants.
        """
        thresh = base_threshold
        if speech_frames_count < 18:
            thresh = max(10, base_threshold - 2)
        elif speech_frames_count > 45:
            thresh = base_threshold + 4

        if trailing_rms > 0.0015:
            thresh += 2
        return thresh

    def _resolve_audio_device(self):
        dev_setting = self.config.get("audio_input_device", "auto")
        devs = sd.query_devices()
        input_indices = [i for i, d in enumerate(devs) if d.get('max_input_channels', 0) > 0]

        if not input_indices:
            raise RuntimeError("No microphone input devices found on system!")

        candidates = []
        for i in input_indices:
            d = devs[i]
            name = d['name']
            prio = 1

            if dev_setting in ["auto", "default", None]:
                if any(k in name.lower() for k in ["noise", "airwave", "headset", "bluetooth", "buds"]):
                    prio = 10 if d['hostapi'] in [2, 3] else 4
                elif i == sd.default.device[0]:
                    prio = 8
                elif "realtek" in name.lower():
                    prio = 6
                else:
                    prio = 3
            elif isinstance(dev_setting, str) and dev_setting.lower() in name.lower():
                prio = 12 if d['hostapi'] in [2, 3] else 8
            elif isinstance(dev_setting, int) and i == dev_setting:
                prio = 20

            candidates.append((i, d, prio))

        candidates.sort(key=lambda x: x[2], reverse=True)

        for idx, d, prio in candidates:
            rate = int(d['default_samplerate'])
            ch = min(1, d['max_input_channels'])
            try:
                chunks = []
                def test_cb(indata, frames, time_info, status):
                    chunks.append(indata.copy())
                with sd.InputStream(samplerate=rate, channels=ch, device=idx, dtype='float32', blocksize=512, callback=test_cb):
                    time.sleep(0.12)
                if chunks:
                    log.info(f"Selected active microphone [{idx}]: {d['name']} (HostAPI: {d['hostapi']}, Rate: {rate}Hz)")
                    return idx, d, rate
            except Exception:
                continue

        default_idx = sd.default.device[0] if sd.default.device[0] >= 0 else input_indices[0]
        return default_idx, devs[default_idx], int(devs[default_idx]['default_samplerate'])

    # =========================================================================
    # WORKER 1: ASYNCHRONOUS SPEECH RECOGNITION (ASR) THREAD
    # =========================================================================
    def _asr_worker_loop(self):
        log.info("Pipeline: ASR Worker Thread started (Parallel).")
        while self.is_running:
            try:
                utterance_item = self.utterance_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if utterance_item is None:
                break

            audio_data, agc_target, max_gain, during_tts = (tuple(utterance_item) + (False,))[:4]

            try:
                text = self._transcribe_audio(audio_data, agc_target, max_gain)
                if text and during_tts:
                    tts = self.router.tts
                    spoken = tts.recent_spoken() if callable(getattr(tts, "recent_spoken", None)) else []
                    if is_probable_echo(text, spoken):
                        log.info(f"Pipeline: dropped echo of MXB's own voice: '{text}'")
                        self.vad_status_changed.emit("Idle")
                        continue
                    log.info("Pipeline: barge-in — user spoke over MXB, interrupting speech.")
                    tts.interrupt()
                if text:
                    log.info(f"Pipeline [Parallel ASR] -> '{text}'")
                    self.transcription_ready.emit(text)
                    # Stop words, confirmations and the wake word are handled instantly
                    # in the bus; real commands are queued without blocking this thread.
                    outcome = self.bus.submit(text, source="voice", lang=getattr(self, "last_language", None))
                    if outcome == "ignored":
                        self.vad_status_changed.emit("Idle")
                else:
                    log.info("Pipeline: No recognizable speech in utterance.")
                    self.vad_status_changed.emit("Idle")
            except Exception as e:
                log.error(f"Pipeline: ASR Worker Exception: {e}")
            finally:
                self.utterance_queue.task_done()

    def _audio_to_wav_bytes(self, audio_data: np.ndarray, sample_rate=16000) -> bytes:
        int16_data = (audio_data * 32767).clip(-32768, 32767).astype(np.int16)
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(int16_data.tobytes())
        wav_io.seek(0)
        return wav_io.read()

    def _transcribe_nvidia_build(self, audio_data: np.ndarray) -> str | None:
        api_key = CredentialsManager.get_nvidia_api_key()
        if not api_key:
            return None

        cfg_sr = self.config.get("speech_recognition", {})
        model_name = cfg_sr.get("model", "nvidia/parakeet-tdt-0.6b")
        api_url = cfg_sr.get("api_url", "https://integrate.api.nvidia.com/v1/audio/transcriptions")

        wav_bytes = self._audio_to_wav_bytes(audio_data, 16000)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json"
        }
        files = {"file": ("speech.wav", wav_bytes, "audio/wav")}
        data = {
            "model": model_name,
            "language": "en-US",
            "response_format": "json"
        }

        t0 = time.time()
        resp = requests.post(api_url, headers=headers, files=files, data=data, timeout=8)
        if resp.status_code == 200:
            text = resp.json().get("text", "").strip()
            log.info(f"NVIDIA Build ASR ({time.time()-t0:.2f}s): '{text}'")
            return text
        return None

    def _transcribe_sarvam(self, audio_data: np.ndarray, mode: str) -> str | None:
        """Sarvam Saaras: Indian-language speech -> English text + detected language (needs SARVAM_API_KEY)."""
        key = CredentialsManager.get_secret("SARVAM_API_KEY")
        if not key:
            return None
        try:
            from engine.indic import SarvamSTT
            cfg = self.config.get("speech_recognition", {})
            stt = SarvamSTT(key, model=cfg.get("sarvam_model", "saaras:v3"), mode="translate")
            t0 = time.time()
            text, lang = stt.transcribe(self._audio_to_wav_bytes(audio_data, 16000), mode)
            self.last_language = lang
            log.info(f"Sarvam ASR ({time.time() - t0:.2f}s, {lang or 'en'}): '{text}'")
            return text or None
        except Exception as e:
            log.warning(f"Sarvam ASR failed, using local recognition: {e}")
            return None

    def _transcribe_audio(self, audio_data: np.ndarray, agc_target: float, max_gain: float) -> str | None:
        # Zero-center waveform by removing DC bias
        audio_data = audio_data - float(np.mean(audio_data))

        # Dynamic Adaptive Gain Control (AGC) with soft compression
        max_amp = float(np.max(np.abs(audio_data)))
        if max_amp > 0.00005:
            gain = min(agc_target / max_amp, max_gain)
            audio_data = audio_data * gain
            if np.any(np.abs(audio_data) > 0.85):
                audio_data = np.tanh(audio_data * 1.05)

        text = None
        self.last_language = None
        from engine.indic import LANGUAGES, preferred_language
        mode = preferred_language(self.config)   # "en", "auto" or an Indian language code

        # 0. Indian languages: Sarvam turns speech straight into English and says which language it was.
        if mode != "en":
            text = self._transcribe_sarvam(audio_data, mode)

        # 1. Cloud NVIDIA Build ASR (fastest, English only)
        if text is None and mode == "en" and (self.config.get("speech_recognition", {}).get("provider") == "nvidia"
                                              or CredentialsManager.has_nvidia_api_key()):
            try:
                text = self._transcribe_nvidia_build(audio_data)
            except Exception as e:
                log.warning(f"NVIDIA Build ASR fallback: {e}")
                text = None

        # 2. Local Faster-Whisper Fallback
        if text is None and self.whisper_model:
            try:
                audio_len_s = len(audio_data) / 16000.0
                adaptive_speech_pad = min(350, max(180, int(audio_len_s * 55)))
                lang_kwargs = {}
                if mode != "en" and not getattr(self, "_whisper_english_only", False):
                    lang_kwargs["language"] = None if mode == "auto" else mode
                segments, info = self.whisper_model.transcribe(
                    audio_data,
                    beam_size=5,
                    **lang_kwargs,
                    vad_filter=True,
                    vad_parameters=dict(
                        threshold=0.35,
                        min_speech_duration_ms=100,
                        min_silence_duration_ms=300,
                        speech_pad_ms=adaptive_speech_pad
                    ),
                    condition_on_previous_text=False,
                    # No initial prompt: Whisper repeated the old one ("open app, close window...") on noise.
                    initial_prompt=None,
                    no_speech_threshold=0.60,
                    # One decode, no fallback ladder: noise was re-decoded at up to 6 temperatures.
                    temperature=0.0,
                    **whisper_options(self.whisper_model, self.config.get("engine", {}).get("whisper_hotwords", ""),
                                      max_new_tokens=max_tokens_for(audio_len_s)),
                )
                detected = getattr(info, "language", None)
                if detected in LANGUAGES and detected != "en":
                    self.last_language = detected
                filtered_segments = []
                for s in segments:
                    if getattr(s, "no_speech_prob", 0.0) > 0.65:
                        continue
                    if getattr(s, "avg_logprob", 0.0) < -1.4:
                        continue
                    clean_seg = s.text.strip()
                    if clean_seg:
                        filtered_segments.append(clean_seg)
                text = " ".join(filtered_segments).strip()
            except Exception as e:
                log.error(f"Local Faster-Whisper error: {e}")

        # Post-transcription noise & hallucination filter: "open notepad, open notepad" -> "open notepad";
        # loops Whisper invents from noise ("go, go, go", "open app" x6) are dropped.
        if text:
            cleaned = clean_transcript(text)
            if cleaned is None:
                log.info(f"Pipeline: Filtered hallucinated repetition: '{text}'")
            elif cleaned != text:
                log.info(f"Pipeline: collapsed repeated phrase '{text}' -> '{cleaned}'")
            return cleaned
        return text

    # =========================================================================
    # MAIN VAD & CONTINUOUS AUDIO STREAMING LOOP
    # =========================================================================
    def run(self):
        self.vad_status_changed.emit("Loading Models...")
        log.info("Loading Local Faster-Whisper Fallback Engine...")

        try:
            model_size = self.config.get("engine", {}).get("whisper_model", "base.en")
            from engine.indic import preferred_language
            if preferred_language(self.config) != "en" and str(model_size).endswith(".en"):
                # English-only models can't hear Kannada, Hindi...: load the multilingual one instead.
                model_size = self.config.get("engine", {}).get("whisper_model_multilingual", "small")
            device = "cpu"
            compute_type = "int8"
            self.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
            self._whisper_english_only = str(model_size).endswith(".en")
        except Exception as e:
            error_msg = f"Model Error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)
            return

        vad_model = self._get_vad_model()
        # Keeps the VAD's memory between 32 ms frames (calling the model per frame reset it every time).
        self._vad = StreamingVAD(vad_model) if vad_model is not None else None
        if self._vad is not None:
            log.info(f"Pipeline: streaming voice detection ({self._vad.kind}).")

        # Start Parallel Worker Threads
        self._asr_thread = threading.Thread(target=self._asr_worker_loop, name="MXB-Parallel-ASR", daemon=True)
        self._asr_thread.start()

        self.vad_status_changed.emit("Idle")

        try:
            device_idx, device_info, dev_native_rate = self._resolve_audio_device()
        except Exception as e:
            error_msg = f"Microphone lookup error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)
            return

        self.barge_in_mode = resolve_mode(self.barge_in_setting, device_info.get("name", ""))
        log.info(f"Pipeline: barge-in mode = {self.barge_in_mode} (mic: {device_info.get('name', '?')})")
        if self.wake_engine is not None and not self.wake_engine.load():
            self.wake_engine = None

        use_software_resample = False
        stream_rate = 16000
        stream_channels = 1
        stream_blocksize = 512

        try:
            test_stream = sd.InputStream(
                samplerate=stream_rate,
                channels=stream_channels,
                dtype='float32',
                blocksize=stream_blocksize,
                device=device_idx
            )
            test_stream.close()
        except Exception:
            use_software_resample = True
            stream_rate = dev_native_rate
            stream_channels = 1
            stream_blocksize = int(stream_rate * 0.032)

        buffer = []
        is_speaking = False
        started_during_tts = False
        silence_frames = 0
        speech_frames_count = 0

        max_utterance_s = float(self.config.get("engine", {}).get("max_utterance_s", 12))
        max_utterance_frames = max(32, int(max_utterance_s / 0.032))
        sensitivity = self.config.get("engine", {}).get("microphone_sensitivity", "high").lower()
        if sensitivity == "high":
            vad_speech_prob_threshold = 0.35
            silence_threshold = 16
            min_speech_frames = 3
            agc_target_level = 0.85
            agc_max_gain = 60.0
        elif sensitivity == "medium":
            vad_speech_prob_threshold = 0.50
            silence_threshold = 18
            min_speech_frames = 4
            agc_target_level = 0.80
            agc_max_gain = 40.0
        else:
            vad_speech_prob_threshold = 0.65
            silence_threshold = 20
            min_speech_frames = 5
            agc_target_level = 0.75
            agc_max_gain = 25.0

        try:
            with sd.InputStream(
                samplerate=stream_rate,
                channels=stream_channels,
                dtype='float32',
                blocksize=stream_blocksize,
                device=device_idx,
                callback=self.audio_callback
            ):
                log.info(f"Microphone Streaming Active [{stream_rate}Hz, Ch {stream_channels}]. Continuous Parallel VAD Active.")

                while self.is_running:
                    if not self.raw_audio_queue.empty():
                        raw_chunk = self.raw_audio_queue.get()

                        if raw_chunk.ndim > 1 and raw_chunk.shape[1] > 1:
                            chunk = raw_chunk.mean(axis=1)
                        else:
                            chunk = raw_chunk.flatten()

                        if use_software_resample and stream_rate != 16000:
                            chunk = np.interp(
                                np.linspace(0, len(chunk), 512, endpoint=False),
                                np.arange(len(chunk)),
                                chunk
                            ).astype(np.float32)
                        elif len(chunk) != 512:
                            chunk = np.resize(chunk, 512).astype(np.float32)

                        raw_rms = float(np.sqrt(np.mean(chunk**2)))
                        speaking_now = self.is_tts_speaking or (time.time() - self.tts_finish_time) < 0.35
                        # Amplify quiet microphones before anything listens. MXB's own voice doesn't
                        # train the gain (adapt=False), or it would turn the gain down for the user.
                        chunk = self.agc.process(chunk, adapt=not speaking_now)
                        rms_volume = float(np.sqrt(np.mean(chunk**2)))
                        noise_level = self.agc.noise_after_gain
                        self.mic_level_signal.emit(min(rms_volume / (self.agc.target * 1.4), 1.0))
                        self._log_gain()

                        # Silero VAD (<0.2ms)
                        speech_prob = 0.0
                        if self._vad is not None:
                            try:
                                speech_prob = self._vad(chunk)
                            except Exception:
                                speech_prob = energy_speech_prob(rms_volume, noise_level)
                        else:
                            speech_prob = energy_speech_prob(rms_volume, noise_level)

                        # Offline wake word: runs on raw audio, before any transcription.
                        if self.wake_engine is not None and self.wake_engine.process(chunk):
                            self.bus.wake.engage()
                            self.vad_status_changed.emit("Active (Listening...)")
                            self.action_feedback.emit("Wake word heard — listening.")

                        if speaking_now and self.barge_in_mode != "off":
                            # Stricter detection while MXB talks, so its own voice doesn't count as speech.
                            # Raw level: the detector's thresholds were tuned before the input gain existed.
                            barge = self.barge_detector.update(speech_prob, raw_rms)
                            if barge and self.barge_in_mode == "headset" and self.is_tts_speaking:
                                log.info("Pipeline: barge-in (headset) — interrupting speech immediately.")
                                self.router.tts.interrupt()
                            has_speech = barge or (is_speaking and speech_prob >= 0.6)
                        else:
                            # Relative to this room's noise floor, not a fixed level that a fan can beat.
                            has_speech = is_speech(speech_prob, rms_volume, noise_level, vad_speech_prob_threshold)

                        if has_speech:
                            if not is_speaking:
                                is_speaking = True
                                started_during_tts = speaking_now
                                speech_frames_count = 0
                                self.vad_status_changed.emit("Active (Listening...)")
                                log.info(f"Speech Detected (Prob: {speech_prob:.3f}, RMS: {rms_volume:.4f}, "
                                         f"raw {raw_rms:.4f}, gain {self.agc.gain_db:+.1f} dB)")
                                buffer.extend(list(self.preroll_buffer))

                            buffer.append(chunk)
                            speech_frames_count += 1
                            silence_frames = 0
                            if len(buffer) >= max_utterance_frames:
                                # A TV or people talking can keep "speech" going for minutes: transcribe
                                # in pieces instead of waiting for a pause that never comes.
                                log.info(f"Pipeline: {len(buffer) * 0.032:.0f} s without a pause; transcribing this part now.")
                                self._dispatch_utterance(buffer, started_during_tts, agc_target_level, agc_max_gain)
                                buffer = []
                                speech_frames_count = 0
                                started_during_tts = speaking_now
                        else:
                            self.preroll_buffer.append(chunk)

                            if is_speaking:
                                silence_frames += 1
                                buffer.append(chunk)

                                adaptive_silence_target = self.calculate_adaptive_silence_threshold(
                                    speech_frames_count=speech_frames_count,
                                    trailing_rms=raw_rms,
                                    base_threshold=silence_threshold
                                )

                                if silence_frames > adaptive_silence_target:
                                    is_speaking = False

                                    if speech_frames_count < min_speech_frames:
                                        buffer = []
                                        self.vad_status_changed.emit("Idle")
                                        continue

                                    self._dispatch_utterance(buffer, started_during_tts, agc_target_level, agc_max_gain)
                                    buffer = []
                                    self.preroll_buffer.clear()
                    else:
                        time.sleep(0.008)
        except Exception as e:
            error_msg = f"Audio stream error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)

    def _dispatch_utterance(self, buffer, started_during_tts: bool, agc_target: float, max_gain: float):
        """Hands an utterance to the ASR worker without ever blocking the microphone loop."""
        # With the offline wake engine, nothing is transcribed until the wake word is heard
        # (except while MXB is busy/speaking, so "stop" still works).
        if (self.wake_engine is not None and not self.bus.wake.engaged
                and not self.bus.busy and not self.is_tts_speaking):
            self.vad_status_changed.emit("Idle")
            return
        item = (np.concatenate(buffer).flatten(), agc_target, max_gain,
                started_during_tts and self.barge_in_mode == "speaker")
        try:
            self.utterance_queue.put_nowait(item)
        except queue.Full:
            # Recognition is behind (long background talk): drop the OLDEST waiting utterance, so the
            # newest one, most likely the user's command, still gets transcribed.
            try:
                self.utterance_queue.get_nowait()
                self.utterance_queue.task_done()
                log.warning("Pipeline: speech recognition is behind; dropped the oldest waiting utterance.")
            except queue.Empty:
                pass
            try:
                self.utterance_queue.put_nowait(item)
            except queue.Full:
                return
        self.vad_status_changed.emit("Transcribing...")
        log.info(f"Utterance dispatched to Parallel ASR queue ({len(buffer)} frames). Mic stays listening!")

    def _log_gain(self, every_s: float = 30.0, min_change_db: float = 3.0):
        """One log line when the microphone gain settles somewhere new (for diagnosing quiet mics)."""
        last_t, last_db = self._gain_log
        now = time.time()
        db = self.agc.gain_db
        if now - last_t >= every_s and (last_db is None or abs(db - last_db) >= min_change_db):
            self._gain_log = (now, db)
            log.info(f"Mic input gain {db:+.1f} dB (noise floor {self.agc.noise:.4f}, speech level {self.agc.speech:.4f}, "
                     f"mode {self.agc.mode})")

    def pause_listening(self):
        self.is_listening = False
        self.vad_status_changed.emit("Microphone Muted")
        log.info("Voice Pipeline Muted.")
        with self.raw_audio_queue.mutex:
            self.raw_audio_queue.queue.clear()

    def resume_listening(self):
        self.is_listening = True
        if self._vad is not None:
            self._vad.reset()               # the voice detector's memory is from before the mute
        self.vad_status_changed.emit("Idle")
        # Unmuting is an explicit "I'm talking to you" signal: no wake word needed next.
        self.bus.wake.engage()
        log.info("Voice Pipeline Listening Resumed.")

    def stop(self):
        self.is_running = False
        self.utterance_queue.put(None)
        self.bus.shutdown()
        if hasattr(self, 'router') and hasattr(self.router, 'tts'):
            self.router.tts.stop()
        self.wait(1500)
