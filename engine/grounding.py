"""
Pixel grounding: find something on screen by looking at it.

"click the gear icon", "click the blue Submit button", "double-click the red folder": for icons,
games, canvas apps and anything without accessibility info, where UI Automation and OCR can't
help. A vision-language model looks at a screenshot and says where the thing is; MXB clicks there.

Providers (config "grounding"):
- "ollama": local and private. Default model qwen3-vl:4b (3.3 GB, `ollama pull qwen3-vl:4b`).
- "nvidia": cloud, your NVIDIA key. Default model qwen/qwen3.5-122b-a10b on build.nvidia.com.
- "openai": any OpenAI-compatible server (vLLM, LM Studio, OpenRouter...) via base_url + model,
            e.g. a UI-TARS-1.5 or GUI-Owl deployment.
- "auto":   Ollama when the model is pulled, otherwise NVIDIA when you have a key.

Coordinates: MXB asks for integers 0-1000 relative to the image, the native format of Qwen3-VL
and Qwen3.5. Models that answer in absolute pixels of the image they saw (Qwen2.5-VL, UI-TARS)
work with "coord_mode": "absolute" (MXB then sends sizes that are multiples of 28, so the
model's internal resize is a no-op), and are auto-detected when numbers exceed 1000.

Zoom pass: on wide screens MXB crops around the first guess and asks again, which recovers
small icons on 1440p/4K displays (the crop-and-refine trick from recent grounding work).
"""
import base64
import io
import json
import re
import time
from dataclasses import dataclass

import requests

from utils.logger import log


class GroundingError(Exception):
    """User-facing grounding problem (safe to speak)."""


@dataclass
class Grounding:
    x: int
    y: int
    box: tuple[int, int, int, int] | None
    provider: str
    model: str
    raw: str


SYSTEM = "You are a precise GUI grounding model. You locate user-interface elements in screenshots. Output JSON only."
PROMPT = ('Locate this on the screenshot: "{target}".\n'
          'Reply with JSON only: {{"found": true, "point_2d": [x, y], "bbox_2d": [x1, y1, x2, y2]}} where every '
          'coordinate is an integer from 0 to 1000, relative to the image width and height (0,0 is the top-left '
          'corner, 1000,1000 the bottom-right). If it is not visible, reply {{"found": false}}.')

DEFAULT_MODELS = {"ollama": "qwen3-vl:4b", "nvidia": "qwen/qwen3.5-122b-a10b", "openai": ""}
NVIDIA_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
_NUM = r"-?\d+(?:\.\d+)?"


# ---------------------------------------------------------------------------
# Parsing model output
# ---------------------------------------------------------------------------
def _json_candidates(text: str):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip(), flags=re.M)
    yield t
    for m in re.finditer(r"\{[^{}]*\}|\[[^\[\]]*(?:\[[^\[\]]*\][^\[\]]*)*\]", t):
        yield m.group(0)


def _nums(value) -> list[float] | None:
    if isinstance(value, (list, tuple)) and value and all(isinstance(v, (int, float)) for v in value):
        return [float(v) for v in value]
    if isinstance(value, str):
        found = re.findall(_NUM, value)
        return [float(v) for v in found] if found else None
    return None


def _from_obj(obj) -> dict | None:
    if isinstance(obj, list):
        if obj and all(isinstance(v, (int, float)) for v in obj) and len(obj) in (2, 4):
            return {"point": tuple(obj) if len(obj) == 2 else None, "box": tuple(obj) if len(obj) == 4 else None}
        for item in obj:
            got = _from_obj(item)
            if got:
                return got
        return None
    if not isinstance(obj, dict):
        return None
    if obj.get("found") is False:
        return {"point": None, "box": None, "found": False}
    point = box = None
    for key in ("point_2d", "point", "coordinate", "coordinates", "click", "position", "center"):
        vals = _nums(obj.get(key))
        if vals and len(vals) >= 2:
            point = (vals[0], vals[1])
            break
    for key in ("bbox_2d", "bbox", "box", "bounding_box"):
        vals = _nums(obj.get(key))
        if vals and len(vals) >= 4:
            box = tuple(vals[:4])
            break
    if point is None and isinstance(obj.get("x"), (int, float)) and isinstance(obj.get("y"), (int, float)):
        point = (float(obj["x"]), float(obj["y"]))
    if point is None and box is None:
        return None
    return {"point": point, "box": box}


