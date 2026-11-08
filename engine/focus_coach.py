"""
Focus & study coach: focus sessions with gentle nudges, screen-time reports and eye-break reminders.

Privacy first: nothing is tracked until the user asks. Usage is stored on this PC only (activity.db
in MXB's data folder) as app or site NAMES with seconds per day: never window titles, page titles,
URLs or content. A title is read for a moment to tell YouTube from LeetCode, then discarded.

- "start a 50 minute focus session for DSA practice": MXB watches which app/site is in front.
  After 10 seconds on a distraction it says "You're on YouTube, 32 minutes left on DSA practice".
  "strict" also minimizes the distracting window; "allow YouTube" whitelists it for that session.
  At the end: a summary (focused vs distracted minutes) and a break suggestion.
- "how much screen time today / this week / on YouTube": local reports ("track my screen time" first).
- "remind me to rest my eyes": every 20 minutes of continuous screen use, a 20-20-20 reminder.
- In a Zoom/Teams/Meet call, MXB offers once to take meeting notes.
"""
import re
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from utils.logger import log

FOCUS, DISTRACTION, COMMS, MEETING, NEUTRAL, IDLE = "focus", "distraction", "communication", "meeting", "neutral", "idle"
BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe", "arc.exe", "iexplore.exe"}
BROWSER_NAMES = ("google chrome", "microsoft edge", "mozilla firefox", "brave", "opera", "vivaldi", "arc")
SEPARATORS = re.compile(r"\s+[-|·—–/]\s+")

# (pattern searched in one title segment, label, category, passive = fine to watch without touching the keyboard)
SITES = [
    (r"youtube", "YouTube", DISTRACTION, True),
    (r"instagram", "Instagram", DISTRACTION, False),
    (r"facebook", "Facebook", DISTRACTION, False),
    (r"^x$|twitter", "X (Twitter)", DISTRACTION, False),
    (r"reddit", "Reddit", DISTRACTION, False),
    (r"netflix", "Netflix", DISTRACTION, True),
    (r"hotstar", "JioHotstar", DISTRACTION, True),
    (r"prime video", "Prime Video", DISTRACTION, True),
    (r"twitch", "Twitch", DISTRACTION, True),
    (r"cricbuzz|espncricinfo", "Cricket scores", DISTRACTION, False),
    (r"amazon\.in|amazon\.com|flipkart|myntra|meesho|ajio", "Shopping", DISTRACTION, False),
    (r"discord", "Discord", DISTRACTION, False),
    (r"whatsapp", "WhatsApp", COMMS, False),
    (r"telegram", "Telegram", COMMS, False),
    (r"gmail|outlook", "Email", COMMS, False),
    (r"^meet\b|google meet", "Google Meet", MEETING, True),
    (r"^zoom( meeting| workplace)?$", "Zoom", MEETING, True),
    (r"github", "GitHub", FOCUS, False),
    (r"stack overflow", "Stack Overflow", FOCUS, False),
    (r"leetcode", "LeetCode", FOCUS, False),
    (r"geeksforgeeks", "GeeksforGeeks", FOCUS, False),
    (r"hackerrank|codeforces|codechef", "Coding practice", FOCUS, False),
    (r"kaggle", "Kaggle", FOCUS, False),
    (r"colab", "Google Colab", FOCUS, False),
    (r"coursera|udemy|nptel|swayam|edx|khan academy", "Online course", FOCUS, True),
    (r"arxiv|overleaf", "Research", FOCUS, False),
    (r"chatgpt|claude|gemini|perplexity", "AI assistant", FOCUS, False),
    (r"google docs|google sheets|google slides|notion", "Docs", FOCUS, False),
    (r"spotify|jiosaavn|gaana|wynk", "Music", NEUTRAL, True),
    (r"linkedin", "LinkedIn", NEUTRAL, False),
]
APPS = {
    "code.exe": ("VS Code", FOCUS, False), "cursor.exe": ("Cursor", FOCUS, False),
    "pycharm64.exe": ("PyCharm", FOCUS, False), "idea64.exe": ("IntelliJ IDEA", FOCUS, False),
    "devenv.exe": ("Visual Studio", FOCUS, False), "sublime_text.exe": ("Sublime Text", FOCUS, False),
    "notepad++.exe": ("Notepad++", FOCUS, False), "notepad.exe": ("Notepad", FOCUS, False),
    "windowsterminal.exe": ("Terminal", FOCUS, False), "cmd.exe": ("Terminal", FOCUS, False),
    "powershell.exe": ("Terminal", FOCUS, False), "pwsh.exe": ("Terminal", FOCUS, False),
    "rstudio.exe": ("RStudio", FOCUS, False), "matlab.exe": ("MATLAB", FOCUS, False),
    "winword.exe": ("Word", FOCUS, False), "excel.exe": ("Excel", FOCUS, False),
    "powerpnt.exe": ("PowerPoint", FOCUS, False), "onenote.exe": ("OneNote", FOCUS, False),
    "obsidian.exe": ("Obsidian", FOCUS, False), "notion.exe": ("Notion", FOCUS, False),
    "acrord32.exe": ("PDF reader", FOCUS, True), "acrobat.exe": ("PDF reader", FOCUS, True),
    "sumatrapdf.exe": ("PDF reader", FOCUS, True), "postman.exe": ("Postman", FOCUS, False),
    "figma.exe": ("Figma", FOCUS, False),
    "spotify.exe": ("Spotify", NEUTRAL, True),
    "discord.exe": ("Discord", DISTRACTION, False), "steam.exe": ("Steam", DISTRACTION, False),
    "steamwebhelper.exe": ("Steam", DISTRACTION, False), "epicgameslauncher.exe": ("Epic Games", DISTRACTION, False),
    "vlc.exe": ("VLC", DISTRACTION, True),
    "whatsapp.exe": ("WhatsApp", COMMS, False), "telegram.exe": ("Telegram", COMMS, False),
    "outlook.exe": ("Outlook", COMMS, False), "olk.exe": ("Outlook", COMMS, False),
    "thunderbird.exe": ("Thunderbird", COMMS, False),
    "zoom.exe": ("Zoom", COMMS, False), "ms-teams.exe": ("Teams", COMMS, False), "teams.exe": ("Teams", COMMS, False),
}
CALL_WORDS = re.compile(r"(?i)\b(meeting|call|huddle)\b")


