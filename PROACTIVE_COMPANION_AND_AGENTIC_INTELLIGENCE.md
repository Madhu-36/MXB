# MXB V4.4 - Proactive Companion & Agentic Intelligence Architecture

## 1. Executive Overview & Autonomous Companion Vision
MXB V4.4 marks the transition of MXB from a purely reactive desktop automation tool into an autonomous, proactive companion. In traditional voice assistants, execution begins only after an explicit wake-word or push-to-talk trigger. MXB V4.4 introduces a dual-operating model:
1. **Reactive Automation Pipeline**: Instant, sub-5ms deterministic command routing and multi-step ReAct execution loops.
2. **Proactive Companion Daemon**: Autonomous background arbitration that anticipates user needs—delivering morning briefings, tracking meeting schedules, issuing 20-20-20 ergonomic breaks, and warning against suspicious financial payment requests.

```
+-----------------------------------------------------------------------------------+
|                        MXB V4.4 Proactive Companion System Map                    |
|                                                                                   |
|  [ Microphones ] ----> ( Silero VAD + Smart Turn Detection ) ----> [ CommandBus ] |
|                                                                          ^        |
|  [ Local Calendar & IMAP ] ---> ( Proactive Engine: Offline Cache ) -----+        |
|                                                                          |        |
|  [ Screen & Vision ] ---------> ( Scam Shield / Digital Arrest Check ) --+        |
|                                                                          v        |
|  [ User Feedback ] <---------- ( Floating Layered HUD / Native TTS ) <---+        |
+-----------------------------------------------------------------------------------+
```

### Core Design Principles
- **User Agency First**: MXB speaks first only when configured, authenticated, and explicitly verified.
- **Total Local Privacy**: Calendar parsing, voice identification, and heuristic fraud detection execute 100% on the local workstation.
- **Fail-Safe Offline Autonomy**: If network connectivity drops, MXB gracefully degrades to cached schedules and local models.


## 2. Smart Turn Semantic End-of-Turn Engine
Traditional voice assistants rely solely on acoustic silence timeouts (typically 700ms–1500ms) to detect when a user has finished speaking. This introduces unnatural pauses or prematurely cuts off users when thinking mid-sentence.

### Semantic State Machine
MXB V4.4 integrates a dual-mode turn detector:
1. **Acoustic Silence Thresholding**: High-sensitivity energy detection via Silero VAD.
2. **Semantic Turn Classifier**: A lightweight local ONNX transformer model that evaluates grammatical completeness:

$$\mathcal{P}(\text{turn\_complete} \mid \mathbf{x}_{1:T}) = \sigma(\mathbf{W} \cdot \text{Transformer}(\mathbf{x}_{1:T}) + b)$$

```python
class TurnDetector:
    def evaluate_turn(self, audio_frames: np.ndarray) -> TurnVerdict:
        features = turn_features(audio_frames)
        prob = self._session.run(None, {"input": features})[0][0]
        if prob > 0.85:
            return TurnVerdict.COMPLETE
        elif prob < 0.35:
            return TurnVerdict.HOLD
        return TurnVerdict.UNCERTAIN
```

This eliminates dead air while allowing users to pause naturally during complex dictation.


## 3. Acoustic Feature Extraction & Tensor Sanitization
The turn detection pipeline requires robust, low-latency extraction of log-mel spectrogram features from raw 16 kHz mono PCM streams.

### Sanitization & Flattening Pipeline
To prevent memory explosion or NaN poisoning from audio device anomalies:
- Input tensors are strictly flattened to 1D via `.reshape(-1)`.
- Non-finite samples ($+\infty$, $-\infty$, $\text{NaN}$) are sanitized using `np.nan_to_num(x, copy=False, posinf=1.0, neginf=-1.0)`.
- Short utterances are padded with reflection or zero-fill to match the required receptive field.

```python
def turn_features(audio: np.ndarray, sample_rate: int = 16000) -> np.ndarray:
    x = np.asarray(audio, dtype=np.float32).reshape(-1)
    if len(x) == 0:
        return np.zeros((1, 80, 128), dtype=np.float32)
    np.nan_to_num(x, copy=False, posinf=1.0, neginf=-1.0)
    # 80-channel Log-Mel extraction with 25ms window and 10ms hop size
    mel = compute_log_mel_spectrogram(x, sample_rate=sample_rate, n_mels=80)
    return mel[np.newaxis, ...]
```


## 4. Multi-Speaker Voice ID & Speaker Verification
To prevent accidental activation by background voices or television audio, MXB V4.4 implements biometric speaker verification.

### Speaker Embedding Generation
Using a compact ResNet-34 speaker recognition backbone (Sherpa-ONNX), MXB maps user utterances into a 512-dimensional unit hypersphere:

$$\mathbf{e} = \frac{f_{\theta}(\mathbf{a})}{\|f_{\theta}(\mathbf{a})\|_2}, \quad \|\mathbf{e}\|_2 = 1.0$$

### Cosine Verification Scoring
During active turns, the incoming utterance embedding $\mathbf{e}_{\text{test}}$ is scored against the enrolled owner profile $\mathbf{e}_{\text{owner}}$:

$$\text{Score}(\mathbf{e}_{\text{test}}, \mathbf{e}_{\text{owner}}) = \mathbf{e}_{\text{test}} \cdot \mathbf{e}_{\text{owner}} = \sum_{i=1}^{512} e_{\text{test}, i} \, e_{\text{owner}, i}$$

If $\text{Score} < \tau$ (default threshold: $0.62$), the command is silently discarded or greeted with a security prompt.


## 5. Thread-Safe Voiceprint Storage & Windows Handle Resilience
On Windows workstations, standard atomic file replacement (`os.replace`) can fail with `WinError 32` or `WinError 5` (Access Denied) if an open file handle remains held by another thread.

### Context-Managed Loading
MXB V4.4 enforces strict context management when accessing `.npz` vector archives:

```python
class VoiceID:
    def __init__(self, store_path: Path):
        self._lock = threading.RLock()
        self.store = store_path

    def _load(self):
        with self._lock:
            if not self.store.is_file():
                return
            try:
                with np.load(self.store) as data:
                    owner = data.get("owner")
                    if owner is not None and np.isfinite(owner).all():
                        self.owner = np.array(owner, dtype=np.float32)
            except Exception as e:
                log.warning(f"VoiceID: profile corrupted ({e}); resetting.")
                self.owner = None
```

Saves are routed through unique temporary files (`tmp.{uuid}.npz`) followed by atomic rename within an acquisition lock.