def parse_location(text: str) -> dict | None:
    """
    Extracts a point and/or box from a grounding model's reply. Returns None when nothing
    parseable is present, {"found": False} when the model says it isn't there, or
    {"point": (x, y) | None, "box": (x1, y1, x2, y2) | None, "percent": bool}.
    """
    if not text or not text.strip():
        return None
    for cand in _json_candidates(text):
        try:
            got = _from_obj(json.loads(cand))
        except (json.JSONDecodeError, TypeError):
            continue
        if got:
            got.setdefault("percent", False)
            return got
    # Molmo-style <point x="12.5" y="40.1"> (percent of the image)
    m = re.search(rf'<point[^>]*\bx\d*="({_NUM})"[^>]*\by\d*="({_NUM})"', text)
    if m:
        return {"point": (float(m.group(1)), float(m.group(2))), "box": None, "percent": True}
    # UI-TARS: click(start_box='(x,y)') or <|box_start|>(x1,y1,x2,y2)<|box_end|>
    m = re.search(rf"\(\s*({_NUM})\s*,\s*({_NUM})\s*(?:,\s*({_NUM})\s*,\s*({_NUM})\s*)?\)", text)
    if m:
        vals = [float(v) for v in m.groups() if v is not None]
        if len(vals) == 4:
            return {"point": None, "box": tuple(vals), "percent": False}
        return {"point": (vals[0], vals[1]), "box": None, "percent": False}
    if re.search(r"\b(not (?:visible|found|present)|cannot find|can't find|no such)\b", text, re.I):
        return {"point": None, "box": None, "found": False}
    return None


def resolve_mode(loc: dict, mode: str) -> str:
    if mode and mode != "auto":
        return mode
    if loc.get("percent"):
        return "percent"
    values = [v for v in (loc.get("point") or ()) + (loc.get("box") or ())]
    if values and all(0 <= v <= 1.0 for v in values) and any(isinstance(v, float) and v % 1 for v in values):
        return "normalized"
    if any(v > 1000 for v in values):
        return "absolute"
    return "relative_1000"


def to_pixels(loc: dict, mode: str, width: int, height: int) -> tuple[tuple[int, int], tuple | None] | None:
    """Converts a parsed location to pixel coordinates in the image that was sent."""
    mode = resolve_mode(loc, mode)
    scale = {"relative_1000": (width / 1000.0, height / 1000.0), "normalized": (width, height),
             "percent": (width / 100.0, height / 100.0), "absolute": (1.0, 1.0)}.get(mode, (width / 1000.0, height / 1000.0))
    box = None
    if loc.get("box"):
        x1, y1, x2, y2 = loc["box"]
        box = (round(min(x1, x2) * scale[0]), round(min(y1, y2) * scale[1]),
               round(max(x1, x2) * scale[0]), round(max(y1, y2) * scale[1]))
    if loc.get("point"):
        px, py = round(loc["point"][0] * scale[0]), round(loc["point"][1] * scale[1])
    elif box:
        px, py = (box[0] + box[2]) // 2, (box[1] + box[3]) // 2
    else:
        return None
    if not (0 <= px < width and 0 <= py < height):
        return None
    return (px, py), box


