"""
Proactive companion: MXB speaks first when it has something worth saying.

- A morning briefing once a day (time, weather, today's calendar, unread email, reminders), at
  proactive.briefing_time or the first time you're at the PC after it.
- "Meeting in 10 minutes" from your calendar.
- "Battery at 15%, plug in" when it isn't charging.
Quiet hours (default 22:30-07:30) silence all of it except meeting alerts, which show without speech.
Each kind can be muted by voice ("stop the battery alerts"), and nothing repeats itself.

Calendar: your calendar's private iCal link (Google Calendar: Settings > your calendar > Integrate
calendar > "Secret address in iCal format"; Outlook: Publish calendar > ICS), or a local .ics file.
The link is a password, so it is kept in MXB's encrypted vault, not in config.json.
Email: IMAP with an app password (Gmail: turn on 2-step verification, then create one at
myaccount.google.com/apppasswords; Yahoo and iCloud have app passwords too), also in the vault.
Outlook.com / Hotmail / Live accept only OAuth sign-in since 16 September 2024, which MXB doesn't do yet.
Read-only: MXB peeks at sender and subject and never marks anything as read.

    python -m engine.proactive --setup       # asks for the calendar link and email, stores them
    python -m engine.proactive --briefing    # prints today's briefing
"""
import email.header
import email.utils
import imaplib
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from utils.logger import log

CALENDAR_KEY = "proactive_calendar_ics"
IMAP_PASSWORD_KEY = "proactive_imap_password"
KINDS = ("briefing", "meetings", "battery", "email")

IMAP_HOSTS = {
    "gmail.com": "imap.gmail.com", "googlemail.com": "imap.gmail.com",
    "yahoo.com": "imap.mail.yahoo.com", "yahoo.co.in": "imap.mail.yahoo.com", "ymail.com": "imap.mail.yahoo.com",
    "icloud.com": "imap.mail.me.com", "me.com": "imap.mail.me.com", "mac.com": "imap.mail.me.com",
    "zoho.com": "imap.zoho.com", "zohomail.in": "imap.zoho.in",
}
# Microsoft turned off password (basic) sign-in for these on 16 September 2024; app passwords are refused too.
OAUTH_ONLY_DOMAINS = ("outlook.com", "hotmail.com", "live.com", "msn.com", "outlook.in", "live.in", "hotmail.co.in")


def imap_host_for(address: str) -> str:
    """The IMAP server for well-known providers ('' when unknown, e.g. a college or company domain)."""
    return IMAP_HOSTS.get((address or "").rsplit("@", 1)[-1].strip().lower(), "")


def needs_oauth(address: str) -> bool:
    return (address or "").rsplit("@", 1)[-1].strip().lower() in OAUTH_ONLY_DOMAINS


@dataclass
class Event:
    title: str
    start: datetime
    end: datetime
    location: str = ""
    all_day: bool = False

    def when(self) -> str:
        return "all day" if self.all_day else self.start.strftime("%I:%M %p").lstrip("0")


def _local(value) -> tuple[datetime, bool]:
    """icalendar values (date, naive or aware datetime) -> (local naive datetime, all_day)."""
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            value = value.astimezone().replace(tzinfo=None)
        return value, False
    return datetime.combine(value, datetime.min.time()), True


class CalendarSource:
    def __init__(self, url_or_path: str, http_get=requests.get, cache_seconds: float = 900, clock=time.time):
        self.where = (url_or_path or "").strip()
        self.http_get = http_get
        self.cache_seconds = cache_seconds
        self.clock = clock
        self._cache: tuple[float, bytes] | None = None

    def _ics(self) -> bytes:
        now = self.clock()
        if self._cache and now - self._cache[0] < self.cache_seconds:
            return self._cache[1]
        if self.where.lower().startswith(("http://", "https://", "webcal://")):
            url = "https://" + self.where.split("://", 1)[1] if self.where.lower().startswith("webcal://") else self.where
            resp = self.http_get(url, timeout=15)
            resp.raise_for_status()
            data = resp.content
        else:
            data = Path(self.where).expanduser().read_bytes()
        self._cache = (now, data)
        return data

    def events(self, start: datetime, end: datetime) -> list[Event]:
        import icalendar
        import recurring_ical_events
        cal = icalendar.Calendar.from_ical(self._ics())
        out = []
        for comp in recurring_ical_events.of(cal).between(start, end):
            if str(comp.get("STATUS", "")).upper() == "CANCELLED":
                continue
            begin, all_day = _local(comp.decoded("DTSTART"))
            finish = _local(comp.decoded("DTEND"))[0] if comp.get("DTEND") else begin + timedelta(hours=1)
            out.append(Event(str(comp.get("SUMMARY", "Untitled")).strip(), begin, finish,
                             str(comp.get("LOCATION", "") or "").strip(), all_day))
        return sorted(out, key=lambda e: (not e.all_day, e.start))


