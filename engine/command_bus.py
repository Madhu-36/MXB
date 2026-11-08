"""
MXB Command Bus — one entry point for voice AND text.

            voice (ASR thread) ─┐
                                ├─► submit() ─► control lane (instant, caller thread)
         text (chat window) ────┘               • "stop" / kill  → abort + clear + silence
                                                • "yes"/"no"     → answer pending confirmation
                                                • wake word gate (voice only)
                                                • "what are you doing" status
                                              ─► action lane (ordered FIFO worker)
                                                • everything that operates the PC
                                              ─► info lane (parallel worker)
                                                • questions asked WHILE a task runs,
                                                  so MXB keeps talking while it works

Questions that unexpectedly need the mouse/keyboard wait on the executor's
input lock, so they never type into the middle of a running plan.
"""
import queue
import re
import threading
import time
from PySide6.QtCore import QObject, Signal
from safety.policy import ConfirmationManager
from engine.wake_word import WakeWordGate
from engine.indic import IndicBridge, is_stop as indic_is_stop, set_reply_language
from utils.logger import log

STOP_PHRASES = {
    "stop", "cancel", "halt", "abort", "freeze", "stop it", "stop that", "stop executing",
    "cancel action", "cancel that", "shut up", "be quiet", "stop talking", "emergency stop", "pause",
}
STATUS_PHRASES = {
    "what are you doing", "status", "what's happening", "what is happening", "are you busy",
    "what are you working on", "progress", "task status",
}
OPEN_CHAT_PHRASES = {"open chat", "show chat", "open the chat", "show the chat", "open chat window", "chat window"}

INFO_STARTERS = (
    "what", "who", "whom", "why", "how", "when", "where", "which", "whose", "is ", "are ", "am i", "do you",
    "does ", "did ", "can you tell", "could you tell", "tell me", "explain", "define", "describe",
    "calculate", "translate", "summarize what", "give me an idea", "suggest",
)
ACTION_STARTERS = (
    "open", "close", "click", "double click", "right click", "type", "press", "hit", "search", "go to", "delete",
    "remove", "move", "copy", "paste", "rename", "turn", "switch", "connect", "disconnect", "set", "scroll",
    "play", "pause", "create", "make", "send", "write", "enter", "select", "drag", "launch", "start", "kill",
    "lock", "shut", "restart", "mute", "unmute", "increase", "decrease", "minimize", "maximize", "snap",
    "take", "save", "find", "read", "give access", "grant", "revoke", "agent", "autopilot", "remember",
)


def normalize(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"[\.,!\?;:]+$", "", t).strip()
    t = re.sub(r"^(?:hey\s+)?(?:mxb|m x b)[\s,]+", "", t)
    return re.sub(r"\s+", " ", t)


def is_stop_command(text: str) -> bool:
    t = normalize(text)
    return t in STOP_PHRASES or t in {f"{p} mxb" for p in STOP_PHRASES} or t in {f"mxb {p}" for p in STOP_PHRASES}


def is_info_query(text: str) -> bool:
    t = normalize(text)
    if not t or t.startswith(ACTION_STARTERS):
        return False
    return t.startswith(INFO_STARTERS) or (text or "").strip().endswith("?")


def format_result(result: str) -> str:
    """Turns router output ("MXB: ...\\nAction: ...") into clean chat text."""
    if not result:
        return ""
    lines = []
    for line in str(result).splitlines():
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"^MXB:\s*", "", line)
        if line:
            lines.append(line)
    return "\n".join(lines)


