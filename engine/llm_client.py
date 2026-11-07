"""
MXB LLM Client — one place for every model call.

Order: NVIDIA Build cloud (if NVIDIA_API_KEY is set) -> local Ollama.

Three calling styles:
- chat / chat_json      : classic request -> text / parsed JSON (JSON mode)
- plan_with_tools       : native OpenAI-style tool calling with a schema whose action
                          names are an enum -> far fewer malformed plans
- stream_chat           : token streaming (SSE / NDJSON) so MXB can start speaking the
                          reply while the rest of the plan is still being generated
Optional screenshots for vision models (NVIDIA image_url parts / Ollama "images").
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
    reply_match = re.search(r'"reply"\s*:\s*"((?:[^"\\]|\\.)*)', text)
    if reply_match:
        try:
            reply = json.loads(f'"{reply_match.group(1)}"').strip()
        except Exception:
            reply = reply_match.group(1).strip()
    plan = []
    for action, target in re.findall(r'\{\s*"action"\s*:\s*"([^"]+)"(?:\s*,\s*"target"\s*:\s*"([^"]*)")?[^{}]*\}', text):
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


def parse_tool_arguments(args) -> dict | None:
    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        return parse_json_reply(args)
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
        self.use_tool_calling = bool(cfg.get("use_tool_calling", True))
        self._tools_unsupported = {"nvidia": False, "ollama": False}

    # ------------------------------------------------------------------ message builders
    def _nvidia_messages(self, system: str, user: str, image_png: bytes | None):
        if image_png:
            b64 = base64.b64encode(image_png).decode("ascii")
            content = [{"type": "text", "text": user},
                       {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}]
            return [{"role": "system", "content": system}, {"role": "user", "content": content}], self.nvidia_vision_model
        return [{"role": "system", "content": system}, {"role": "user", "content": user}], self.nvidia_model

    def _ollama_messages(self, system: str, user: str, image_png: bytes | None):
        message = {"role": "user", "content": user}
        model = self.local_model
        if image_png:
            message["images"] = [base64.b64encode(image_png).decode("ascii")]
            model = self.local_vision_model
        return [{"role": "system", "content": system}, message], model

    @staticmethod
    def _headers(key: str) -> dict:
        return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    # ------------------------------------------------------------------ plain providers
    def _nvidia(self, system: str, user: str, max_tokens: int, json_mode: bool, image_png: bytes | None) -> str | None:
        key = CredentialsManager.get_nvidia_api_key()
        if not key:
            return None
        messages, model = self._nvidia_messages(system, user, image_png)
        payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens}
        if json_mode and not image_png:
            payload["response_format"] = {"type": "json_object"}
        resp = requests.post(self.nvidia_url, headers=self._headers(key), json=payload, timeout=self.cloud_timeout)
        if resp.status_code != 200:
            log.warning(f"LLM: NVIDIA returned {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json()["choices"][0]["message"]["content"]

    def _ollama(self, system: str, user: str, max_tokens: int, json_mode: bool, image_png: bytes | None) -> str | None:
        messages, model = self._ollama_messages(system, user, image_png)
        payload = {"model": model, "messages": messages, "stream": False, "keep_alive": "2h",
                   "options": {"num_predict": max_tokens, "num_ctx": 4096, "temperature": 0.1}}
        if json_mode:
            payload["format"] = "json"
        resp = requests.post(self.ollama_url, json=payload, timeout=self.local_timeout)
        if resp.status_code != 200:
            log.warning(f"LLM: Ollama returned {resp.status_code}: {resp.text[:200]}")
            return None
        return resp.json().get("message", {}).get("content", "")

    # ------------------------------------------------------------------ public: plain
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

    # ------------------------------------------------------------------ public: tool calling
    def plan_with_tools(self, system: str, user: str, tool: dict, max_tokens: int | None = None,
                        image_png: bytes | None = None) -> dict | None:
        """
        Native tool calling: the model must call `execute_plan` with schema-checked
        arguments. Returns the arguments dict, or None (caller falls back to JSON mode).
        """
        if not self.use_tool_calling:
            return None
        max_tokens = max_tokens or self.max_tokens
        name = tool["function"]["name"]

        key = CredentialsManager.get_nvidia_api_key()
        if key and not self._tools_unsupported["nvidia"]:
            try:
                messages, model = self._nvidia_messages(system, user, image_png)
                payload = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens,
                           "tools": [tool], "tool_choice": {"type": "function", "function": {"name": name}}}
                resp = requests.post(self.nvidia_url, headers=self._headers(key), json=payload, timeout=self.cloud_timeout)
                if resp.status_code == 200:
                    msg = resp.json()["choices"][0]["message"]
                    for call in msg.get("tool_calls") or []:
                        args = parse_tool_arguments(call.get("function", {}).get("arguments"))
                        if args is not None:
                            return args
                    if msg.get("content"):
                        return parse_json_reply(msg["content"])
                elif resp.status_code in (400, 422):
                    log.warning(f"LLM: NVIDIA model rejected tool calling ({resp.status_code}); using JSON mode from now on.")
                    self._tools_unsupported["nvidia"] = True
            except Exception as e:
                log.warning(f"LLM: NVIDIA tool call failed: {e}")

        if not self._tools_unsupported["ollama"]:
            try:
                messages, model = self._ollama_messages(system, user, image_png)
                payload = {"model": model, "messages": messages, "stream": False, "keep_alive": "2h", "tools": [tool],
                           "options": {"num_predict": max_tokens, "num_ctx": 4096, "temperature": 0.1}}
                resp = requests.post(self.ollama_url, json=payload, timeout=self.local_timeout)
                if resp.status_code == 200:
                    msg = resp.json().get("message", {})
                    for call in msg.get("tool_calls") or []:
                        args = parse_tool_arguments(call.get("function", {}).get("arguments"))
                        if args is not None:
                            return args
                    if msg.get("content"):
                        return parse_json_reply(msg["content"])
                elif resp.status_code == 400 and "does not support tools" in resp.text:
                    self._tools_unsupported["ollama"] = True
            except Exception as e:
                log.warning(f"LLM: Ollama tool call failed: {e}")
        return None

    # ------------------------------------------------------------------ public: streaming
    def stream_chat(self, system: str, user: str, on_delta=None, max_tokens: int | None = None,
                    json_mode: bool = True) -> str:
        """
        Streams tokens, calling on_delta(text) as they arrive. Returns the full text
        ("" if no provider answered).
        """
        max_tokens = max_tokens or self.max_tokens
        key = CredentialsManager.get_nvidia_api_key()
        if key:
            try:
                messages, model = self._nvidia_messages(system, user, None)
                payload = {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": max_tokens, "stream": True}
                if json_mode:
                    payload["response_format"] = {"type": "json_object"}
                with requests.post(self.nvidia_url, headers=self._headers(key), json=payload,
                                   timeout=self.cloud_timeout, stream=True) as resp:
                    if resp.status_code == 200:
                        return self._consume_sse(resp.iter_lines(decode_unicode=True), on_delta)
                    log.warning(f"LLM: NVIDIA stream returned {resp.status_code}")
            except Exception as e:
                log.warning(f"LLM: NVIDIA stream failed: {e}")
        try:
            messages, model = self._ollama_messages(system, user, None)
            payload = {"model": model, "messages": messages, "stream": True, "keep_alive": "2h",
                       "options": {"num_predict": max_tokens, "num_ctx": 4096, "temperature": 0.1}}
            if json_mode:
                payload["format"] = "json"
            with requests.post(self.ollama_url, json=payload, timeout=self.local_timeout, stream=True) as resp:
                if resp.status_code == 200:
                    return self._consume_ndjson(resp.iter_lines(decode_unicode=True), on_delta)
        except Exception as e:
            log.warning(f"LLM: Ollama stream failed: {e}")
        return ""

    @staticmethod
    def _consume_sse(lines, on_delta) -> str:
        parts = []
        for line in lines:
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            try:
                delta = json.loads(data)["choices"][0].get("delta", {}).get("content") or ""
            except Exception:
                continue
            if delta:
                parts.append(delta)
                if on_delta:
                    on_delta(delta)
        return "".join(parts)

    @staticmethod
    def _consume_ndjson(lines, on_delta) -> str:
        parts = []
        for line in lines:
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            delta = obj.get("message", {}).get("content") or ""
            if delta:
                parts.append(delta)
                if on_delta:
                    on_delta(delta)
            if obj.get("done"):
                break
        return "".join(parts)
