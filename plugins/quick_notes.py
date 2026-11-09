"""
Example plugin: quick voice notes.

  "MXB, note that the SIH demo is on Friday"
  "MXB, take a note buy a USB hub"
  "MXB, read my notes"
Notes are appended to Documents/MXB Notes.md with a timestamp.
"""
import time
from pathlib import Path
from engine.skills import skill

NOTES = Path.home() / "Documents" / "MXB Notes.md"


@skill(name="quick_note",
       patterns=[r"^(?:note that|take a note(?: that)?|make a note(?: that)?|jot down)\s+(?P<target>.+)$"],
       description="Append a timestamped note to the user's MXB Notes file", target="note text")
def quick_note(target, ctx):
    if not target:
        return "What should I note down?"
    NOTES.parent.mkdir(parents=True, exist_ok=True)
    with open(NOTES, "a", encoding="utf-8") as f:
        f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} — {target}\n")
    return "Noted."


@skill(name="read_notes", patterns=[r"^(?:read|show)(?: me)? my (?:last |recent )?notes$"],
       description="Read the most recent quick notes", target="none")
def read_notes(target, ctx):
    if not NOTES.exists():
        return "You don't have any notes yet."
    lines = [l.strip("- \n") for l in NOTES.read_text(encoding="utf-8").splitlines() if l.strip()]
    recent = lines[-5:]
    return "Your latest notes: " + "; ".join(recent) if recent else "Your notes file is empty."
