"""
Indian-language voice and text: speak or type in Kannada, Hindi, Telugu, Tamil, Malayalam,
Marathi, Bengali or Gujarati (native script, romanized, or mixed with English) and MXB answers
in the same language.

How it works:
1. Which language: the voice pipeline reports the spoken language (Sarvam or Whisper detect
   it); typed text is recognized by its script; romanized text ("notepad open maadi") by marker
   words when voice.language is set to that language.
2. MXB translates the command to English for its router and planner (LLM, cached), so every
   feature works in every language without separate rules.
3. The planner writes its reply directly in your language; English action results are
   translated before they are shown or spoken.
4. Speech uses a neural voice for that language (edge-tts: kn-IN-SapnaNeural, hi-IN-SwaraNeural...).

Safety words never wait for an LLM: stop / yes / no are matched locally in every language.
"""
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass

from utils.logger import log


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native: str
    block: tuple[int, int] | None
    voices: tuple[str, str]           # (female, male) edge-tts neural voices

    @property
    def locale(self) -> str:          # Sarvam / BCP-47 style
        return f"{self.code}-IN"


LANGUAGES: dict[str, Language] = {
    "en": Language("en", "English", "English", None, ("en-IN-NeerjaNeural", "en-IN-PrabhatNeural")),
    "hi": Language("hi", "Hindi", "हिन्दी", (0x0900, 0x097F), ("hi-IN-SwaraNeural", "hi-IN-MadhurNeural")),
    "mr": Language("mr", "Marathi", "मराठी", (0x0900, 0x097F), ("mr-IN-AarohiNeural", "mr-IN-ManoharNeural")),
    "bn": Language("bn", "Bengali", "বাংলা", (0x0980, 0x09FF), ("bn-IN-TanishaaNeural", "bn-IN-BashkarNeural")),
    "gu": Language("gu", "Gujarati", "ગુજરાતી", (0x0A80, 0x0AFF), ("gu-IN-DhwaniNeural", "gu-IN-NiranjanNeural")),
    "ta": Language("ta", "Tamil", "தமிழ்", (0x0B80, 0x0BFF), ("ta-IN-PallaviNeural", "ta-IN-ValluvarNeural")),
    "te": Language("te", "Telugu", "తెలుగు", (0x0C00, 0x0C7F), ("te-IN-ShrutiNeural", "te-IN-MohanNeural")),
    "kn": Language("kn", "Kannada", "ಕನ್ನಡ", (0x0C80, 0x0CFF), ("kn-IN-SapnaNeural", "kn-IN-GaganNeural")),
    "ml": Language("ml", "Malayalam", "മലയാളം", (0x0D00, 0x0D7F), ("ml-IN-SobhanaNeural", "ml-IN-MidhunNeural")),
}

NAME_TO_CODE = {"auto": "auto", "automatic": "auto", "any": "auto"}
for _lang in LANGUAGES.values():
    NAME_TO_CODE[_lang.code] = _lang.code
    NAME_TO_CODE[_lang.name.lower()] = _lang.code
    NAME_TO_CODE[_lang.native] = _lang.code
NAME_TO_CODE.update({"bangla": "bn", "kannad": "kn", "hindhi": "hi", "telgu": "te", "tamizh": "ta"})