@dataclass
class Sample:
    at: float
    label: str | None
    category: str
    seconds: float
    hwnd: int = 0


def _strip_browser(title: str) -> str:
    text = title.replace("​", "").strip()
    low = text.lower()
    for name in BROWSER_NAMES:
        if low.endswith(name):
            text = text[: len(text) - len(name)]
            break
    return re.sub(r"[\s\-|·—–]+$", "", text)


def classify(app: str, title: str = "", productive=(), distracting=()) -> tuple[str, str, bool]:
    """(label, category, passive) for the foreground window. Titles are only used to name the site."""
    proc = (app or "").lower().strip()
    if proc in BROWSERS:
        segments = [s.strip().lower() for s in SEPARATORS.split(_strip_browser(title or "")) if s.strip()]
        found = None
        for seg in list(reversed(segments[-3:])) + segments[:-3]:      # sites put their name at the end
            for pattern, label, category, passive in SITES:
                if re.search(pattern, seg):
                    found = (label, category, passive)
                    break
            if found:
                break
        label, category, passive = found or ("Web browsing", NEUTRAL, False)
    elif proc in APPS:
        label, category, passive = APPS[proc]
        if label in ("Zoom", "Teams") and CALL_WORDS.search(title or ""):
            category, passive = MEETING, True
    else:
        stem = Path(proc).stem if proc else "unknown app"
        label, category, passive = stem[:1].upper() + stem[1:], NEUTRAL, False
    names = {label.lower(), proc, Path(proc).stem}
    if names & {n.lower() for n in productive}:
        category = FOCUS
    elif names & {n.lower() for n in distracting}:
        category = DISTRACTION
    return label, category, passive


STOP_WORDS = {"time", "screen", "today", "week", "with", "much", "long", "spent", "this", "yesterday", "used"}


