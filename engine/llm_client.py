"""
MXB LLM Client — one place for every model call.

Order: NVIDIA Build cloud (if NVIDIA_API_KEY is set) -> local Ollama.
Supports JSON-mode planning and optional screenshots for vision models
(NVIDIA: OpenAI-style image_url content parts; Ollama: "images" field).
"""
import base64
import json
import re
import requests
from utils.credentials import CredentialsManager
from utils.logger import log


def parse_json_reply(raw: str) -> dict | None:
    """Resilient JSON extraction: fences, surrounding prose, truncated output, plain text."""
    if not raw:
        return None
    text = raw.strip()
    if text.startswith("```json"):
        text = text[7:]
    elif text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {"reply": str(data), "plan": []}
    except Exception:
        pass

    first, last = text.find("{"), text.rfind("}")
    if first != -1 and last > first:
        try:
            data = json.loads(text[first:last + 1])
            if isinstance(data, dict):
                return data
        except Exception:
            pass

    reply = ""
    reply_match = re.search(r'"reply"\s*:\s*"([^"]*)', text)
    if reply_match:
        reply = reply_match.group(1).strip()
    plan = []
    for action, target in re.findall(r'\{\s*"action"\s*:\s*"([^"]+)"(?:\s*,\s*"target"\s*:\s*"([^"]*)")?\s*\}', text):
        plan.append({"action": action, "target": target or ""})
    done = None
    done_match = re.search(r'"done"\s*:\s*(true|false)', text)
    if done_match:
        done = done_match.group(1) == "true"
    if reply or plan or done is not None:
        out = {"reply": reply, "plan": plan}
        if done is not None:
            out["done"] = done
        return out
    if text and not text.startswith("{"):
        return {"reply": text, "plan": []}
    return None


class LLMClient:
    def __init__(self, config: dict | None = None):
        cfg = (config or {}).get("llm", {}) if isinstance(config, dict) else {}
        self.nvidia_url = cfg.get("api_url", "https://integrate.api.nvidia.com/v1/chat/completions")
        self.nvidia_model = cfg.get("model", "meta/llama-3.1-8b-instruct")
        self.nvidia_vision_model = cfg.get("vision_model", "meta/llama-3.2-11b-vision-instruct")
        self.ollama_url = cfg.get("ollama_url", "http://localhost:11434/api/chat")
        self.local_model = cfg.get("local_model", "llama3.2:1b")
        self.local_vision_model = cfg.get("local_vision_model", "llama3.2-vision")
        self.max_tokens = int(cfg.get("max_tokens", 500))
        self.cloud_timeout = float(cfg.get("cloud_timeout_sec", 12))
        self.local_timeout = float(cfg.get("local_timeout_sec", 40))

    # ------------------------------------------------------------------ providers
    def _nvidia(self, system: str, user: str, max_tokens: int, json_mode: bool, image_png: bytes | None) -> str | None:
        key = CredentialsManager.get_nvidia_api_key()
        if not key:
            return None
        if image_png:
            b64 = base64.b64encode(image_png).decode("ascii")
            content = [
                {"type": "text", "text": user},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ]
            model = self.nvidia_vision_model
        else:
            content = user
            model = self.nvidia_model
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}],
            "temperature": 0.2,
            "max_tokens": max_tokens,
        }
        if json_mode and not image_png:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        resp = requests.post(self.nvidia_url, headers=headers, json=payload, timeout=self.cloud_timeout)
        if resp.status_code != 200:
            log.warning(f"LLM: NVIDIA returned {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()["choices"][0]["message"]["content"]

    def _ollama(self, system: str, user: str, max_tokens: int, json_mode: bool, image_png: bytes | None) -> str | None:
        message = {"role": "user", "content": user}
        model = self.local_model
        if image_png:
            message["images"] = [base64.b64encode(image_png).decode("ascii")]
            model = self.local_vision_model
        payload = {
            "model": model,
            "messages": [{"role": "system", "content": system}, message],
            "stream": False,
            "keep_alive": "2h",
            "options": {"num_predict": max_tokens, "num_ctx": 4096, "temperature": 0.1},
        }
        if json_mode:
            payload["format"] = "json"
        resp = requests.post(self.ollama_url, json=payload, timeout=self.local_timeout)
        if resp.status_code != 200:
            log.warning(f"LLM: Ollama returned {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json().get("message", {}).get("content", "")

    # ------------------------------------------------------------------ public API
    def chat(self, system: str, user: str, max_tokens: int | None = None, json_mode: bool = True,
             image_png: bytes | None = None) -> str | None:
        max_tokens = max_tokens or self.max_tokens
        for name, fn in (("NVIDIA", self._nvidia), ("Ollama", self._ollama)):
            try:
                out = fn(system, user, max_tokens, json_mode, image_png)
                if out:
                    return out
            except Exception as e:
                log.warning(f"LLM: {name} call failed: {e}")
        return None

    def chat_json(self, system: str, user: str, max_tokens: int | None = None,
                  image_png: bytes | None = None) -> dict | None:
        return parse_json_reply(self.chat(system, user, max_tokens, True, image_png) or "")