def _decode(value: str) -> str:
    parts = []
    for text, charset in email.header.decode_header(value or ""):
        parts.append(text.decode(charset or "utf-8", errors="replace") if isinstance(text, bytes) else text)
    return " ".join("".join(parts).split())


class MailSource:
    def __init__(self, host: str, user: str, password_getter, port: int = 993, folder: str = "INBOX",
                 imap_factory=None, timeout: float = 15):
        self.host, self.user, self.port, self.folder = host, user, port, folder
        self.password_getter = password_getter
        # A hung mail server must not stall the briefing thread or a voice command.
        self.imap_factory = imap_factory or (lambda h, p: imaplib.IMAP4_SSL(h, p, timeout=timeout))

    def unread(self, limit: int = 3) -> tuple[int, list[tuple[str, str]]]:
        """(number of unread messages, [(sender, subject), ...] newest first). Read-only."""
        conn = self.imap_factory(self.host, self.port)
        try:
            conn.login(self.user, self.password_getter())
            conn.select(self.folder, readonly=True)
            status, data = conn.search(None, "UNSEEN")
            ids = data[0].split() if status == "OK" and data and data[0] else []
            latest = []
            for msg_id in reversed(ids[-limit:]):
                status, parts = conn.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                msg = email.message_from_bytes(parts[0][1])
                name, address = email.utils.parseaddr(_decode(msg.get("From", "")))
                latest.append((name or address, _decode(msg.get("Subject", "(no subject)"))))
            return len(ids), latest
        finally:
            try:
                conn.logout()
            except Exception:
                pass


def _parse_hm(text: str, default: str) -> tuple[int, int]:
    try:
        h, m = (text or default).split(":")
        return int(h) % 24, int(m) % 60
    except Exception:
        h, m = default.split(":")
        return int(h), int(m)