def label_mentioned(label: str, text: str) -> bool:
    """'how long on youtube' mentions YouTube; 'twitter' mentions 'X (Twitter)'."""
    low = label.lower()
    if re.search(rf"(?<![a-z0-9]){re.escape(low)}(?![a-z0-9])", text):
        return True
    words = [w for w in re.findall(r"[a-z0-9]+", low) if len(w) >= 4 and w not in STOP_WORDS]
    return any(re.search(rf"\b{re.escape(w)}\b", text) for w in words)


def minutes_text(seconds: float) -> str:
    minutes = int(seconds / 60 + 0.5)
    if seconds < 60:
        return "under a minute" if seconds > 0 else "no time"
    hours, mins = divmod(minutes, 60)
    if hours and mins:
        return f"{hours} h {mins} min"
    return f"{hours} h" if hours else f"{mins} min"


def parse_session_request(text: str, default_minutes: int = 25) -> tuple[int, str, bool, set]:
    """'strict 50 minutes for DSA practice, allow LeetCode' -> (50, 'DSA practice', True, {'leetcode'})."""
    raw = " " + (text or "").strip() + " "
    minutes = None
    m = re.search(r"(?i)\b(\d+(?:\.\d+)?)\s*(hours?|hrs?|h)\b", raw)
    if m:
        minutes = float(m.group(1)) * 60
        raw = raw.replace(m.group(0), " ")
    m = re.search(r"(?i)\b(\d+)\s*(minutes?|mins?|m)\b", raw)
    if m:
        minutes = (minutes or 0) + int(m.group(1))
        raw = raw.replace(m.group(0), " ")
    if minutes is None:
        for phrase, value in (("half an hour", 30), ("an hour", 60), ("one hour", 60), ("pomodoro", 25)):
            if phrase in raw.lower():
                minutes = value
                raw = re.sub(re.escape(phrase), " ", raw, flags=re.I)
                break
    strict = bool(re.search(r"(?i)\bstrict(ly)?\b", raw))
    raw = re.sub(r"(?i)\bstrict(ly)?\b", " ", raw)
    allowed = set()
    m = re.search(r"(?i)[,;]?\s*\b(?:allow|allowing|except)\s+(.+?)\s*$", raw)
    if m:
        allowed = {a.strip().lower() for a in re.split(r",|\band\b", m.group(1)) if a.strip()}
        raw = raw[: m.start()]
    goal = re.sub(r"(?i)^\s*(?:(?:a|an|the|my)\s+)?(?:(?:focus(?:ing)?|study(?:ing)?|deep\s*work|pomodoro)\b\s*)?"
                  r"(?:(?:session|mode|block|timer|sprint)\b)?\s*", " ", raw)
    goal = re.sub(r"\s+", " ", goal).strip(" ,.-")
    goal = re.sub(r"(?i)^(?:(?:for|on|to|about)\b\s*)+", "", goal)
    goal = re.sub(r"(?i)(?:\s*\b(?:for|on|to|about))+$", "", goal).strip(" ,.-")
    minutes = int(max(1, min(240, round(minutes or default_minutes))))
    return minutes, goal, strict, allowed


# ---------------------------------------------------------------------------
# Storage: names and seconds only
# ---------------------------------------------------------------------------
class ActivityStore:
    def __init__(self, path: Path | str | None = None):
        if path is None:
            from utils.paths import data_file
            path = data_file("activity.db")
        self.path = Path(path)
        with self._conn() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT, label TEXT, category TEXT, seconds REAL, "
                         "PRIMARY KEY (day, label))")
            conn.execute("CREATE TABLE IF NOT EXISTS sessions (started REAL, ended REAL, goal TEXT, planned_min INTEGER, "
                         "focused REAL, distracted REAL, other REAL, nudges INTEGER, completed INTEGER)")

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def add_usage(self, day: str, label: str, category: str, seconds: float):
        with self._conn() as conn:
            conn.execute("INSERT INTO usage (day, label, category, seconds) VALUES (?, ?, ?, ?) "
                         "ON CONFLICT(day, label) DO UPDATE SET seconds = seconds + excluded.seconds, "
                         "category = excluded.category", (day, label, category, float(seconds)))

    def usage(self, first_day: str, last_day: str) -> list[tuple[str, str, float]]:
        with self._conn() as conn:
            rows = conn.execute("SELECT label, category, SUM(seconds) FROM usage WHERE day BETWEEN ? AND ? "
                                "GROUP BY label ORDER BY SUM(seconds) DESC", (first_day, last_day)).fetchall()
        return [(r[0], r[1], float(r[2])) for r in rows]

    def add_session(self, **row):
        with self._conn() as conn:
            conn.execute("INSERT INTO sessions VALUES (:started, :ended, :goal, :planned_min, :focused, :distracted, "
                         ":other, :nudges, :completed)", row)

    def sessions_since(self, ts: float) -> list[dict]:
        with self._conn() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute("SELECT * FROM sessions WHERE started >= ? ORDER BY started", (ts,))]

    def forget(self):
        with self._conn() as conn:
            conn.execute("DELETE FROM usage")
            conn.execute("DELETE FROM sessions")


