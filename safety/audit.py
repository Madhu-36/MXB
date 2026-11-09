"""
Audit log: every action MXB takes, blocks or is refused, in an append-only JSONL file.

    {"t": 1731000000.0, "source": "voice", "action": "delete_file", "target": "...",
     "decision": "cancelled", "result": "...", "flags": []}

- Lets you answer "what did you do while I was away?" ("MXB, show the audit log").
- Secrets are redacted: vault values, password-like text, long digit runs (OTP/card/account numbers).
- Rotates at 5 MB, keeping 3 old files. Stored locally in the MXB data folder.
"""
import json
import re
import threading
import time
from pathlib import Path
from utils.paths import data_file

# 6+ digits, spaces/hyphens allowed between them: OTPs, phone, card and account numbers.
_DIGITS = re.compile(r"\d(?:[\s-]?\d){5,}")
# A keyword followed by a value: "password: x", "pin=1234", "otp 4829", "password is x".
# Whole words only, and a separator is required, so "shopping list" and "secret.txt" stay readable.
_SECRETY = re.compile(r"(?i)\b(password|passwd|pwd|passcode|otp|pin|cvv|token|api[_ -]?key|secret)\b"
                      r"(?:\s*[:=]\s*|\s+is\s+|\s+)\S+")
REDACT_ALL = {"vault_get", "vault_store"}


def redact(text: str) -> str:
    text = _SECRETY.sub(lambda m: m.group(1) + " [redacted]", str(text or ""))
    return _DIGITS.sub("[number redacted]", text)


class AuditLog:
    def __init__(self, path: str | Path | None = None, max_bytes: int = 5 * 1024 * 1024, keep: int = 3):
        self.path = Path(path) if path else data_file("audit.log.jsonl")
        self.max_bytes = max_bytes
        self.keep = keep
        self._lock = threading.Lock()

    def _rotate(self):
        try:
            if not self.path.exists() or self.path.stat().st_size < self.max_bytes:
                return
            for i in range(self.keep - 1, 0, -1):
                older = self.path.with_name(f"{self.path.name}.{i}")
                if older.exists():
                    older.replace(self.path.with_name(f"{self.path.name}.{i + 1}"))
            self.path.replace(self.path.with_name(f"{self.path.name}.1"))
        except OSError:
            pass

    def record(self, action: str, target: str = "", result: str = "", source: str = "local",
               decision: str = "executed", flags: list[str] | None = None):
        if action in REDACT_ALL:
            target_r, result_r = "[redacted]", "[redacted]"
        else:
            target_r, result_r = redact(target)[:300], redact(result)[:300]
        entry = {"t": round(time.time(), 3), "source": source, "action": action, "target": target_r,
                 "decision": decision, "result": result_r, "flags": flags or []}
        line = json.dumps(entry, ensure_ascii=False)
        with self._lock:
            self._rotate()
            try:
                with open(self.path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
            except OSError:
                pass

    def recent(self, limit: int = 20, since: float | None = None) -> list[dict]:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        out = []
        for line in reversed(lines):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if since is not None and entry.get("t", 0) < since:
                break
            out.append(entry)
            if len(out) >= limit:
                break
        return list(reversed(out))

    def summary_text(self, limit: int = 12, hours: float | None = None) -> str:
        since = time.time() - hours * 3600 if hours else None
        entries = [e for e in self.recent(limit=200, since=since) if e["action"] not in ("wait", "conversation", "audit_log")]
        if not entries:
            return "I haven't done anything yet" + (f" in the last {hours:g} hours." if hours else ".")
        entries = entries[-limit:]
        blocked = [e for e in entries if e["decision"] in ("blocked", "cancelled")]
        parts = []
        for e in entries:
            when = time.strftime("%H:%M", time.localtime(e["t"]))
            mark = {"blocked": " [BLOCKED]", "cancelled": " [cancelled]"}.get(e["decision"], "")
            target = f" {e['target'][:40]}" if e["target"] else ""
            parts.append(f"{when} {e['source']}: {e['action']}{target}{mark}")
        head = f"Last {len(entries)} actions"
        if blocked:
            head += f" ({len(blocked)} blocked or cancelled)"
        return head + ":\n" + "\n".join(parts)


_shared: AuditLog | None = None


def get_audit() -> AuditLog:
    global _shared
    if _shared is None:
        _shared = AuditLog()
    return _shared
