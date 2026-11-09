"""
Reminders and scheduled commands with natural-language times.

  "remind me in 20 minutes to stretch"
  "remind me at 5 pm to call mom" / "remind me tomorrow at 9 to submit the form"
  "every weekday at 9 am open outlook"   (scheduled command)
  "every 2 hours remind me to drink water"
  "list my reminders" / "cancel reminder 2" / "cancel all reminders"

Jobs persist in schedules.json, so they survive restarts. Scheduled commands run
through the normal CommandBus, which means destructive ones still need a "yes".
"""
import json
import re
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from utils.logger import log
from utils.paths import data_file

WEEKDAYS = {"monday": 0, "mon": 0, "tuesday": 1, "tue": 1, "tues": 1, "wednesday": 2, "wed": 2, "thursday": 3,
            "thu": 3, "thurs": 3, "friday": 4, "fri": 4, "saturday": 5, "sat": 5, "sunday": 6, "sun": 6}
UNITS = {"second": 1, "sec": 1, "minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}
NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
                "eight": 8, "nine": 9, "ten": 10, "fifteen": 15, "twenty": 20, "thirty": 30, "forty five": 45,
                "forty-five": 45, "few": 3, "couple of": 2}

_TIME = r"(?P<h>\d{1,2})(?::|\.)?(?P<m>\d{2})?\s*(?P<ampm>a\.?m\.?|p\.?m\.?)?"


def _parse_clock(text: str, default_pm: bool = False) -> tuple[int, int] | None:
    t = text.strip().lower()
    if t in {"noon", "midday"}:
        return 12, 0
    if t == "midnight":
        return 0, 0
    m = re.fullmatch(_TIME, t)
    if not m:
        return None
    h, mi = int(m.group("h")), int(m.group("m") or 0)
    ampm = (m.group("ampm") or "").replace(".", "")
    if h > 23 or mi > 59:
        return None
    if ampm == "pm" and h < 12:
        h += 12
    elif ampm == "am" and h == 12:
        h = 0
    elif not ampm and default_pm and 1 <= h <= 11:
        h += 12
    return h, mi


def _amount(text: str) -> float | None:
    t = text.strip().lower()
    if re.fullmatch(r"\d+(?:\.\d+)?", t):
        return float(t)
    if t in {"half an", "half a"}:
        return 0.5
    return float(NUMBER_WORDS[t]) if t in NUMBER_WORDS else None


def next_daily(hour: int, minute: int, days: list[int], after: datetime) -> datetime:
    candidate = after.replace(hour=hour, minute=minute, second=0, microsecond=0)
    for _ in range(8):
        if candidate > after and candidate.weekday() in days:
            return candidate
        candidate += timedelta(days=1)
        candidate = candidate.replace(hour=hour, minute=minute)
    return candidate


def compute_next(rule: dict, after: datetime) -> datetime:
    if rule["type"] == "interval":
        return after + timedelta(seconds=int(rule["seconds"]))
    h, m = (int(x) for x in rule["time"].split(":"))
    return next_daily(h, m, rule.get("days", list(range(7))), after)