# ---------------------------------------------------------------------------
# Grounder
# ---------------------------------------------------------------------------
class Grounder:
    def __init__(self, config: dict | None = None, http=None, key_provider=None):
        self.config = config or {}
        cfg = self.config.get("grounding", {}) or {}
        self.enabled = cfg.get("enabled", "auto")
        self.provider = (cfg.get("provider") or "auto").lower()
        self.models = {**DEFAULT_MODELS, **{k: v for k, v in (cfg.get("models") or {}).items() if v}}
        if cfg.get("model"):
            self.models[self.provider if self.provider != "auto" else "ollama"] = cfg["model"]
        self.coord_mode = (cfg.get("coord_mode") or "auto").lower()
        self.max_width = int(cfg.get("max_image_width", 1280))
        self.zoom = cfg.get("zoom_refine", "auto")
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.api_key_env = cfg.get("api_key_env", "OPENAI_API_KEY")
        llm = self.config.get("llm", {})
        self.ollama_base = re.sub(r"/api/(chat|generate)$", "", llm.get("ollama_url", "http://localhost:11434/api/chat"))
        self.timeout = float(cfg.get("timeout_sec", 60))
        self.http = http or requests
        self._key = key_provider
        self._available: tuple[float, str | None] | None = None

    # ------------------------------------------------------------------ provider selection
    def _nvidia_key(self) -> str | None:
        if self._key:
            return self._key()
        try:
            from utils.credentials import CredentialsManager
            return CredentialsManager.get_nvidia_api_key()
        except Exception:
            return None

    def _ollama_has(self, model: str) -> bool:
        try:
            r = self.http.get(f"{self.ollama_base}/api/tags", timeout=2)
            names = [m.get("name", "") for m in r.json().get("models", [])] if r.status_code == 200 else []
        except Exception:
            return False
        want = model if ":" in model else model + ":latest"
        return any(n == want or n == model for n in names)

    def pick_provider(self) -> str | None:
        """The provider to use now, or None when nothing is set up (cached for 5 minutes)."""
        if self.provider != "auto":
            return self.provider
        now = time.time()
        if self._available and now - self._available[0] < 300:
            return self._available[1]
        choice = None
        if self._ollama_has(self.models["ollama"]):
            choice = "ollama"
        elif self._nvidia_key():
            choice = "nvidia"
        elif self.base_url and self.models.get("openai"):
            choice = "openai"
        self._available = (now, choice)
        return choice

    def available(self) -> bool:
        if self.enabled is False or str(self.enabled).lower() == "false":
            return False
        return self.pick_provider() is not None

    # ------------------------------------------------------------------ requests
    @staticmethod
    def _encode(img, max_bytes: int = 170_000) -> tuple[str, str]:
        """JPEG small enough for hosted APIs' inline-image limits; returns (mime, base64)."""
        rgb = img.convert("RGB")
        for quality in (85, 70, 55):
            buf = io.BytesIO()
            rgb.save(buf, format="JPEG", quality=quality)
            if buf.tell() <= max_bytes:
                break
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode("ascii")

    def _ask(self, provider: str, prompt: str, img) -> str:
        model = self.models.get(provider) or ""
        mime, b64 = self._encode(img)
        if provider == "ollama":
            body = {"model": model, "stream": False, "format": "json", "options": {"temperature": 0},
                    "messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": prompt, "images": [b64]}]}
            r = self.http.post(f"{self.ollama_base}/api/chat", json=body, timeout=self.timeout)
            if r.status_code != 200:
                raise GroundingError(f"Ollama answered {r.status_code}. Is '{model}' pulled? (ollama pull {model})")
            return (r.json().get("message") or {}).get("content", "")
        if provider in ("nvidia", "openai"):
            if provider == "nvidia":
                url, key = NVIDIA_URL, self._nvidia_key()
            else:
                import os
                url, key = f"{self.base_url}/chat/completions", os.environ.get(self.api_key_env, "")
            if not key and provider == "nvidia":
                raise GroundingError("Visual clicking with NVIDIA needs your NVIDIA API key.")
            body = {"model": model, "temperature": 0, "max_tokens": 300,
                    "chat_template_kwargs": {"thinking": False, "enable_thinking": False},
                    "messages": [{"role": "system", "content": SYSTEM},
                                 {"role": "user", "content": [
                                     {"type": "text", "text": prompt},
                                     {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}]}]}
            headers = {"Authorization": f"Bearer {key}", "Accept": "application/json"} if key else {}
            r = self.http.post(url, json=body, headers=headers, timeout=self.timeout)
            if r.status_code != 200:
                raise GroundingError(f"The vision model answered {r.status_code}: {str(getattr(r, 'text', ''))[:120]}")
            msg = (r.json().get("choices") or [{}])[0].get("message") or {}
            return msg.get("content") or ""
        raise GroundingError(f"Unknown grounding provider '{provider}'.")

    def _prepare(self, img, mode: str):
        w, h = img.size
        ratio = min(1.0, self.max_width / float(w))
        nw, nh = max(1, round(w * ratio)), max(1, round(h * ratio))
        if mode == "absolute":   # match Qwen2.5-VL / UI-TARS smart_resize so absolute pixels map exactly
            nw, nh = max(28, round(nw / 28) * 28), max(28, round(nh / 28) * 28)
        return (img.resize((nw, nh)) if (nw, nh) != (w, h) else img), nw / float(w), nh / float(h)

    def _locate_once(self, provider: str, target: str, img):
        sent, sx, sy = self._prepare(img, self.coord_mode)
        raw = self._ask(provider, PROMPT.format(target=target.replace('"', "'")), sent)
        loc = parse_location(raw)
        if not loc or loc.get("found") is False:
            return None, raw
        px = to_pixels(loc, self.coord_mode, *sent.size)
        if px is None:
            return None, raw
        (x, y), box = px
        to_img = lambda vx, vy: (round(vx / sx), round(vy / sy))  # noqa: E731
        ix, iy = to_img(x, y)
        ibox = (*to_img(box[0], box[1]), *to_img(box[2], box[3])) if box else None
        return (ix, iy, ibox), raw

    def _zoom_wanted(self, img) -> bool:
        z = str(self.zoom).lower()
        if z in ("false", "off", "never"):
            return False
        if z in ("true", "on", "always"):
            return True
        return img.size[0] > 1600

    def locate(self, target: str, img, offset: tuple[int, int] = (0, 0)) -> Grounding | None:
        """Where `target` is in the screenshot `img`, in screen pixels (img pixel + offset)."""
        target = (target or "").strip()
        if not target:
            raise GroundingError("What should I look for?")
        provider = self.pick_provider()
        if provider is None:
            raise GroundingError("Visual clicking needs a vision model: run 'ollama pull qwen3-vl:4b' "
                                 "or add your NVIDIA API key.")
        hit, raw = self._locate_once(provider, target, img)
        if hit is None:
            return None
        x, y, box = hit
        if self._zoom_wanted(img):
            half = max(160, int(img.size[0] * 0.18))
            x0, y0 = max(0, x - half), max(0, y - half)
            x1, y1 = min(img.size[0], x + half), min(img.size[1], y + half)
            try:
                crop_hit, crop_raw = self._locate_once(provider, target, img.crop((x0, y0, x1, y1)))
                if crop_hit is not None:
                    cx, cy, cbox = crop_hit
                    x, y = x0 + cx, y0 + cy
                    box = (cbox[0] + x0, cbox[1] + y0, cbox[2] + x0, cbox[3] + y0) if cbox else box
                    raw = crop_raw
            except GroundingError as e:
                log.info(f"Grounding: zoom pass skipped ({e})")
        ox, oy = offset
        box = (box[0] + ox, box[1] + oy, box[2] + ox, box[3] + oy) if box else None
        return Grounding(x + ox, y + oy, box, provider, self.models.get(provider, ""), raw)


def where_on_screen(x: int, y: int, width: int, height: int) -> str:
    """'top right', 'center', 'bottom left'... for spoken answers."""
    col = "left" if x < width / 3 else ("right" if x > 2 * width / 3 else "")
    row = "top" if y < height / 3 else ("bottom" if y > 2 * height / 3 else "")
    return " ".join(p for p in (row, col) if p) or "center"
