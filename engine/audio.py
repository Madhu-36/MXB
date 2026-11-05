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
from engine.router import IntentRouter
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
    """

    vad_status_changed = Signal(str)
    transcription_ready = Signal(str)
    action_feedback = Signal(str)
    mic_level_signal = Signal(float)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.is_running = True
        self.is_listening = True
        self.is_tts_speaking = False
        self.tts_finish_time = 0.0

        self.router = IntentRouter()

        # Connect TTS signals for echo suppression
        self.router.tts.started_speaking.connect(self._on_tts_started)
        self.router.tts.finished_speaking.connect(self._on_tts_finished)

        self.sample_rate = 16000
        self.blocksize = 512

        # Thread-safe queues connecting the concurrent pipeline stages
        self.raw_audio_queue = queue.Queue(maxsize=150)
        self.utterance_queue = queue.Queue(maxsize=10)
        self.action_task_queue = queue.Queue(maxsize=15)

        # 800ms pre-roll audio ring buffer to preserve leading syllables
        self.preroll_buffer = collections.deque(maxlen=25)

        # Silero neural VAD model lazy loader
        self._vad_model = None
        self.whisper_model = None

        # Worker threads
        self._asr_thread = None
        self._action_thread = None

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
        with self.raw_audio_queue.mutex:
            self.raw_audio_queue.queue.clear()

    def _on_tts_finished(self):
        self.tts_finish_time = time.time()
        self.is_tts_speaking = False
        with self.raw_audio_queue.mutex:
            self.raw_audio_queue.queue.clear()

    def audio_callback(self, indata, frames, time_info, status):
        """Non-blocking low-latency sounddevice capture callback."""
        if not self.is_listening or self.is_tts_speaking:
            return
        if (time.time() - self.tts_finish_time) < 0.35:
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

            audio_data, agc_target, max_gain = utterance_item

            try:
                text = self._transcribe_audio(audio_data, agc_target, max_gain)
                if text:
                    log.info(f"Pipeline [Parallel ASR] -> '{text}'")
                    self.transcription_ready.emit(text)

                    # Check for immediate emergency voice interruption
                    clean_lower = text.lower().strip()
                    if clean_lower in ["stop", "cancel", "halt", "pause", "abort", "freeze"]:
                        log.warning("Pipeline: Immediate Voice Interruption detected in ASR thread!")
                        self.router.executor.abort_current_action()
                        self.action_feedback.emit("INTERRUPTED: Actions aborted.")
                        self.router.tts.speak("Stopped.")
                        # Drain any pending queued actions
                        with self.action_task_queue.mutex:
                            self.action_task_queue.queue.clear()
                        continue

                    # Put recognized command into Action Execution Queue
                    self.action_task_queue.put(text)
                else:
                    log.info("Pipeline: No recognizable speech in utterance.")
                    self.vad_status_changed.emit("Idle")
            except Exception as e:
                log.error(f"Pipeline: ASR Worker Exception: {e}")
            finally:
                self.utterance_queue.task_done()

    # =========================================================================
    # WORKER 2: ASYNCHRONOUS ACTION EXECUTION THREAD (PARALLEL TO AUDIO)
    # =========================================================================
    def _action_worker_loop(self):
        log.info("Pipeline: Action Execution Worker Thread started (Parallel).")
        while self.is_running:
            try:
                text_cmd = self.action_task_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            if text_cmd is None:
                break

            try:
                self.action_feedback.emit("Reasoning & Planning...")
                action_result = self.router.route(text_cmd, feedback_callback=self.action_feedback.emit)
                log.info(f"Pipeline [Parallel Action Result] -> {action_result}")
                self.action_feedback.emit(action_result)
                self.vad_status_changed.emit("Idle")
            except Exception as e:
                log.error(f"Pipeline: Action Worker Exception: {e}")
                self.action_feedback.emit(f"Execution Error: {e}")
            finally:
                self.action_task_queue.task_done()

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

    def _transcribe_audio(self, audio_data: np.ndarray, agc_target: float, max_gain: float) -> str | None:
        # Dynamic AGC
        max_amp = float(np.max(np.abs(audio_data)))
        if max_amp > 0.00005:
            gain = min(agc_target / max_amp, max_gain)
            audio_data = audio_data * gain
            if np.any(np.abs(audio_data) > 0.90):
                audio_data = np.tanh(audio_data * 1.1)

        text = None

        # 1. Cloud NVIDIA Build ASR (fastest)
        if self.config.get("speech_recognition", {}).get("provider") == "nvidia" or CredentialsManager.has_nvidia_api_key():
            try:
                text = self._transcribe_nvidia_build(audio_data)
            except Exception as e:
                log.warning(f"NVIDIA Build ASR fallback: {e}")
                text = None

        # 2. Local Faster-Whisper Fallback
        if text is None and self.whisper_model:
            try:
                segments, _ = self.whisper_model.transcribe(
                    audio_data,
                    beam_size=5,
                    vad_filter=True,
                    vad_parameters=dict(
                        threshold=0.35,
                        min_speech_duration_ms=100,
                        min_silence_duration_ms=300,
                        speech_pad_ms=200
                    ),
                    condition_on_previous_text=False,
                    initial_prompt="Desktop commands: open app, close window, check system, click, scroll down, type text.",
                    no_speech_threshold=0.60
                )
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

        # Post-transcription noise & hallucination filter
        if text:
            words = text.lower().replace(",", " ").replace("!", " ").replace(".", " ").split()
            if len(words) >= 4 and len(set(words)) <= 2:
                log.info(f"Pipeline: Filtered hallucinated repetition: '{text}'")
                return None
            if len(text) < 2:
                return None

        return text

    # =========================================================================
    # MAIN VAD & CONTINUOUS AUDIO STREAMING LOOP
    # =========================================================================
    def run(self):
        self.vad_status_changed.emit("Loading Models...")
        log.info("Loading Local Faster-Whisper Fallback Engine...")

        try:
            model_size = self.config.get("engine", {}).get("whisper_model", "base.en")
            device = "cpu"
            compute_type = "int8"
            self.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as e:
            error_msg = f"Model Error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)
            return

        vad_model = self._get_vad_model()

        # Start Parallel Worker Threads
        self._asr_thread = threading.Thread(target=self._asr_worker_loop, name="MXB-Parallel-ASR", daemon=True)
        self._action_thread = threading.Thread(target=self._action_worker_loop, name="MXB-Parallel-Action", daemon=True)
        self._asr_thread.start()
        self._action_thread.start()

        self.vad_status_changed.emit("Idle")

        try:
            device_idx, device_info, dev_native_rate = self._resolve_audio_device()
        except Exception as e:
            error_msg = f"Microphone lookup error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)
            return

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
        silence_frames = 0
        speech_frames_count = 0

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

                        rms_volume = float(np.sqrt(np.mean(chunk**2)))
                        self.mic_level_signal.emit(min(rms_volume * 150.0, 1.0))

                        # Silero VAD (<0.2ms)
                        speech_prob = 0.0
                        if vad_model is not None:
                            try:
                                prob_out = vad_model(chunk)
                                speech_prob = float(prob_out[0]) if len(prob_out) > 0 else 0.0
                            except Exception:
                                speech_prob = 1.0 if rms_volume > 0.0006 else 0.0
                        else:
                            speech_prob = 1.0 if rms_volume > 0.0006 else 0.0

                        has_speech = (speech_prob >= vad_speech_prob_threshold) or (rms_volume > 0.0025)

                        if has_speech:
                            if not is_speaking:
                                is_speaking = True
                                speech_frames_count = 0
                                self.vad_status_changed.emit("Active (Listening...)")
                                log.info(f"Speech Detected (Prob: {speech_prob:.3f}, RMS: {rms_volume:.6f})")
                                buffer.extend(list(self.preroll_buffer))

                            buffer.append(chunk)
                            speech_frames_count += 1
                            silence_frames = 0
                        else:
                            self.preroll_buffer.append(chunk)

                            if is_speaking:
                                silence_frames += 1
                                buffer.append(chunk)

                                if silence_frames > silence_threshold:
                                    is_speaking = False

                                    if speech_frames_count < min_speech_frames:
                                        buffer = []
                                        self.vad_status_changed.emit("Idle")
                                        continue

                                    # Hand off utterance to ASR Worker WITHOUT BLOCKING AUDIO STREAM
                                    audio_utterance = np.concatenate(buffer).flatten()
                                    self.utterance_queue.put((audio_utterance, agc_target_level, agc_max_gain))
                                    self.vad_status_changed.emit("Transcribing...")
                                    log.info(f"Utterance dispatched to Parallel ASR queue ({len(buffer)} frames). Mic stays listening!")

                                    buffer = []
                                    self.preroll_buffer.clear()
                    else:
                        time.sleep(0.008)
        except Exception as e:
            error_msg = f"Audio stream error: {e}"
            log.error(error_msg)
            self.vad_status_changed.emit(error_msg)

    def pause_listening(self):
        self.is_listening = False
        self.vad_status_changed.emit("Microphone Muted")
        log.info("Voice Pipeline Muted.")
        with self.raw_audio_queue.mutex:
            self.raw_audio_queue.queue.clear()

    def resume_listening(self):
        self.is_listening = True
        self.vad_status_changed.emit("Idle")
        log.info("Voice Pipeline Listening Resumed.")

    def stop(self):
        self.is_running = False
        self.utterance_queue.put(None)
        self.action_task_queue.put(None)
        if hasattr(self, 'router') and hasattr(self.router, 'tts'):
            self.router.tts.stop()
        self.wait(1500)