# Instant safety words (native script and common romanizations).
STOP_WORDS = {
    "kn": {"ನಿಲ್ಲಿಸು", "ನಿಲ್ಲಿಸಿ", "ನಿಲ್ಲು", "ಸ್ಟಾಪ್", "nillisu", "nillisi", "nillu"},
    "hi": {"रुको", "रुकिए", "रुक जाओ", "बंद करो", "बस करो", "स्टॉप", "ठहरो", "ruko", "rukiye", "ruk jao", "band karo", "bas karo"},
    "mr": {"थांब", "थांबा", "बंद कर", "thamb", "thamba", "thaamba"},
    "te": {"ఆపు", "ఆపండి", "స్టాప్", "aapu", "apu", "aapandi"},
    "ta": {"நிறுத்து", "நிறுத்துங்கள்", "ஸ்டாப்", "niruthu", "nirutthu", "niruthunga"},
    "ml": {"നിർത്തൂ", "നിർത്ത്", "നിർത്തുക", "സ്റ്റോപ്പ്", "nirthu", "nirthoo"},
    "bn": {"থামো", "থামুন", "বন্ধ করো", "স্টপ", "thamo", "thamun"},
    "gu": {"રોકો", "બંધ કરો", "સ્ટોપ", "roko", "bandh karo"},
}
YES_WORDS = {
    "kn": {"ಹೌದು", "ಸರಿ", "ಹೂಂ", "ಆಯ್ತು", "houdu", "haudu", "aaytu", "aytu", "sari"},
    "hi": {"हाँ", "हां", "हा", "जी", "जी हाँ", "जी हां", "ठीक है", "कर दो", "haan", "haa", "han", "ji", "ji haan",
           "theek hai", "thik hai", "kar do"},
    "mr": {"हो", "होय", "ठीक आहे", "ho", "hoy", "theek aahe"},
    "te": {"అవును", "సరే", "ఓకే", "avunu", "sare"},
    "ta": {"ஆம்", "ஆமா", "சரி", "aam", "aama"},
    "ml": {"അതെ", "ശരി", "ഉവ്വ്", "athe", "shari", "uvvu"},
    "bn": {"হ্যাঁ", "হাঁ", "ঠিক আছে", "hyan", "thik ache"},
    "gu": {"હા", "હાં", "બરાબર", "ઠીક છે", "barabar", "thik chhe"},
}
NO_WORDS = {
    "kn": {"ಬೇಡ", "ಬೇಡಾ", "ಇಲ್ಲ", "beda", "bedaa", "illa"},
    "hi": {"नहीं", "नही", "ना", "मत करो", "रहने दो", "nahi", "nahin", "mat karo", "rehne do"},
    "mr": {"नाही", "नको", "naahi", "nako"},
    "te": {"వద్దు", "కాదు", "లేదు", "vaddu", "kaadu", "ledu"},
    "ta": {"வேண்டாம்", "வேணாம்", "இல்லை", "vendaam", "venaam", "illai"},
    "ml": {"വേണ്ട", "ഇല്ല", "venda"},
    "bn": {"না", "na"},
    "gu": {"ના", "નહીં"},
}
# "MXB" as Indian-language speech recognizers tend to spell it (spaces/ZWNJ are stripped first).
WAKE_VARIANTS = {"ಎಂಎಕ್ಸ್ಬಿ", "ಎಮ್ಎಕ್ಸ್ಬಿ", "एमएक्सबी", "ఎంఎక్స్బి", "ఎమ్ఎక్స్బి", "எம்எக்ஸ்பி", "എംഎക്സ്ബി",
                 "এমএক্সবি", "એમએક્સબી"}
# Romanized command words that only make sense in that language (used when voice.language is set).
ROMAN_MARKERS = {
    "kn": {"maadi", "madi", "maadu", "maadri", "beku", "thegi", "tegi", "thege", "haaku", "haku", "nodu", "kodi",
           "swalpa", "yenu", "enu", "ide", "idhe", "muchu", "mucchu", "hogu", "baa"},
    "hi": {"kholo", "khol", "karo", "kardo", "kar", "chalao", "chala", "dikhao", "batao", "bataiye", "kya", "hai",
           "mujhe", "chahiye", "banao", "likho", "bhejo", "kijiye", "karna", "krdo", "bandh"},
    "te": {"cheyyi", "cheyandi", "cheyu", "teruvu", "teravu", "moosey", "moosi", "kavali", "chupinchu", "enti",
           "undi", "cheppu", "pettu", "tiyyi"},
    "ta": {"pannu", "pannunga", "thira", "thirakka", "mudu", "moodu", "venum", "kaattu", "sollu", "enna", "irukku",
           "podu"},
    "ml": {"cheyyu", "thurakku", "thurakkuka", "adakku", "kaanikku", "parayu", "enthu", "venam", "aakku"},
    "mr": {"kara", "ughad", "ughada", "dakhav", "dakhva", "saanga", "pahije"},
    "bn": {"koro", "dekhao", "bolo", "chai", "ache"},
    "gu": {"karo", "batavo", "kaho", "joie"},
}

_INDIC_KEEP = re.compile(r"[^a-z0-9\sऀ-ൿ]")
_local = threading.local()
_preferred = {"language": None}   # runtime override set by "speak in kannada"