class ProactiveEngine:
    def __init__(self, config: dict | None = None, announce=None, calendar: CalendarSource | None = None,
                 mail: MailSource | None = None, reminders=None, weather=None, battery=None, user_name: str = "",
                 save_setting=None, clock=datetime.now, idle_seconds=None, busy=None):
        cfg = (config or {}).get("proactive", {})
        self.enabled = bool(cfg.get("enabled", True))
        self.briefing_at = _parse_hm(cfg.get("briefing_time", "08:30"), "08:30")
        quiet = str(cfg.get("quiet_hours", "22:30-07:30"))
        self.quiet_from = _parse_hm(quiet.split("-")[0], "22:30")
        self.quiet_to = _parse_hm(quiet.split("-")[-1], "07:30")
        self.meeting_minutes = int(cfg.get("meeting_alert_minutes", 10))
        self.battery_percent = int(cfg.get("battery_alert_percent", 15))
        self.muted = set(cfg.get("muted", []))
        self.announce = announce or (lambda text, speak=True: None)
        self.calendar, self.mail = calendar, mail
        self.reminders = reminders          # callable -> [(datetime, text)] for today
        self.weather = weather              # callable -> one-sentence summary
        self.battery = battery              # callable -> (percent, plugged) or None
        self.user_name = user_name
        self.save_setting = save_setting or (lambda key, value: None)
        self.clock = clock
        self.idle_seconds = idle_seconds or (lambda: 0.0)   # seconds since the last key/mouse input
        self.busy = busy or (lambda: False)                  # in a meeting or focus session: don't talk
        self._last_briefing: date | None = None
        self._alerted: set = set()
        self._battery_warned = False
        self._thread = None
        self._stop = threading.Event()

    # ------------------------------------------------------------------ rules
    def quiet(self, now: datetime) -> bool:
        cur = (now.hour, now.minute)
        if self.quiet_from <= self.quiet_to:
            return self.quiet_from <= cur < self.quiet_to
        return cur >= self.quiet_from or cur < self.quiet_to

    def _today(self, now: datetime) -> list[Event]:
        if not self.calendar:
            return []
        start = datetime.combine(now.date(), datetime.min.time())
        return self.calendar.events(start, start + timedelta(days=1))

    def tick(self) -> list[tuple[str, str]]:
        """One check (MXB runs it every minute). Returns what it said, as (kind, text)."""
        if not self.enabled:
            return []
        now = self.clock()
        said = []
        quiet = self.quiet(now)
        if "meetings" not in self.muted and self.calendar:
            try:
                for ev in self._today(now):
                    minutes = (ev.start - now).total_seconds() / 60
                    key = (ev.title, ev.start.isoformat())
                    if not ev.all_day and 0 <= minutes <= self.meeting_minutes and key not in self._alerted:
                        self._alerted.add(key)
                        text = f"{ev.title} starts in {max(1, round(minutes))} minutes" + \
                               (f", {ev.location}." if ev.location else ".")
                        said.append(("meetings", text))
                        self.announce(text, speak=not quiet and not self.busy())
            except Exception as e:
                log.warning(f"Proactive: calendar check failed: {e}")
        if quiet or self.busy():
            return said
        if "battery" not in self.muted and self.battery:
            reading = self.battery()
            if reading:
                percent, plugged = reading
                if percent <= self.battery_percent and not plugged and not self._battery_warned:
                    self._battery_warned = True
                    text = f"Battery is at {int(percent)}%. Plug in soon."
                    said.append(("battery", text))
                    self.announce(text)
                elif plugged or percent > self.battery_percent + 10:
                    self._battery_warned = False
        # Unasked, only with something to tell: no daily "your calendar isn't connected" nag.
        if "briefing" not in self.muted and (self.calendar or self.mail) and self._last_briefing != now.date() and \
                (now.hour, now.minute) >= self.briefing_at and self.idle_seconds() < 300:
            self._last_briefing = now.date()
            text = self.briefing(now, asked=False)
            said.append(("briefing", text))
            self.announce(text)
        return said

    # ------------------------------------------------------------------ the briefing
    def briefing(self, now: datetime | None = None, asked: bool = True) -> str:
        now = now or self.clock()
        part = "morning" if now.hour < 12 else "afternoon" if now.hour < 17 else "evening"
        name = f", {self.user_name}" if self.user_name else ""
        lines = [f"Good {part}{name}. It's {now.strftime('%I:%M %p').lstrip('0')}, {now.strftime('%A %d %B')}."]
        if self.weather:
            try:
                w = self.weather()
                if w:
                    lines.append(w if w.endswith(".") else w + ".")
            except Exception:
                pass
        if self.calendar or asked:
            lines.append(self.agenda(now))
        if self.mail and "email" not in self.muted:
            lines.append(self.email_summary())
        if self.reminders:
            try:
                items = self.reminders()
                if items:
                    lines.append("Reminders: " + "; ".join(f"{t:%I:%M %p} {text}".lstrip("0") for t, text in items) + ".")
            except Exception:
                pass
        return " ".join(line for line in lines if line)

    def agenda(self, now: datetime | None = None, day_offset: int = 0) -> str:
        now = now or self.clock()
        if not self.calendar:
            return "Your calendar isn't connected; say 'connect my calendar' to set it up."
        day = now + timedelta(days=day_offset)
        label = "Today" if day_offset == 0 else "Tomorrow" if day_offset == 1 else day.strftime("%A")
        try:
            events = self._today(day if day_offset else now)
        except Exception as e:
            log.warning(f"Proactive: calendar unavailable: {e}")
            return "I couldn't read your calendar just now."
        if day_offset == 0:
            events = [e for e in events if e.all_day or e.end > now]
        if not events:
            return f"{label} your calendar is clear." if day_offset else "Nothing else on your calendar today."
        shown = ", ".join(f"{e.when()} {e.title}" for e in events[:5])
        more = f", and {len(events) - 5} more" if len(events) > 5 else ""
        return f"{label}: {len(events)} event{'s' if len(events) != 1 else ''}: {shown}{more}."

    def email_summary(self) -> str:
        if not self.mail:
            return "Email isn't connected."
        try:
            count, latest = self.mail.unread()
        except Exception as e:
            log.warning(f"Proactive: email check failed: {e}")
            return "I couldn't check your email just now."
        if not count:
            return "No unread email."
        top = "; ".join(f"{sender}: {subject}" for sender, subject in latest)
        return f"{count} unread email{'s' if count != 1 else ''}. Latest: {top}."

    # ------------------------------------------------------------------ control
    def mute(self, kind: str) -> str:
        kind = kind.strip().lower()
        if kind in ("all", "everything"):
            self.enabled = False
            self.save_setting("enabled", False)
            return "Okay, I won't speak first anymore. Say 'turn on proactive alerts' to undo."
        if kind not in KINDS:
            return f"I can mute {', '.join(KINDS)} or all of it."
        self.muted.add(kind)
        self.save_setting("muted", sorted(self.muted))
        return f"Okay, no more {kind} alerts."

    def unmute(self, kind: str) -> str:
        kind = kind.strip().lower()
        if kind in ("all", "everything", ""):
            self.enabled, self.muted = True, set()
            self.save_setting("enabled", True)
            self.save_setting("muted", [])
            return "Proactive alerts are on: briefing, meetings, battery and email."
        self.muted.discard(kind)
        self.save_setting("muted", sorted(self.muted))
        return f"{kind.capitalize()} alerts are back on."

    def start(self, interval: float = 60.0):
        if self._thread is not None:
            return

        def loop():
            while not self._stop.wait(interval):
                try:
                    self.tick()
                except Exception as e:
                    log.warning(f"Proactive: {e}")
        self._thread = threading.Thread(target=loop, name="proactive", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()


# ---------------------------------------------------------------------- wiring helpers
def build_sources(config: dict, vault=None) -> tuple[CalendarSource | None, MailSource | None]:
    cfg = (config or {}).get("proactive", {})
    vault = vault or _vault()
    cal, mail = None, None
    link = cfg.get("calendar_file") or (vault.get_secret(CALENDAR_KEY) if vault else None)
    if link:
        cal = CalendarSource(link)
    host, user = cfg.get("imap_host"), cfg.get("imap_user")
    if host and user and vault and vault.has_secret(IMAP_PASSWORD_KEY):
        mail = MailSource(host, user, lambda: vault.get_secret(IMAP_PASSWORD_KEY), int(cfg.get("imap_port", 993)))
    return cal, mail


def _vault():
    try:
        from utils.vault import SecureVault
        return SecureVault()
    except Exception:
        return None


def battery_reading():
    try:
        import psutil
        b = psutil.sensors_battery()
        return (b.percent, bool(b.power_plugged)) if b else None
    except Exception:
        return None


def _setup_calendar(vault) -> None:
    import getpass
    link = getpass.getpass("Calendar's private iCal link (input hidden; Enter to skip): ").strip()
    if not link:
        return
    try:
        now = datetime.now()
        found = CalendarSource(link).events(now - timedelta(days=1), now + timedelta(days=30))
    except Exception as e:
        print(f"Couldn't read that calendar ({type(e).__name__}: {e}). Not saved; check the link and run setup again.")
        return
    vault.set_secret(CALENDAR_KEY, link)
    print(f"Calendar connected: {len(found)} event(s) in the next 30 days. The link is in the vault.")


def _setup_email(vault, config: dict, save_config) -> None:
    import getpass
    address = input("Email address for unread-mail summaries (Enter to skip): ").strip()
    if not address:
        return
    if needs_oauth(address):
        print("Outlook.com, Hotmail and Live accounts only allow OAuth sign-in since September 2024, and MXB "
              "doesn't support that yet. Skipping email; a Gmail, Yahoo or iCloud address works.")
        return
    default = imap_host_for(address)
    host = input(f"IMAP server [{default or 'e.g. imap.gmail.com'}]: ").strip() or default
    if not host:
        print("No IMAP server given; skipping email.")
        return
    if host == "imap.gmail.com":
        print("Gmail: use an app password from myaccount.google.com/apppasswords (needs 2-step verification), "
              "not your Google password.")
    password = getpass.getpass("App password (input hidden): ").strip()
    if not password:
        return
    try:
        count, _ = MailSource(host, address, lambda: password).unread(limit=1)
    except Exception as e:
        print(f"Couldn't sign in to {host} ({type(e).__name__}: {e}). Not saved; check the app password.")
        return
    vault.set_secret(IMAP_PASSWORD_KEY, password)
    config.setdefault("proactive", {}).update({"imap_host": host, "imap_user": address})
    save_config(config)
    print(f"Email connected: {count} unread. The app password is in the vault.")


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="MXB proactive companion")
    ap.add_argument("--setup", action="store_true", help="connect your calendar link and email")
    ap.add_argument("--briefing", action="store_true", help="print today's briefing")
    args = ap.parse_args(argv)
    from utils.paths import load_config, save_config
    config = load_config()
    vault = _vault()
    if args.setup:
        if vault is None:
            print("MXB's encrypted vault isn't available on this PC, so nothing can be stored safely. "
                  "Install the requirements (pip install -r requirements.txt) and try again.")
            return 1
        _setup_calendar(vault)
        _setup_email(vault, config, save_config)
    cal, mail = build_sources(config, vault)
    if args.briefing or args.setup:
        engine = ProactiveEngine(config, calendar=cal, mail=mail, battery=battery_reading)
        print(engine.briefing())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