# ---------------------------------------------------------------------------
# Sampling the foreground window
# ---------------------------------------------------------------------------
def windows_probe():
    """(process name, window title, seconds since the last key/mouse input, hwnd) on Windows."""
    import ctypes
    from ctypes import wintypes
    import psutil

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
    user32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name()
    except Exception:
        app = ""
    info = LASTINPUTINFO()
    info.cbSize = ctypes.sizeof(info)
    user32.GetLastInputInfo(ctypes.byref(info))
    idle = ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000.0
    return app, buf.value, idle, int(hwnd or 0)


def minimize_window(hwnd: int):
    import ctypes
    ctypes.windll.user32.ShowWindow(hwnd, 6)        # SW_MINIMIZE: nothing is closed or lost


class ActivityTracker:
    def __init__(self, probe=None, store: ActivityStore | None = None, config: dict | None = None,
                 interval: float = 5.0, idle_after: float = 120.0, clock=time.time, flush_every: float = 60.0):
        cfg = (config or {}).get("focus", {}) or {}
        self.probe = probe or windows_probe
        self.store = store
        self.interval = interval
        self.idle_after = float(cfg.get("idle_after_seconds", idle_after))
        self.productive = cfg.get("productive", []) or []
        self.distracting = cfg.get("distracting", []) or []
        self.clock = clock
        self.flush_every = flush_every
        self.store_usage = False
        self.keep_running = lambda: True    # checked after every sample; the loop ends itself when False
        self.listeners: list = []
        self._last = None
        self._buffer: dict[tuple[str, str, str], float] = {}
        self._flushed = clock()
        self._lock = threading.Lock()
        self._run_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._exiting = False

    def tick(self) -> Sample | None:
        now = self.clock()
        elapsed = 0.0 if self._last is None else max(0.0, min(now - self._last, self.interval * 3))  # sleep gaps don't count
        self._last = now
        try:
            app, title, idle, hwnd = self.probe()
        except Exception as e:
            log.debug(f"FocusCoach: probe failed: {e}")
            return None
        label, category, passive = classify(app, title, self.productive, self.distracting)
        if idle >= self.idle_after and not passive:
            label, category = None, IDLE
        sample = Sample(now, label, category, elapsed, hwnd)
        if self.store_usage and label and elapsed:
            key = (time.strftime("%Y-%m-%d", time.localtime(now)), label, category)
            with self._lock:
                self._buffer[key] = self._buffer.get(key, 0.0) + elapsed
            if now - self._flushed >= self.flush_every:
                self.flush()
        for fn in list(self.listeners):
            try:
                fn(sample)
            except Exception as e:
                log.warning(f"FocusCoach: listener failed: {e}")
        return sample

    def flush(self):
        with self._lock:
            pending, self._buffer = self._buffer, {}
            self._flushed = self.clock()
        if self.store is None:
            return
        for (day, label, category), seconds in pending.items():
            try:
                self.store.add_usage(day, label, category, seconds)
            except Exception as e:
                log.warning(f"FocusCoach: couldn't save usage: {e}")

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._exiting

    def start(self):
        with self._run_lock:
            if self.running:
                return
            if self._thread is not None:            # it's finishing on its own: let it, then restart
                self._thread.join(timeout=3)
            self._exiting = False
            self._stop.clear()
            self._last = None
            self._thread = threading.Thread(target=self._run, name="mxb-focus-tracker", daemon=True)
            self._thread.start()

    def _run(self):
        self.tick()
        while not self._stop.wait(self.interval):
            self.tick()
            with self._run_lock:
                if not self.keep_running():
                    self._exiting = True
                    break
        self.flush()

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3)
        self._thread = None
        self._exiting = False
        self.flush()