# ---------------------------------------------------------------------------
# Detection and safety words
# ---------------------------------------------------------------------------
def normalize(text: str) -> str:
    """Lowercase, drop punctuation/danda/zero-width joiners, keep Indian scripts, squeeze spaces."""
    t = (text or "").lower().replace("‌", "").replace("‍", "").replace("।", " ").replace("॥", " ")
    return re.sub(r"\s+", " ", _INDIC_KEEP.sub(" ", t)).strip()


def script_language(text: str, devanagari: str = "hi") -> str | None:
    """Language of the dominant Indian script in the text, or None (Latin, numbers, mixed)."""
    counts: dict[str, int] = {}
    total = 0
    for ch in text or "":
        if ch.isspace() or not (ch.isalnum() or 0x0900 <= ord(ch) <= 0x0D7F):
            continue
        total += 1
        cp = ord(ch)
        for code, lang in LANGUAGES.items():
            if lang.block and lang.block[0] <= cp <= lang.block[1] and code != "mr":
                counts[code] = counts.get(code, 0) + 1
                break
    if not counts:
        return None
    code, n = max(counts.items(), key=lambda kv: kv[1])
    if n < 2 or n / max(total, 1) < 0.25:
        return None
    return devanagari if code == "hi" and devanagari in ("hi", "mr") else code


def looks_romanized(text: str, code: str) -> bool:
    words = set(normalize(text).split())
    return bool(words & ROMAN_MARKERS.get(code, set()))


def _phrases(table: dict[str, set[str]]) -> set[str]:
    return {normalize(p) for words in table.values() for p in words}


_STOP = _phrases(STOP_WORDS)
_YES = _phrases(YES_WORDS)
_NO = _phrases(NO_WORDS)


def is_stop(text: str) -> bool:
    t = normalize(text)
    t = re.sub(r"^(?:mxb\s+)|(?:\s+mxb)$", "", t)
    return t in _STOP


def classify_answer(text: str) -> bool | None:
    """True/False for an Indian-language yes/no (whole short answer), None otherwise."""
    t = normalize(text)
    t = re.sub(r"^(?:mxb\s+)|(?:\s+mxb)$", "", t)
    if not t or len(t.split()) > 4:
        return None
    if t in _NO:
        return False
    if t in _YES:
        return True
    words = t.split()
    has_no = any(w in _NO for w in words)
    has_yes = any(w in _YES for w in words)
    if has_no and not has_yes:
        return False
    if has_yes and not has_no:
        return True
    return None


def code_for(name: str) -> str | None:
    """'kannada' / 'ಕನ್ನಡ' / 'kn' / 'kn-IN' -> 'kn'; 'auto'; None if unknown."""
    t = (name or "").strip().lower()
    t = re.sub(r"[-_](in|india)$", "", t)
    return NAME_TO_CODE.get(t) or NAME_TO_CODE.get((name or "").strip())


def voice_for(text: str, default_voice: str, gender: str = "female", devanagari: str = "hi") -> str:
    """The edge-tts voice for the text's script (Indian language), else the configured voice."""
    code = script_language(text, devanagari)
    if not code:
        return default_voice
    female, male = LANGUAGES[code].voices
    return male if (gender or "").lower().startswith("m") else female


# ---------------------------------------------------------------------------
# Reply language for the current command (thread-local: each bus worker has its own)
# ---------------------------------------------------------------------------
def set_reply_language(code: str | None):
    _local.language = code if code and code != "en" else None


def reply_language() -> str | None:
    return getattr(_local, "language", None)


def language_instruction() -> str:
    code = reply_language()
    if not code or code not in LANGUAGES:
        return ""
    lang = LANGUAGES[code]
    return (f"\nReply language: write the \"reply\" in {lang.name} ({lang.native} script), short and natural. "
            "Keep app names, file names, website names and numbers exactly as they are. Plan targets stay in English.")


def set_preferred_language(code: str | None):
    _preferred["language"] = code


def preferred_language(config: dict | None = None) -> str:
    if _preferred["language"]:
        return _preferred["language"]
    return (((config or {}).get("voice") or {}).get("language") or "en").lower()


