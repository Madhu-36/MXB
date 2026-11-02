import io
import time
import wave
import queue
import requests
import collections
import traceback
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from PySide6.QtCore import QThread, Signal
from engine.router import IntentRouter
from utils.credentials import CredentialsManager

class VoicePipeline(QThread):
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
        
        # Connect TTS signals to prevent acoustic self-listening loop
        self.router.tts.started_speaking.connect(self._on_tts_started)
        self.router.tts.finished_speaking.connect(self._on_tts_finished)
        
        self.sample_rate = 16000
        self.blocksize = 512 # 512 samples at 16000Hz = 32ms chunks
        self.audio_queue = queue.Queue()
        
        # 15 chunks @ 32ms = 480ms pre-roll audio ring buffer to preserve leading syllables
        self.preroll_buffer = collections.deque(maxlen=15)

    def _on_tts_started(self):
        self.is_tts_speaking = True
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def _on_tts_finished(self):
        self.tts_finish_time = time.time()
        self.is_tts_speaking = False
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def audio_callback(self, indata, frames, time_info, status):
        # Ignore mic frames while muted, speaking TTS, or within 350ms of TTS finishing (room echo suppression)
        if not self.is_listening or self.is_tts_speaking:
            return
        if (time.time() - self.tts_finish_time) < 0.35:
            return
            
        self.audio_queue.put(indata.copy())

    def _resolve_audio_device(self):
        """
        Smart microphone resolver.
        Tests available devices across APIs (WASAPI, MME, DirectSound, WDM-KS)
        to select an active, working recording device with valid audio throughput.
        """
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

            if dev_setting == "auto" or dev_setting == "default" or dev_setting is None:
                # If a Bluetooth headset mic is present, prioritize it
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
                    time.sleep(0.2)
                if chunks:
                    print(f"[Audio] Selected active microphone [{idx}]: {d['name']} (HostAPI: {d['hostapi']}, Rate: {rate}Hz)")
                    return idx, d, rate
            except Exception:
                continue

        default_idx = sd.default.device[0] if sd.default.device[0] >= 0 else input_indices[0]
        return default_idx, devs[default_idx], int(devs[default_idx]['default_samplerate'])

    def run(self):
        self.vad_status_changed.emit("Loading AI Models...")
        print("[Audio] Loading Local Faster-Whisper Fallback Engine...")
        
        try:
            model_size = self.config.get("engine", {}).get("whisper_model", "base.en")
            device = "cpu"
            compute_type = "int8"
            try:
                import torch
                if torch.cuda.is_available():
                    device = "cuda"
                    compute_type = "float16"
            except Exception:
                pass
            print(f"[Audio] Loading Faster-Whisper ({model_size}) on {device} ({compute_type})...")
            self.whisper_model = WhisperModel(model_size, device=device, compute_type=compute_type)
        except Exception as e:
            error_msg = f"Model Error: {e}"
            print(f"[Audio] {error_msg}")
            self.vad_status_changed.emit(error_msg)
            return

        has_nv = CredentialsManager.has_nvidia_api_key()
        if has_nv:
            print("[Audio] NVIDIA Build Cloud ASR: ENABLED (Ultra-fast cloud recognition)")
        else:
            print("[Audio] NVIDIA Build Cloud ASR: Not configured. Using local Faster-Whisper engine.")

        self.vad_status_changed.emit("Idle")
        
        try:
            device_idx, device_info, dev_native_rate = self._resolve_audio_device()
        except Exception as e:
            error_msg = f"Microphone lookup error: {e}"
            print(f"[Audio] {error_msg}")
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
            print(f"[Audio] Direct 16kHz capture unsupported by driver. Using native {dev_native_rate}Hz with software resample.")
            use_software_resample = True
            stream_rate = dev_native_rate
            stream_channels = min(1, max(1, device_info['max_input_channels']))
            stream_blocksize = int(stream_rate * 0.032)

        buffer = []
        is_speaking = False
        silence_frames = 0
        speech_frames_count = 0
        
        sensitivity = self.config.get("engine", {}).get("microphone_sensitivity", "high").lower()
        if sensitivity == "high":
            threshold_multiplier = 1.30
            min_threshold = 0.00035
            energy_offset = 0.00015
            self.max_agc_gain = 40.0
            silence_threshold = 22 # ~0.70s silence
        elif sensitivity == "medium":
            threshold_multiplier = 1.65
            min_threshold = 0.0009
            energy_offset = 0.0003
            self.max_agc_gain = 25.0
            silence_threshold = 24
        else:
            threshold_multiplier = 2.30
            min_threshold = 0.0022
            energy_offset = 0.0007
            self.max_agc_gain = 12.0
            silence_threshold = 26

        ambient_noise = 0.0003
        calibration_frames = 40

        try:
            with sd.InputStream(
                samplerate=stream_rate, 
                channels=stream_channels, 
                dtype='float32', 
                blocksize=stream_blocksize, 
                device=device_idx,
                callback=self.audio_callback
            ):
                print(f"[Audio] Microphone Streaming Active [{stream_rate}Hz, Ch {stream_channels}]. Sensitivity: {sensitivity.upper()}. Calibrating noise baseline...")
                
                debug_counter = 0
                while self.is_running:
                    if not self.audio_queue.empty():
                        raw_chunk = self.audio_queue.get()
                        
                        if raw_chunk.ndim > 1 and raw_chunk.shape[1] > 1:
                            chunk = raw_chunk.mean(axis=1)
                        else:
                            chunk = raw_chunk.flatten()
                            
                        if use_software_resample and stream_rate != 16000:
                            num_target = int(len(chunk) * 16000 / stream_rate)
                            chunk = np.interp(
                                np.linspace(0, len(chunk), num_target, endpoint=False),
                                np.arange(len(chunk)),
                                chunk
                            ).astype(np.float32)

                        rms_volume = float(np.sqrt(np.mean(chunk**2)))
                        self.mic_level_signal.emit(min(rms_volume * 100.0, 1.0))
                        
                        if calibration_frames > 0:
                            ambient_noise = (ambient_noise * 0.85) + (rms_volume * 0.15)
                            calibration_frames -= 1
                            if calibration_frames == 0:
                                print(f"[Audio] Baseline Calibrated: {ambient_noise:.6f} | Trigger Level: {max(ambient_noise * threshold_multiplier + energy_offset, min_threshold):.6f}")
                            continue

                        speech_threshold = max(ambient_noise * threshold_multiplier + energy_offset, min_threshold)

                        debug_counter += 1
                        if debug_counter % 45 == 0:
                            print(f"[Audio Debug] Mic RMS: {rms_volume:.6f} | Ambient: {ambient_noise:.6f} | Trigger: {speech_threshold:.6f}")
                        
                        if rms_volume > speech_threshold:
                            if not is_speaking:
                                is_speaking = True
                                speech_frames_count = 0
                                self.vad_status_changed.emit("Active (Listening...)")
                                print(f"[Audio] SPEECH DETECTED! (RMS: {rms_volume:.6f} > {speech_threshold:.6f})")
                                buffer.extend(list(self.preroll_buffer))
                                
                            buffer.append(chunk)
                            speech_frames_count += 1
                            silence_frames = 0
                        else:
                            self.preroll_buffer.append(chunk)
                            ambient_noise = (ambient_noise * 0.993) + (rms_volume * 0.007)
                            
                            if is_speaking:
                                silence_frames += 1
                                buffer.append(chunk)
                                
                                if silence_frames > silence_threshold:
                                    is_speaking = False
                                    
                                    if speech_frames_count < 4:
                                        print("[Audio] Ignored transient click/pop (<120ms).")
                                        buffer = []
                                        self.vad_status_changed.emit("Idle")
                                        continue
                                        
                                    self.vad_status_changed.emit("Processing Voice...")
                                    print(f"[Audio] Silence detected ({silence_frames} frames). Processing audio buffer ({len(buffer)} frames)...")
                                    self._process_audio_buffer(buffer)
                                    buffer = []
                                    self.vad_status_changed.emit("Idle")
                                    self.preroll_buffer.clear()
                    else:
                        time.sleep(0.01)
        except Exception as e:
            error_msg = f"Audio stream error: {e}"
            print(f"[Audio] {error_msg}")
            self.vad_status_changed.emit(error_msg)

    def _audio_to_wav_bytes(self, audio_data: np.ndarray, sample_rate=16000) -> bytes:
        """Encodes float32 numpy array into 16-bit PCM WAV in-memory bytes."""
        int16_data = (audio_data * 32767).clip(-32768, 32767).astype(np.int16)
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)
            wav_file.setsampwidth(2) # 16-bit
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(int16_data.tobytes())
        wav_io.seek(0)
        return wav_io.read()

    def _transcribe_nvidia_build(self, audio_data: np.ndarray) -> str | None:
        """Calls NVIDIA Build cloud ASR endpoint for high-speed voice recognition."""
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
        files = {
            "file": ("speech.wav", wav_bytes, "audio/wav")
        }
        data = {
            "model": model_name,
            "language": "en-US",
            "response_format": "json"
        }

        t0 = time.time()
        print(f"[NVIDIA Build ASR] Sending audio to {model_name}...")
        resp = requests.post(api_url, headers=headers, files=files, data=data, timeout=8)
        if resp.status_code == 200:
            res_json = resp.json()
            text = res_json.get("text", "").strip()
            elapsed = time.time() - t0
            print(f"[NVIDIA Build ASR] Transcribed in {elapsed:.2f}s: '{text}'")
            return text
        else:
            print(f"[NVIDIA Build ASR] Error {resp.status_code}: {resp.text}")
            return None

    def _process_audio_buffer(self, buffer):
        if not buffer:
            return

        audio_data = np.concatenate(buffer).flatten()
        
        # Dynamic Automatic Gain Control (AGC)
        max_amp = float(np.max(np.abs(audio_data)))
        if max_amp > 0.0001:
            gain = min(0.85 / max_amp, getattr(self, 'max_agc_gain', 35.0))
            audio_data = audio_data * gain
            if np.any(np.abs(audio_data) > 0.92):
                audio_data = np.tanh(audio_data)

        text = None

        # 1. Try NVIDIA Build Cloud ASR first if enabled
        if self.config.get("speech_recognition", {}).get("provider") == "nvidia" or CredentialsManager.has_nvidia_api_key():
            try:
                text = self._transcribe_nvidia_build(audio_data)
            except Exception as e:
                print(f"[NVIDIA Build ASR] Cloud request exception: {e}. Falling back to local Faster-Whisper...")
                text = None

        # 2. Fallback to Local Faster-Whisper if NVIDIA is not configured or failed
        if text is None:
            try:
                print("[Whisper] Transcribing with local Faster-Whisper fallback...")
                segments, info = self.whisper_model.transcribe(
                    audio_data, 
                    beam_size=5, 
                    vad_filter=True,
                    vad_parameters=dict(
                        threshold=0.30,
                        min_speech_duration_ms=100,
                        min_silence_duration_ms=350,
                        speech_pad_ms=300
                    ),
                    condition_on_previous_text=False,
                    initial_prompt="Open application, close window, check system, search the web, volume control, mute, minimize, maximize, type text, screenshot.",
                    no_speech_threshold=0.55
                )
                text = " ".join([segment.text for segment in segments]).strip()
            except Exception as e:
                error_msg = f"Local transcription error: {e}"
                print(f"[Whisper] {error_msg}")
                self.action_feedback.emit(error_msg)
                return

        if text:
            print(f"[Speech Engine] >>> Recognized: '{text}'")
            self.transcription_ready.emit(text)
            self.action_feedback.emit("Executing...")
            
            # Hand off to Router
            action_result = self.router.route(text)
            print(f"[Router Output] {action_result}")
            self.action_feedback.emit(action_result)
            
            with self.audio_queue.mutex:
                self.audio_queue.queue.clear()
        else:
            print("[Speech Engine] No recognizable speech detected in utterance.")

    def pause_listening(self):
        self.is_listening = False
        self.vad_status_changed.emit("Microphone Muted")
        print("[Audio] Muted.")
        with self.audio_queue.mutex:
            self.audio_queue.queue.clear()

    def resume_listening(self):
        self.is_listening = True
        self.vad_status_changed.emit("Idle")
        print("[Audio] Listening Resumed.")

    def stop(self):
        self.is_running = False
        self.wait(1500)