# ---------------------------------------------------------------------------
# Focus sessions
# ---------------------------------------------------------------------------
@dataclass
class FocusSession:
    minutes: int
    goal: str = ""
    strict: bool = False
    allowed: set = field(default_factory=set)
    started: float = 0.0
    nudge_after: float = 10.0
    renudge_every: float = 120.0
    focused: float = 0.0
    distracted: float = 0.0
    other: float = 0.0
    idle: float = 0.0
    nudges: int = 0
    distractions: dict = field(default_factory=dict)
    _streak: float = 0.0
    _next_nudge: float = 0.0

    @property
    def ends_at(self) -> float:
        return self.started + self.minutes * 60

    @property
    def name(self) -> str:
        return f"'{self.goal}'" if self.goal else "your focus session"

    def remaining(self, now: float) -> float:
        return max(0.0, self.ends_at - now)

    def on_sample(self, s: Sample) -> str | None:
        """Adds the sample's time; returns a nudge when it's time for one."""
        secs = max(0.0, min(s.seconds, s.at - self.started, self.ends_at - (s.at - s.seconds)))
        allowed = bool(s.label) and s.label.lower() in self.allowed
        if s.category == DISTRACTION and not allowed:
            self.distracted += secs
            self.distractions[s.label] = self.distractions.get(s.label, 0.0) + secs
            self._streak += secs
            if self._streak >= self._next_nudge:
                self._next_nudge = self._streak + self.renudge_every
                self.nudges += 1
                left = minutes_text(self.remaining(s.at))
                if self.strict:
                    return f"{s.label} is off limits until {self.name} ends. I minimized it. {left} to go."
                return f"You're on {s.label}. {left} left on {self.name}. Back to it?"
            return None
        self._streak = 0.0
        self._next_nudge = self.nudge_after
        if s.category == FOCUS or allowed:
            self.focused += secs
        elif s.category == IDLE:
            self.idle += secs
        else:
            self.other += secs
        return None

    def __post_init__(self):
        self._next_nudge = self.nudge_after

    def summary(self, now: float, completed: bool) -> str:
        spent = minutes_text(min(now, self.ends_at) - self.started)
        head = f"Focus session done: {spent} on {self.name}." if completed else f"Stopped {self.name} after {spent}."
        parts = [head, f"Focused {minutes_text(self.focused)}"]
        if self.distracted:
            top = sorted(self.distractions.items(), key=lambda kv: -kv[1])[:2]
            parts[-1] += f", distracted {minutes_text(self.distracted)} (" + ", ".join(
                f"{label} {minutes_text(sec)}" for label, sec in top) + ")"
        if self.other:
            parts[-1] += f", other apps {minutes_text(self.other)}"
        parts[-1] += "."
        if completed:
            brk = 5 if self.minutes <= 30 else (10 if self.minutes <= 60 else 15)
            parts.append(f"Take a {brk}-minute break: stand up, drink water, look at something far away.")
        return " ".join(parts)