# ---------------------------------------------------------------------------
# Translation bridge
# ---------------------------------------------------------------------------
class IndicBridge:
    def __init__(self, config: dict | None = None, llm_getter=None, cache_size: int = 512):
        self.config = config or {}
        vcfg = self.config.get("voice", {}) or {}
        self.gender = vcfg.get("indic_voice_gender", "female")
        self.devanagari = "mr" if (vcfg.get("language") or "").lower() == "mr" else "hi"
        self._llm_getter = llm_getter
        self._cache: OrderedDict = OrderedDict()
        self._cache_size = cache_size
        self._lock = threading.Lock()

    @property
    def language(self) -> str:
        return preferred_language(self.config)

    def detect(self, text: str, hint: str | None = None) -> str | None:
        """Indian language of a command, or None for English."""
        if hint and hint != "en" and hint in LANGUAGES:
            return hint
        code = script_language(text, "mr" if self.language == "mr" else self.devanagari)
        if code:
            return code
        pref = self.language
        if pref in LANGUAGES and pref != "en" and looks_romanized(text, pref):
            return pref
        return None

    def _llm(self):
        try:
            return self._llm_getter() if self._llm_getter else None
        except Exception:
            return None

    def _cached(self, key, make):
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        value = make()
        if value:
            with self._lock:
                self._cache[key] = value
                while len(self._cache) > self._cache_size:
                    self._cache.popitem(last=False)
        return value

    def _translate(self, system: str, text: str, max_tokens: int = 200) -> str | None:
        llm = self._llm()
        if llm is None:
            return None
        try:
            out = llm.chat(system, text, max_tokens=max_tokens, json_mode=False)
        except Exception as e:
            log.warning(f"Indic: translation failed: {e}")
            return None
        if not isinstance(out, str):
            return None
        out = out.strip().strip('"').strip()
        return out or None

    def to_english(self, text: str, code: str) -> str:
        """Command in an Indian language -> English (falls back to the original text)."""
        if not code or code == "en" or code not in LANGUAGES:
            return text
        lang = LANGUAGES[code]
        system = (f"You translate commands spoken to a Windows desktop assistant into English. The input is {lang.name}, "
                  "possibly romanized or mixed with English. Output ONLY the English command: no quotes, no notes. "
                  "Keep app names, website names, file names, numbers and English words exactly as they are. "
                  "Translate questions as questions.")
        return self._cached(("en", text), lambda: self._translate(system, text, 120)) or text

    def from_english(self, text: str, code: str | None) -> str:
        """English reply -> the user's language (text already in that script passes through)."""
        if not text or not code or code == "en" or code not in LANGUAGES:
            return text
        if script_language(text, "mr" if code == "mr" else "hi") == code:
            return text
        lang = LANGUAGES[code]
        system = (f"Translate the desktop assistant's reply into {lang.name} using {lang.native} script, natural and "
                  "short. Keep app names, file names, URLs, numbers and code unchanged. Output only the translation.")
        return self._cached((code, text), lambda: self._translate(system, text, 300)) or text

    def describe(self, code: str) -> str:
        lang = LANGUAGES.get(code)
        return f"{lang.name} ({lang.native})" if lang else code


# ---------------------------------------------------------------------------
# Sarvam speech-to-text (cloud; best accuracy for Indian languages and code-mixing)
# ---------------------------------------------------------------------------
class SarvamSTT:
    URL = "https://api.sarvam.ai/speech-to-text"

    def __init__(self, api_key: str, model: str = "saaras:v3", mode: str = "translate", http=None, timeout: float = 10):
        import requests
        self.api_key = api_key
        self.model = model
        self.mode = mode
        self.http = http or requests
        self.timeout = timeout

    def transcribe(self, wav_bytes: bytes, language: str = "auto") -> tuple[str, str | None]:
        """
        Returns (text, language_code). In "translate" mode the text is English and the code is the
        language that was spoken ("kn", "hi", ... or None for English).
        """
        lang_code = "unknown" if language in (None, "", "auto") else (
            LANGUAGES[language].locale if language in LANGUAGES else language)
        data = {"model": self.model, "language_code": lang_code}
        if self.model.startswith("saaras:v3"):
            data["mode"] = self.mode
        r = self.http.post(self.URL, headers={"api-subscription-key": self.api_key},
                           files={"file": ("speech.wav", wav_bytes, "audio/wav")}, data=data, timeout=self.timeout)
        if r.status_code != 200:
            raise RuntimeError(f"Sarvam STT answered {r.status_code}: {str(getattr(r, 'text', ''))[:150]}")
        body = r.json()
        text = (body.get("transcript") or "").strip()
        code = code_for(body.get("language_code") or "")
        return text, (code if code and code not in ("en", "auto") else None)
