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


## 6. Proactive Morning Briefing & Temporal Dispatch Engine
MXB V4.4 features a configurable proactive dispatcher that synthesizes calendar commitments, unread priority mail, and system metrics into a natural spoken briefing.

### Temporal Arbitration Rules
1. **Opt-in Activation**: Proactive alerts remain inactive until at least one data source (Calendar or Mailbox) is successfully connected.
2. **Quiet Hours Enforcement**: No audible speech is emitted between user-configured hours (default: 22:00–07:30) or when Windows Focus Assist / Do Not Disturb is active.
3. **Session Monotonicity**: The morning briefing is dispatched at most once per calendar day upon first user presence detection.

```python
class ProactiveEngine:
    def should_brief(self, now: datetime) -> bool:
        if not self.enabled or self.in_quiet_hours(now):
            return False
        if self._last_briefing and self._last_briefing.date() == now.date():
            return False
        return self.idle_seconds() < 120  # User is physically active at desktop
```


## 7. Calendar Synchronization & iCal / CalDAV Parsing
MXB connects to local and remote calendar services (Google Calendar, Microsoft Outlook, Apple iCloud, and Nextcloud) via standard iCalendar (RFC 5545) and CalDAV protocols.

### Recurring Event Expansion
Recurring events (`RRULE:FREQ=WEEKLY;BYDAY=MO,WE,FR`) are deterministically expanded into discrete event instances within a rolling 7-day query window:

```python
from recurring_ical_events import of as expand_ical

class CalendarSource:
    def get_upcoming_events(self, start: datetime, horizon: timedelta) -> list[CalendarEvent]:
        raw_ics = self._fetch_calendar()
        calendar = icalendar.Calendar.from_ical(raw_ics)
        expanded = expand_ical(calendar).between(start, start + horizon)
        return [
            CalendarEvent(
                title=str(ev.get("SUMMARY", "Busy")),
                start=ev.decoded("DTSTART"),
                end=ev.decoded("DTEND")
            )
            for ev in expanded
        ]
```


## 8. Offline Resilience & Graceful Calendar Cache Fallback
Workstations frequently switch between Wi-Fi networks, enter sleep mode, or operate in airplane mode. MXB ensures zero-exception operation during network outages.

### Two-Tier Cache Fallback Architecture
- **In-Memory Cache**: Active 15-minute memory cache avoiding redundant HTTP requests.
- **Durable Disk Cache**: Encrypted snapshot (`calendar_cache.ics`) stored in user AppData.

```python
def _fetch_calendar(self) -> str:
    try:
        resp = requests.get(self.feed_url, timeout=4.0)
        resp.raise_for_status()
        self._disk_cache.write_text(resp.text, encoding="utf-8")
        return resp.text
    except requests.RequestException as exc:
        if self._disk_cache.exists():
            log.warning(f"Calendar: network offline ({exc}); falling back to disk cache.")
            return self._disk_cache.read_text(encoding="utf-8")
        raise
```


## 9. Secure IMAP Mailbox Polling & Header Extraction
MXB provides hands-free email updates by monitoring IMAP servers (TLS port 993) with zero message body retention for user privacy.

### Privacy-Preserving Header Extraction
MXB inspects only standard message headers (`FROM`, `SUBJECT`, `DATE`, `FLAGS`), resolving RFC 2047 MIME encoded words into clean UTF-8 text:

```python
import email
from email.header import decode_header

def clean_subject(raw_header: str) -> str:
    decoded_fragments = decode_header(raw_header)
    parts = []
    for bytes_or_str, encoding in decoded_fragments:
        if isinstance(bytes_or_str, bytes):
            parts.append(bytes_or_str.decode(encoding or "utf-8", errors="replace"))
        else:
            parts.append(str(bytes_or_str))
    return "".join(parts)
```


## 10. Hardware Battery Sensing & Power State Management
To ensure laptop companions do not cause battery anxiety or drain hardware during mobile sessions, MXB monitors OS power state APIs via `psutil.sensors_battery()`.

### Low-Power Threshold Rules
- **Plugged AC Power**: Standard VAD sensitivity, full 4.7 GB local reasoning models permitted.
- **Battery > 20%**: Normal companion mode; proactive briefing active.
- **Battery <= 20% & Not Charging**: Proactive audible speech disabled; speech model quantization lowered; visual HUD alerts only.
- **Critical Battery <= 8%**: Audio pipeline enters low-power sleep; emergency save notification issued.


## 11. Focus Coach, Ergonomic Breaks & Screen Time Tracking
Prolonged computer use leads to digital eye strain and fatigue. MXB V4.4 introduces a built-in Focus Coach inspired by the 20-20-20 ergonomic rule.

### Ergonomic Timer State Machine
- Every **20 minutes** of continuous keyboard/mouse activity:
  - MXB gently plays a soft tone or speaks: *"Look at something 20 feet away for 20 seconds."*
  - Automatically suppresses alerts if a full-screen application or video meeting (Teams, Zoom, Meet) is active.

```python
class FocusCoach:
    def tick(self, active_seconds: float, is_meeting: bool):
        if is_meeting:
            self._consecutive_work_seconds = 0
            return
        if active_seconds > 1200:  # 20 minutes
            self.emit_break_reminder()
            self._consecutive_work_seconds = 0
```


## 12. Schema-Constrained Action Planning & ReAct Loops
When a user command cannot be resolved through the <5ms deterministic fast path (e.g. *"Look up flight statuses, write a summary in notepad, and mute system audio"*), MXB engages the ReAct Planning Engine.

### Constrained JSON-Schema Grammar
To eliminate LLM hallucination of non-existent actions, MXB dynamically generates strict JSON schemas constraining model output:

```json
{
  "type": "object",
  "properties": {
    "thought": { "type": "string" },
    "steps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "action": { "type": "string", "enum": ["launch_app", "type_text", "press_key", "media_control", "wait"] },
          "target": { "type": "string" }
        },
        "required": ["action", "target"]
      }
    }
  },
  "required": ["thought", "steps"]
}
```


## 13. TaskScope Goal-Grounding & Lateral Action Confinement
A major vulnerability in autonomous desktop agents is Indirect Prompt Injection—untrusted web text or emails instructing the agent to run dangerous secondary commands (e.g., launching PowerShell).

### Semantic Goal Alignment Check
Before executing any multi-step plan, MXB evaluates the semantic relevance of each step against the user's root goal:

$$\text{Relevance}(\text{step}_i, \text{goal}) = \frac{\mathbf{e}(\text{step}_i) \cdot \mathbf{e}(\text{goal})}{\|\mathbf{e}(\text{step}_i)\|_2 \|\mathbf{e}(\text{goal})\|_2} \ge \tau_{\text{align}}$$

If a step proposes high-risk lateral actions (such as `win+r`, shell execution, or registry modification) when the goal was informational, execution is immediately halted with an emergency security alert.


