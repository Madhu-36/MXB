import time
import queue
import traceback
import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel
from PySide6.QtCore import QThread, Signal
from engine.router import IntentRouter

class VoicePipeline(QThread):
    vad_status_changed = Signal(str)
    transcription_ready = Signal(str)
    action_feedback = Signal(str)

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.is_running = True
        self.is_listening = True
        self.router = IntentRouter()
        self.sample_rate = 16000
        self.audio_queue = queue.Queue()

    def audio_callback(self, indata, frames, time_info, status):
        if self.is_listening:
            self.audio_queue.put(indata.copy())

    def run(self):
        self.vad_status_changed.emit("Loading AI Models...")
        print("[Audio] Loading Faster-Whisper...")
        
        try:
            model_size = self.config.get("engine", {}).get("whisper_model", "base.en")
            try:
                self.whisper_model = WhisperModel(model_size, device="auto", compute_type="default")
            except Exception as cuda_err:
                print(f"[Audio] GPU acceleration unavailable. Falling back to CPU...")
                self.whisper_model = WhisperModel(model_size, device="cpu", compute_type="int8")
        except Exception as e:
            error_msg = f"Model Error: {e}"
            print(f"[Audio] {error_msg}")
            self.vad_status_changed.emit(error_msg)
            return

        self.vad_status_changed.emit("Idle")
        
        buffer = []
        is_speaking = False
        silence_frames = 0
        
        # 512 blocksize at 16000Hz = 32ms. 1.0s silence = ~31 blocks.
        silence_threshold = 31
        
        # Dynamic noise floor baseline (Auto-calibrates to your microphone)
        ambient_noise = 0.01 
        calibration_frames = 30 # Calibrate for roughly 1 second on boot

        # Get native hardware sample rate to prevent Windows from corrupting the stream
        device_info = sd.query_devices(sd.default.device[0])
        self.hardware_rate = int(device_info['default_samplerate'])
        self.chunk_duration = 0.032 # 32ms chunks
        self.blocksize = int(self.hardware_rate * self.chunk_duration)

        try:
            default_mic = device_info['name']
            print(f"[Audio] Connecting to Microphone: {default_mic} at {self.hardware_rate}Hz")
            
            with sd.InputStream(samplerate=self.hardware_rate, channels=None, dtype='float32', blocksize=self.blocksize, callback=self.audio_callback):
                print("[Audio] Microphone Active! Auto-calibrating to your room's background noise...")
                
                while self.is_running:
                    if not self.audio_queue.empty():
                        raw_chunk = self.audio_queue.get()
                        
                        # Manually convert Stereo down to Mono safely in numpy
                        if raw_chunk.ndim > 1 and raw_chunk.shape[1] > 1:
                            chunk = raw_chunk.mean(axis=1)
                        else:
                            chunk = raw_chunk.flatten()
                        
                        rms_volume = float(np.sqrt(np.mean(chunk**2)))
                        
                        # Print the volume constantly to the terminal so the user can verify their mic works
                        if getattr(self, '_debug_count', 0) % 30 == 0:
                            print(f"[Audio Debug] Mic Volume: {rms_volume:.5f} (Speak now to test!)")
                        self._debug_count = getattr(self, '_debug_count', 0) + 1
                        
                        if calibration_frames > 0:
                            ambient_noise = (ambient_noise * 0.9) + (rms_volume * 0.1)
                            calibration_frames -= 1
                            if calibration_frames == 0:
                                print(f"[Audio] Calibration complete. Ambient noise baseline: {ambient_noise:.5f}")
                            continue

                        # Trigger speech if volume spikes to 2.5x the ambient background noise
                        speech_threshold = max(ambient_noise * 2.5, 0.005)
                        
                        if rms_volume > speech_threshold:
                            if not is_speaking:
                                is_speaking = True
                                self.vad_status_changed.emit("Active (Listening...)")
                                print("[Audio] SPEECH DETECTED! Recording...")
                            buffer.append(chunk)
                            silence_frames = 0
                        else:
                            if is_speaking:
                                silence_frames += 1
                                buffer.append(chunk)
                                
                                if silence_frames > silence_threshold:
                                    is_speaking = False
                                    self.vad_status_changed.emit("Processing Voice...")
                                    print("[Audio] Silence detected. Handing off to Whisper...")
                                    self._process_audio_buffer(buffer)
                                    buffer = []
                                    self.vad_status_changed.emit("Idle")
                                    
                                    # Recalibrate slightly after speaking to handle room changes
                                    calibration_frames = 10
                    else:
                        time.sleep(0.01)
        except Exception as e:
            error_msg = f"Audio stream error: {e}"
            print(f"[Audio] {error_msg}")
            self.vad_status_changed.emit(error_msg)

    def _process_audio_buffer(self, buffer):
        # Flatten the accumulated audio chunks
        audio_data = np.concatenate(buffer).flatten()
        
        # Whisper strictly requires exactly 16000Hz. If we captured at 44100Hz or 48000Hz, we must resample it!
        if self.hardware_rate != 16000:
            try:
                import torch
                import torchaudio.functional as F
                tensor_audio = torch.from_numpy(audio_data).float()
                resampled_audio = F.resample(tensor_audio, orig_freq=self.hardware_rate, new_freq=16000)
                audio_data = resampled_audio.numpy()
            except Exception as e:
                print(f"[Audio] Resampling failed: {e}")
                return
        
        # NORMALIZE AUDIO: If the microphone is extremely quiet (like many Realtek mics), 
        # Whisper will silently ignore the audio. This amplifies the volume to maximum safely!
        max_amp = np.max(np.abs(audio_data))
        if max_amp > 0:
            audio_data = audio_data / max_amp
            
        # DEBUG: Save exactly what the AI is hearing to a file so we can prove if it's distorted!
        try:
            import scipy.io.wavfile as wav
            wav.write("debug_recording.wav", 16000, audio_data)
        except Exception:
            pass

        try:
            print("[Whisper] Transcribing...")
            segments, info = self.whisper_model.transcribe(
                audio_data, 
                beam_size=5, 
                vad_filter=False,
                condition_on_previous_text=False, # Stops Whisper from looping hallucinations
                no_speech_threshold=0.6 # Drops audio that is just background noise
            )
            text = " ".join([segment.text for segment in segments]).strip()
            
            if text:
                print(f"[Whisper] You said: '{text}'")
                self.transcription_ready.emit(text)
                self.action_feedback.emit("Routing intent...")
                
                # Hand off to Router (This blocks while LLM thinks and TTS speaks)
                action_result = self.router.route(text)
                print(f"[Router Output] {action_result}")
                self.action_feedback.emit(action_result)
                
                # CRITICAL: While the LLM was thinking and TTS was speaking, the microphone 
                # was still recording. Clear the queue now so MXB doesn't hear its own voice!
                with self.audio_queue.mutex:
                    self.audio_queue.queue.clear()
                    
            else:
                print("[Whisper] No recognizable text.")
        except Exception as e:
            error_msg = f"Transcription error: {e}"
            print(f"[Whisper] {error_msg}")
            self.action_feedback.emit(error_msg)

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
        self.wait()