class CommandBus(QObject):
    user_message = Signal(str, str)          # text, source ("voice" / "text")
    reply_ready = Signal(str, str)           # reply text, source
    feedback = Signal(str)                   # live step-by-step progress
    status_changed = Signal(str)             # "Idle", "Working: ...", "Waiting for confirmation"
    confirmation_requested = Signal(str)     # question
    confirmation_resolved = Signal(bool)
    open_chat_requested = Signal()
    qr_ready = Signal(str, bytes)            # phone remote URL + QR PNG for the chat window

    def __init__(self, config: dict | None = None, router=None, start: bool = True):
        super().__init__()
        self.config = config or {}
        if router is None:
            from engine.router import IntentRouter
            router = IntentRouter()
        self.router = router
        self.executor = router.executor

        # Thread-aware TTS: voice in -> voice + text out; text in -> text out.
        from engine.tts import ModalityTTS
        if not isinstance(router.tts, ModalityTTS):
            router.tts = ModalityTTS(router.tts)
        self.tts = router.tts

        voice_cfg = self.config.get("voice", {})
        self.speak_text_replies = bool(voice_cfg.get("speak_text_replies", False))

        safety_cfg = self.config.get("safety", {})
        self.confirm = ConfirmationManager(timeout=float(safety_cfg.get("confirmation_timeout_sec", 30)))
        if hasattr(self.executor, "confirm_callback"):
            self.executor.confirm_callback = self.request_confirmation
        if hasattr(self.executor, "feedback_callback"):
            self.executor.feedback_callback = self.feedback.emit
        # v4 hooks: background announcements, routines, skills speech
        if hasattr(self.executor, "announce"):
            self.executor.announce = self.announce
        if hasattr(self.executor, "command_runner"):
            self.executor.command_runner = lambda text: self.router.route(text, feedback_callback=self.feedback.emit)
        if hasattr(self.executor, "speak"):
            self.executor.speak = lambda text: self.tts.speak(text)
        self.scheduler = None
        self.remote = None
        # Indian languages: commands are translated to English for routing; replies come back translated.
        self.indic = IndicBridge(self.config, llm_getter=lambda: getattr(self.executor, "llm", None))

        listen_cfg = self.config.get("listening", {})
        self.wake = WakeWordGate(
            mode=listen_cfg.get("mode", "wake_word"),
            wake_words=listen_cfg.get("wake_words"),
            follow_up_seconds=float(listen_cfg.get("follow_up_seconds", 15)),
        )

        self.action_queue: queue.Queue = queue.Queue(maxsize=25)
        self.info_queue: queue.Queue = queue.Queue(maxsize=10)
        self._running = True
        self._action_busy = threading.Event()
        self.current_task = ""
        self._workers: list[threading.Thread] = []
        if start:
            self.start()

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        if self._workers:
            return
        for name, q, lane in (("MXB-Action-Lane", self.action_queue, "action"),
                              ("MXB-Info-Lane", self.info_queue, "info")):
            t = threading.Thread(target=self._worker, args=(q, lane), name=name, daemon=True)
            t.start()
            self._workers.append(t)

    def start_services(self, scheduler=True, remote=True):
        """Starts the scheduler and prepares the phone remote (it only listens once turned on)."""
        services = getattr(self.executor, "services", None)
        if scheduler and self.scheduler is None:
            from engine.scheduler import Scheduler
            self.scheduler = Scheduler(fire=self._fire_job)
            self.scheduler.start()
            if services is not None:
                services["scheduler"] = self.scheduler
        if remote and self.remote is None:
            from engine.remote_server import RemoteServer
            screen = getattr(self.executor, "screen", None)
            grab = getattr(screen, "capture_screen_image", None)
            self.remote = RemoteServer(bus=self, config=self.config, screen_grabber=grab)
            if services is not None:
                services["remote"] = self.remote
            if self.config.get("remote", {}).get("enabled", False):
                try:
                    self.remote.start()
                except OSError as e:
                    log.warning(f"CommandBus: phone remote could not start: {e}")
        hooks = getattr(self.executor, "ui_hooks", None)
        if hooks is not None:
            hooks.setdefault("show_qr", lambda url, png: self.qr_ready.emit(url, png or b""))

    def _fire_job(self, job: dict):
        if job.get("kind") == "reminder":
            text = f"Reminder: {job['text']}"
            try:
                from utils.notifications import Notifier
                Notifier.show_notification("MXB Reminder", job["text"])
            except Exception:
                pass
            try:
                from utils.audio_feedback import audio_feedback
                audio_feedback.play("listen")
            except Exception:
                pass
            self.reply_ready.emit(text, "schedule")
            try:
                self.tts.speak_always(text)
            except Exception:
                pass
        else:
            self.feedback.emit(f"Scheduled: {job['text']}")
            self.submit(job["text"], "schedule")

    def announce(self, text: str, speak: bool = True):
        """Background jobs (indexing, scheduler) report back here."""
        self.reply_ready.emit(text, "system")
        if speak:
            try:
                self.tts.speak_always(text)
            except Exception:
                pass

    def shutdown(self):
        self._running = False
        executor = getattr(self.router, "executor", None)
        if executor is not None and hasattr(executor, "shutdown"):
            executor.shutdown()
        if self.scheduler is not None:
            self.scheduler.stop()
        if self.remote is not None:
            try:
                self.remote.stop()
            except Exception:
                pass
        self.confirm.cancel_pending()
        for q in (self.action_queue, self.info_queue):
            try:
                q.put_nowait(None)
            except queue.Full:
                pass

    @property
    def busy(self) -> bool:
        return self._action_busy.is_set()

    # ------------------------------------------------------------------ control lane
    def submit(self, text: str, source: str = "text", lang: str | None = None) -> str:
        """
        Entry point for every user utterance. Returns a short code describing what
        happened ("stopped", "confirmed", "ignored", "queued", ...) for tests/UI.
        """
        text = (text or "").strip()
        if not text:
            return "empty"
        norm = normalize(text)

        # 1. Emergency stop always wins (no wake word, no queue), in every supported language.
        if is_stop_command(text) or indic_is_stop(text):
            self.user_message.emit(text, source)
            self.stop_all()
            return "stopped"

        # 2. Answer to a pending yes/no question.
        if self.confirm.has_pending():
            decision = self.confirm.answer_text(text)
            if decision is not None:
                self.user_message.emit(text, source)
                self.confirmation_resolved.emit(decision)
                self.reply_ready.emit("Okay, doing it." if decision else "Okay, cancelled.", source)
                return "confirmed" if decision else "denied"

        # 3. Wake word gate for voice.
        if source == "voice":
            gated = self.wake.process(text)
            if gated is None:
                log.info(f"CommandBus: ignored (no wake word): '{text}'")
                self.feedback.emit(f"(Heard \"{text[:40]}\" — say \"MXB\" first to give a command.)")
                return "ignored"
            if gated == "":
                self.user_message.emit(text, source)
                self._say("Yes?", source)
                return "woke"
            text, norm = gated, normalize(gated)
        else:
            found, rest = self.wake.strip_wake_word(text)  # typed "MXB, open chrome" works too
            if found and rest:
                text, norm = rest, normalize(rest)

        self.user_message.emit(text, source)

        # 4. Instant meta commands.
        if norm in STATUS_PHRASES:
            self._say(self.describe_status(), source)
            return "status"
        if norm in OPEN_CHAT_PHRASES:
            self.open_chat_requested.emit()
            self._say("Chat window is open.", source, speak=False)
            return "open_chat"

        # 5. Lane selection.
        lane_queue = self.action_queue
        lane = "action"
        if self.busy and is_info_query(text):
            lane_queue, lane = self.info_queue, "info"
        try:
            lane_queue.put_nowait((text, source, lang))
        except queue.Full:
            self._say("I'm overloaded with queued commands. Say stop to clear them.", source)
            return "full"
        if lane == "action" and self.busy:
            self.feedback.emit(f"Queued: \"{text[:50]}\" (after the current task)")
        return lane

    def _say(self, text: str, source: str, speak: bool | None = None):
        should_speak = (source == "voice" or self.speak_text_replies) if speak is None else speak
        if should_speak:
            try:
                self.tts.speak_always(text)
            except Exception:
                pass
        self.reply_ready.emit(text, source)

    def stop_all(self):
        log.warning("CommandBus: STOP — aborting actions, clearing queues, silencing speech.")
        try:
            self.executor.abort_current_action()
        except Exception as e:
            log.error(f"CommandBus: abort failed: {e}")
        self.confirm.cancel_pending()
        for q in (self.action_queue, self.info_queue):
            with q.mutex:
                q.queue.clear()
        try:
            self.tts.interrupt()
        except Exception:
            pass
        self.feedback.emit("STOPPED: all actions halted.")
        self.reply_ready.emit("Stopped.", "system")
        try:
            self.tts.speak_always("Stopped.")
        except Exception:
            pass

    def describe_status(self) -> str:
        if self.confirm.has_pending():
            return f"I'm waiting for your answer: {self.confirm.question}"
        if not self.busy:
            return "I'm free. What should I do?"
        step = getattr(getattr(self.executor, "planner", None), "current_step", "") or ""
        pending = self.action_queue.qsize()
        extra = f" {pending} more queued." if pending else ""
        return f"Working on: {self.current_task}. {step}".strip() + extra

    # ------------------------------------------------------------------ confirmations
    def request_confirmation(self, question: str) -> bool:
        """Called by the executor from a worker thread; blocks until answered."""
        def announce(q):
            self.status_changed.emit("Waiting for confirmation")
            self.confirmation_requested.emit(q)
            self.feedback.emit(f"CONFIRM: {q} (say or type yes / no)")
            try:
                self.tts.speak_always(f"{q} Say yes or no.")
            except Exception:
                pass

        abort_event = getattr(getattr(self.executor, "planner", None), "abort_event", None)
        approved = self.confirm.request(question, announce=announce, abort_event=abort_event)
        self.confirmation_resolved.emit(approved)
        return approved

    def resolve_confirmation(self, approved: bool):
        """Used by chat buttons."""
        if self.confirm.resolve(approved):
            self.confirmation_resolved.emit(approved)

    # ------------------------------------------------------------------ workers
    def _worker(self, q: queue.Queue, lane: str):
        while self._running:
            try:
                item = q.get(timeout=0.25)
            except queue.Empty:
                continue
            if item is None:
                break
            text, source, lang_hint = (tuple(item) + (None,))[:3]
            lang = None
            try:
                from safety.injection import set_source
                set_source(source)
                self.tts.set_thread_speaking(source == "voice" or self.speak_text_replies)
                lang = self.indic.detect(text, hint=lang_hint)
                if lang:
                    english = self.indic.to_english(text, lang)
                    if english != text:
                        self.feedback.emit(f"{self.indic.describe(lang)}: \"{english[:80]}\"")
                    text = english
                set_reply_language(lang)
                if hasattr(self.tts, "set_thread_language"):
                    self.tts.set_thread_language(lang, self.indic.from_english if lang else None)
                if lane == "action":
                    self._action_busy.set()
                    self.current_task = text
                self.status_changed.emit(f"Working: {text[:60]}")
                self.feedback.emit("Reasoning & Planning...")
                started = time.time()
                result = self.router.route(text, feedback_callback=self.feedback.emit)
                log.info(f"CommandBus[{lane}] '{text}' -> {result!r} ({time.time() - started:.2f}s)")
                reply = format_result(result)
                if lang:
                    reply = self.indic.from_english(reply, lang)
                self.reply_ready.emit(reply, source)
                if source == "voice":
                    self.wake.engage()
            except Exception as e:
                log.error(f"CommandBus[{lane}] error: {e}")
                self.reply_ready.emit(f"Something went wrong: {e}", source)
            finally:
                set_reply_language(None)
                if hasattr(self.tts, "set_thread_language"):
                    self.tts.set_thread_language(None, None)
                if lane == "action":
                    self.current_task = ""
                    if q.empty():
                        self._action_busy.clear()
                if not self.busy:
                    self.status_changed.emit("Idle")
                q.task_done()