def parse_when(text: str, now: datetime | None = None) -> dict | None:
    """
    Returns {"next": datetime, "rule": None | {...}, "label": str} or None if not a time expression.
    """
    now = now or datetime.now()
    t = re.sub(r"\s+", " ", (text or "").lower().strip().strip(",."))
    t = re.sub(r"^(?:for|on)\s+(?=(?:every|tomorrow|today|tonight|\d))", "", t)

    # ---- relative: "in 20 minutes", "in an hour", "in half an hour", "after 2 hours"
    m = re.fullmatch(r"(?:in|after)\s+(?P<n>\d+(?:\.\d+)?|half an|half a|an|a|one|two|three|four|five|six|seven|eight|nine|ten|"
                     r"fifteen|twenty|thirty|forty five|forty-five|few|couple of)\s+(?P<u>seconds?|secs?|minutes?|mins?|hours?|hrs?|days?|weeks?)", t)
    if m:
        amount = _amount(m.group("n"))
        unit = m.group("u").rstrip("s")
        unit = {"sec": "sec", "min": "min", "hr": "hr"}.get(unit, unit)
        seconds = amount * UNITS.get(unit, 60)
        when = now + timedelta(seconds=seconds)
        return {"next": when, "rule": None, "label": when.strftime("%I:%M %p").lstrip("0")}

    # ---- intervals: "every 30 minutes", "every 2 hours", "every hour"
    m = re.fullmatch(r"every\s+(?:(?P<n>\d+|two|three|four|five|six|ten|fifteen|twenty|thirty)\s+)?(?P<u>seconds?|minutes?|mins?|hours?|hrs?)", t)
    if m:
        amount = _amount(m.group("n")) if m.group("n") else 1.0
        unit = m.group("u").rstrip("s")
        seconds = max(60, int(amount * UNITS.get(unit, 60)))
        rule = {"type": "interval", "seconds": seconds}
        return {"next": compute_next(rule, now), "rule": rule, "label": t}

    # ---- recurring daily / weekday / specific weekdays
    m = re.fullmatch(r"(?:every\s+(?P<which>day|morning|evening|night|weekday|weekdays|weekend|weekends|"
                     r"(?:(?:mon|tues|tue|wednes|wed|thurs|thu|fri|satur|sat|sun)(?:day)?s?(?:\s*(?:,|and)\s*)?)+)|daily)"
                     r"(?:\s+at\s+(?P<clock>.+))?", t)
    if m:
        which = (m.group("which") or "day").strip()
        clock_text = m.group("clock") or {"morning": "8 am", "evening": "6 pm", "night": "9 pm"}.get(which, "9 am")
        clock = _parse_clock(clock_text, default_pm=which in {"evening", "night"})
        if clock is None:
            return None
        if which in {"weekday", "weekdays"}:
            days = [0, 1, 2, 3, 4]
        elif which in {"weekend", "weekends"}:
            days = [5, 6]
        elif which in {"day", "morning", "evening", "night"}:
            days = list(range(7))
        else:
            days = sorted({WEEKDAYS[w.rstrip("s")] if w.rstrip("s") in WEEKDAYS else WEEKDAYS.get(w, -1)
                           for w in re.findall(r"[a-z]+", which) if w not in {"and"}} - {-1})
            if not days:
                return None
        rule = {"type": "daily", "time": f"{clock[0]:02d}:{clock[1]:02d}", "days": days}
        return {"next": compute_next(rule, now), "rule": rule, "label": t}

    # ---- one-off absolute: "at 5 pm", "tomorrow at 9", "tonight at 9", "on friday at 10 am", "at noon"
    m = re.fullmatch(r"(?:(?P<day>today|tomorrow|tonight|(?:on\s+)?(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s*)?"
                     r"(?:at\s+)?(?P<clock>noon|midnight|midday|\d{1,2}(?:[:.]\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?)?"
                     r"(?:\s+(?P<day2>today|tomorrow|tonight))?", t)
    if m and (m.group("clock") or m.group("day")) and (t.startswith(("at ", "today", "tomorrow", "tonight", "on ", "next ")) or
                                                      re.match(r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday)", t)):
        day = (m.group("day") or m.group("day2") or "").replace("on ", "").replace("next ", "").strip()
        clock = _parse_clock(m.group("clock") or "9 am", default_pm=day == "tonight")
        if clock is None:
            return None
        base = now.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
        clock_text = (m.group("clock") or "").strip()
        ambiguous = bool(re.fullmatch(r"\d{1,2}(?:[:.]\d{2})?", clock_text)) and 1 <= clock[0] <= 11
        if ambiguous and not day and base <= now and base.replace(hour=clock[0] + 12) > now:
            base = base.replace(hour=clock[0] + 12)  # "at 9" said at 3 pm means 9 pm, not 9 am tomorrow
        if day == "tomorrow":
            base += timedelta(days=1)
        elif day in WEEKDAYS:
            delta = (WEEKDAYS[day] - now.weekday()) % 7
            base += timedelta(days=delta or 7) if (delta or base <= now) else timedelta(0)
            if delta == 0 and base <= now:
                base += timedelta(days=7)
        elif base <= now:
            base += timedelta(days=1)
        return {"next": base, "rule": None, "label": base.strftime("%a %I:%M %p").replace(" 0", " ")}
    return None


def split_leading_time(text: str, now: datetime | None = None) -> tuple[str, str] | None:
    """'every day at 9 am open outlook' -> ('every day at 9 am', 'open outlook')"""
    words = (text or "").split()
    for i in range(len(words) - 1, 0, -1):
        if parse_when(" ".join(words[:i]), now):
            return " ".join(words[:i]), " ".join(words[i:])
    return None


def split_trailing_time(text: str, now: datetime | None = None) -> tuple[str, str] | None:
    """'call mom at 5 pm' -> ('call mom', 'at 5 pm')"""
    words = (text or "").split()
    for i in range(1, len(words)):
        if parse_when(" ".join(words[i:]), now):
            return " ".join(words[:i]), " ".join(words[i:])
    return None


class Scheduler:
    def __init__(self, store_path: str | Path | None = None, fire=None, clock=datetime.now):
        self.store_path = Path(store_path) if store_path else data_file("schedules.json")
        self.fire = fire
        self.clock = clock
        self._lock = threading.Lock()
        self.jobs: list[dict] = []
        self._running = False
        self._thread = None
        self._load()

    def _load(self):
        try:
            if self.store_path.exists():
                self.jobs = json.loads(self.store_path.read_text(encoding="utf-8"))
        except Exception:
            self.jobs = []

    def _save(self):
        try:
            self.store_path.write_text(json.dumps(self.jobs, indent=2), encoding="utf-8")
        except Exception as e:
            log.warning(f"Scheduler: could not save: {e}")

    # ------------------------------------------------------------------ adding
    def add(self, kind: str, when_text: str, text: str) -> str:
        parsed = parse_when(when_text, self.clock())
        if not parsed:
            return f"I couldn't understand the time '{when_text}'. Try 'in 20 minutes', 'at 5 pm' or 'every day at 9 am'."
        job = {"id": uuid.uuid4().hex[:8], "kind": kind, "text": text.strip(), "when": when_text.strip(),
               "next": parsed["next"].isoformat(timespec="seconds"), "rule": parsed["rule"], "created": time.time()}
        with self._lock:
            self.jobs.append(job)
            self._save()
        when_desc = self.describe_time(parsed["next"]) if not parsed["rule"] else f"{when_text.strip()} (next {self.describe_time(parsed['next'])})"
        if kind == "reminder":
            return f"Okay, I'll remind you {when_desc} to {job['text']}."
        return f"Okay, I'll run '{job['text']}' {when_desc}."

    def describe_time(self, when: datetime) -> str:
        now = self.clock()
        clock = when.strftime("%I:%M %p").lstrip("0")
        if when.date() == now.date():
            return f"at {clock} today"
        if when.date() == (now + timedelta(days=1)).date():
            return f"at {clock} tomorrow"
        return f"on {when.strftime('%A %d %b')} at {clock}"

    # ------------------------------------------------------------------ listing / cancelling
    def sorted_jobs(self) -> list[dict]:
        with self._lock:
            return sorted(self.jobs, key=lambda j: j["next"])

    def list_text(self) -> str:
        jobs = self.sorted_jobs()
        if not jobs:
            return "You have no reminders or scheduled commands."
        parts = []
        for i, j in enumerate(jobs, 1):
            when = self.describe_time(datetime.fromisoformat(j["next"]))
            repeat = f" ({j['when']})" if j.get("rule") else ""
            label = "Reminder" if j["kind"] == "reminder" else "Command"
            parts.append(f"{i}. {label}: {j['text']} — {when}{repeat}")
        return "\n".join(parts)

    def cancel(self, selector: str) -> str:
        sel = (selector or "").strip().lower()
        jobs = self.sorted_jobs()
        if not jobs:
            return "There's nothing scheduled."
        if sel in {"all", "everything", "all reminders", "all schedules"}:
            with self._lock:
                self.jobs = []
                self._save()
            return f"Cancelled all {len(jobs)} reminders and scheduled commands."
        target = None
        m = re.fullmatch(r"(?:number\s+)?(\d+)", sel)
        if m and 1 <= int(m.group(1)) <= len(jobs):
            target = jobs[int(m.group(1)) - 1]
        else:
            from rapidfuzz import fuzz
            best = max(jobs, key=lambda j: fuzz.partial_ratio(sel, j["text"].lower()))
            if fuzz.partial_ratio(sel, best["text"].lower()) >= 70:
                target = best
        if target is None:
            return f"I couldn't find a reminder matching '{selector}'."
        with self._lock:
            self.jobs = [j for j in self.jobs if j["id"] != target["id"]]
            self._save()
        return f"Cancelled: {target['text']}."

    # ------------------------------------------------------------------ running
    def tick(self) -> list[dict]:
        now = self.clock()
        due = []
        with self._lock:
            keep = []
            for job in self.jobs:
                if datetime.fromisoformat(job["next"]) <= now:
                    due.append(dict(job))
                    if job.get("rule"):
                        job["next"] = compute_next(job["rule"], now).isoformat(timespec="seconds")
                        keep.append(job)
                else:
                    keep.append(job)
            if due:
                self.jobs = keep
                self._save()
        for job in due:
            log.info(f"Scheduler: firing {job['kind']} '{job['text']}'")
            if self.fire:
                try:
                    self.fire(job)
                except Exception as e:
                    log.error(f"Scheduler: job failed: {e}")
        return due

    def start(self, interval: float = 5.0):
        if self._running:
            return
        self._running = True

        def loop():
            while self._running:
                self.tick()
                time.sleep(interval)

        self._thread = threading.Thread(target=loop, name="MXB-Scheduler", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