class FocusCoach:
    def __init__(self, config: dict, announce, store: ActivityStore | None = None, probe=None, clock=time.time,
                 minimize=None, save_setting=None, meeting_active=None, interval: float = 5.0, background: bool = True):
        self.config = config
        cfg = config.get("focus", {}) or {}
        self.announce = announce or (lambda text: None)
        self.store = store
        self.clock = clock
        self.minimize = minimize or minimize_window
        self.save_setting = save_setting or (lambda key, value: None)
        self.meeting_active = meeting_active or (lambda: False)
        self.default_minutes = int(cfg.get("default_minutes", 25))
        self.track = bool(cfg.get("track_activity", False))
        self.eye_break_minutes = float(cfg.get("eye_break_minutes", 0) or 0)
        self.offer_meeting_notes = bool(cfg.get("offer_meeting_notes", True))
        self.background = background            # False in tests: samples come from tracker.tick() calls
        self.tracker = ActivityTracker(probe=probe, store=store, config=config, interval=interval, clock=clock)
        self.tracker.store_usage = self.track
        self.tracker.keep_running = self._needs_tracker
        self.tracker.listeners.append(self._on_sample)
        self.session: FocusSession | None = None
        self._lock = threading.Lock()
        self._screen_streak = 0.0
        self._meeting_streak = 0.0
        self._meeting_offered_at = -1e9

    # ------------------------------------------------------------------ lifecycle
    def _needs_tracker(self) -> bool:
        return self.track or self.eye_break_minutes > 0 or self.session is not None

    def _sync_tracker(self):
        if not self.background:
            return
        if self._needs_tracker():
            self.tracker.start()
        elif self.tracker.running:
            self.tracker.stop()

    def start(self):
        """Called once at startup: only runs if the user turned tracking or eye breaks on."""
        self._sync_tracker()

    def shutdown(self):
        if self.session is not None:
            self._finish(completed=False, speak=False)
        self.tracker.stop()

    # ------------------------------------------------------------------ the sampling loop
    def _on_sample(self, s: Sample):
        messages = []
        with self._lock:
            if s.category == IDLE:
                self._screen_streak = 0.0
            else:
                self._screen_streak += s.seconds
                if self.eye_break_minutes and self._screen_streak >= self.eye_break_minutes * 60:
                    self._screen_streak = 0.0
                    messages.append("Eye break: look at something about 20 feet (6 metres) away for 20 seconds.")
            if s.category == MEETING:
                self._meeting_streak += s.seconds
                if (self.offer_meeting_notes and self._meeting_streak >= 30
                        and s.at - self._meeting_offered_at > 3600 and not self.meeting_active()):
                    self._meeting_offered_at = s.at
                    messages.append(f"Looks like you're in a {s.label} call. Say 'take meeting notes' and I'll "
                                    "transcribe it and write up the decisions and action items.")
            else:
                self._meeting_streak = 0.0
            session = self.session
            if session is not None:
                nudge = session.on_sample(s)
                if nudge:
                    if session.strict and s.hwnd:
                        try:
                            self.minimize(s.hwnd)
                        except Exception as e:
                            log.warning(f"FocusCoach: couldn't minimize: {e}")
                    messages.append(nudge)
                if s.at >= session.ends_at:
                    messages.append(self._finish(completed=True, speak=False, now=s.at))
        for text in messages:
            self.announce(text)

    # ------------------------------------------------------------------ sessions
    def start_session(self, target: str = "") -> str:
        minutes, goal, strict, allowed = parse_session_request(target, self.default_minutes)
        with self._lock:
            if self.session is not None:
                left = minutes_text(self.session.remaining(self.clock()))
                return f"You're already in a focus session on {self.session.name}, {left} left. Say 'stop focus' to end it."
            self.session = FocusSession(minutes=minutes, goal=goal, strict=strict, allowed=allowed, started=self.clock(),
                                        renudge_every=15.0 if strict else 120.0)
        self._sync_tracker()
        extra = []
        if strict:
            extra.append("Strict mode: I'll minimize distracting apps and sites")
        if allowed:
            extra.append("Allowed: " + ", ".join(sorted(allowed)))
        tail = (" " + ". ".join(extra) + ".") if extra else " I'll nudge you if you drift to a distraction."
        return f"Focus session started: {minutes} minutes on {self.session.name}.{tail}"

    def _finish(self, completed: bool, speak: bool = True, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        session, self.session = self.session, None
        if session is None:
            return "There's no focus session running."
        text = session.summary(now, completed)
        if self.store is not None:
            try:
                self.store.add_session(started=session.started, ended=now, goal=session.goal, planned_min=session.minutes,
                                       focused=session.focused, distracted=session.distracted, other=session.other,
                                       nudges=session.nudges, completed=int(completed))
            except Exception as e:
                log.warning(f"FocusCoach: couldn't save the session: {e}")
        if speak:
            self.announce(text)
        return text

    def stop_session(self) -> str:
        with self._lock:
            text = self._finish(completed=False, speak=False)
        self._sync_tracker()        # (a session that ends on its own stops the tracker from inside its loop)
        return text

    def status(self) -> str:
        session = self.session
        if session is None:
            return "No focus session is running. Say 'start a focus session' to begin one."
        now = self.clock()
        return (f"{minutes_text(session.remaining(now))} left on {session.name}. So far: focused "
                f"{minutes_text(session.focused)}, distracted {minutes_text(session.distracted)}.")

    # ------------------------------------------------------------------ settings
    def set_tracking(self, on: bool) -> str:
        self.track = bool(on)
        self.tracker.store_usage = self.track
        self.save_setting("track_activity", self.track)
        if not on:
            self.tracker.flush()
        self._sync_tracker()
        if on:
            return ("Okay, I'm tracking screen time on this PC only, as app and site names with minutes. "
                    "No window titles or content. Say 'stop tracking my screen time' anytime.")
        return "Stopped tracking screen time. Say 'delete my screen time data' to erase what's saved."

    def set_eye_breaks(self, target: str) -> str:
        text = (target or "on").lower()
        if any(w in text for w in ("off", "stop", "disable", "no")):
            self.eye_break_minutes = 0
        else:
            m = re.search(r"\d+", text)
            self.eye_break_minutes = float(m.group()) if m else 20.0
        self.save_setting("eye_break_minutes", self.eye_break_minutes)
        self._screen_streak = 0.0
        self._sync_tracker()
        if not self.eye_break_minutes:
            return "Eye-break reminders are off."
        return (f"Okay: after every {int(self.eye_break_minutes)} minutes of continuous screen time I'll remind you "
                "to look about 20 feet away for 20 seconds.")

    def forget_data(self) -> str:
        self.tracker.flush()
        if self.store is not None:
            self.store.forget()
        return "Deleted all saved screen-time and focus-session data."

    # ------------------------------------------------------------------ reports
    def report(self, target: str = "today") -> str:
        if self.store is None:
            return "Screen-time storage isn't available."
        self.tracker.flush()
        text = (target or "today").lower()
        now = self.clock()
        midnight = time.mktime(time.localtime(now)[:3] + (0, 0, 0, 0, 0, -1))
        day = 86400
        if "yesterday" in text:
            since, until, period = midnight - day, midnight, "Yesterday"
        elif "week" in text or "7 days" in text:
            since, until, period = midnight - 6 * day, now + 1, "This week"
        else:
            since, until, period = midnight, now + 1, "Today"
        first = time.strftime("%Y-%m-%d", time.localtime(since + 3600))
        last = time.strftime("%Y-%m-%d", time.localtime(until - 3600 if until <= midnight else now))
        rows = self.store.usage(first, last)
        if not rows:
            if not self.track:
                return ("I'm not tracking screen time yet. Say 'track my screen time' to start: it stays on this PC "
                        "and stores only app and site names with minutes.")
            return f"{period}: nothing recorded yet."
        for label, _, seconds in rows:              # "how long on YouTube this week"
            if label_mentioned(label, text):
                return f"{period}: {minutes_text(seconds)} on {label}."
        by_cat: dict[str, list] = {}
        for label, category, seconds in rows:
            by_cat.setdefault(category, []).append((label, seconds))
        total = sum(sec for _, _, sec in rows)
        parts = [f"{period}: {minutes_text(total)} on screen."]
        for category, word in ((FOCUS, "focused"), (DISTRACTION, "distracted"), (COMMS, "messages and email"),
                               (MEETING, "meetings")):
            items = by_cat.get(category)
            if items:
                secs = sum(s for _, s in items)
                top = ", ".join(f"{label} {minutes_text(s)}" for label, s in items[:3])
                parts.append(f"{word.capitalize()} {minutes_text(secs)} ({top}).")
        sessions = [s for s in self.store.sessions_since(since) if s["started"] < until]
        if sessions:
            done = sum(1 for s in sessions if s["completed"])
            parts.append(f"{len(sessions)} focus session{'s' if len(sessions) != 1 else ''} ({done} completed), "
                         f"{minutes_text(sum(s['focused'] for s in sessions))} focused.")
        return " ".join(parts)
