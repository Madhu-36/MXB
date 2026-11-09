"""
Who MXB is and how it talks (config "persona").

Every reply the planner writes gets the same voice: short spoken sentences, the user's name now and
then (not every time), plain admissions when something failed, no "As an AI". The style is a
setting: "warm" (default), "crisp" (fewest words) or "playful" (a little humour when nothing is
wrong). The user can rename MXB's way of addressing them by voice: "call me S10".

It also notices the user's mood from what they say and how they repeat themselves:
- frustrated ("it's not working", "again", "useless", the same request twice in a row)
  -> one short sentence, apologise at most once, fix it or offer the next best option, no jokes
- in a hurry ("quick", "fast", "hurry") -> the shortest possible answer
Nothing about mood is stored; it only shapes the current reply.
"""
import random
import re
from datetime import datetime

STYLES = {
    "warm": "Friendly and encouraging, like a capable friend who is good with computers.",
    "crisp": "Brief and to the point. No small talk.",
    "playful": "Light and a little witty when things are going well; never joke when something failed.",
}

_FRUSTRATED = re.compile(
    r"\b(not working|doesn'?t work|didn'?t work|isn'?t working|useless|stupid|again|seriously|come on|"
    r"what the|wrong|still not|why (?:did|didn'?t|won'?t|can'?t) you|i (?:said|told you)|"
    r"listen to me|ugh|damn|wtf)\b|!!+", re.I)
_RUSHED = re.compile(r"\b(quick(?:ly)?|fast|hurry|asap|right now|immediately)\b", re.I)
_CALL_ME = re.compile(r"^(?:please\s+)?call me\s+([a-z0-9][\w .'-]{0,30}?)[.!]?$", re.I)


def detect_mood(text: str, recent_user_turns: list[str] | None = None) -> str:
    """'frustrated', 'rushed' or 'neutral' from the words and from repeating the same request."""
    t = (text or "").strip().lower()
    if _FRUSTRATED.search(t):
        return "frustrated"
    norm = re.sub(r"[^a-z0-9 ]", "", t)
    for prev in (recent_user_turns or [])[-2:]:
        if norm and re.sub(r"[^a-z0-9 ]", "", (prev or "").lower()) == norm:
            return "frustrated"            # asking for the same thing again means it didn't work
    if _RUSHED.search(t):
        return "rushed"
    return "neutral"


_NOT_NAMES = {"later", "back", "tomorrow", "tonight", "today", "in", "when", "at", "on", "a", "an", "the", "now",
              "soon", "after", "before", "once", "if", "please", "maybe", "again", "sometime", "anytime"}


def parse_call_me(text: str) -> str | None:
    """'call me S10' -> 'S10'; 'call me later' / 'call me back' / 'call me a cab' -> None."""
    m = _CALL_ME.match((text or "").strip())
    if not m:
        return None
    name = m.group(1).strip()
    if name.split()[0].lower() in _NOT_NAMES or len(name.split()) > 3:
        return None
    return name[:1].upper() + name[1:] if name.islower() else name


class Persona:
    def __init__(self, config: dict | None = None, rng=None):
        cfg = (config or {}).get("persona", {})
        self.name = cfg.get("name", "MXB")
        self.user_name = cfg.get("user_name", "")
        self.style = cfg.get("style", "warm") if cfg.get("style", "warm") in STYLES else "warm"
        self.rng = rng or random.Random()

    def prompt(self) -> str:
        """Lines for the planner's system prompt."""
        who = f" The user's name is {self.user_name}; use it occasionally, not in every reply." if self.user_name else ""
        return (f"Personality: you are {self.name}. {STYLES[self.style]}{who} Talk like a person: short spoken "
                "sentences, no markdown, no emojis, never say 'as an AI'. If something failed, say so plainly and "
                "say what you'll try next.")

    @staticmethod
    def mood_note(mood: str) -> str:
        if mood == "frustrated":
            return ("Tone for this reply: the user sounds frustrated. One short sentence. Apologise at most once. "
                    "Fix it or offer the next best option. No jokes.")
        if mood == "rushed":
            return "Tone for this reply: the user is in a hurry. Answer in as few words as possible."
        return ""

    def greeting(self, now: datetime | None = None) -> str:
        now = now or datetime.now()
        part = "Good morning" if now.hour < 12 else "Good afternoon" if now.hour < 17 else "Good evening"
        name = f", {self.user_name}" if self.user_name else ""
        if self.style == "crisp":
            return f"{part}{name}. Ready."
        options = [f"{part}{name}! What can I do for you?", f"{part}{name}. I'm here — what's next?",
                   f"Hey{name}! What are we working on?"]
        if self.style == "playful":
            options.append(f"{part}{name}! Your desktop and I are at your service.")
        return self.rng.choice(options)

    def identity(self) -> str:
        if self.style == "crisp":
            return f"I'm {self.name}, your desktop assistant. I run your apps, files, browser and settings by voice."
        return (f"I'm {self.name}, your desktop companion. I can open and control apps, handle files, browse, read "
                "your screen, take meeting notes, keep you focused and remind you of things — just ask.")

    def set_user_name(self, name: str) -> str:
        self.user_name = name
        return f"Got it, I'll call you {name}."
