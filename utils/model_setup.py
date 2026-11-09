"""
Pick, download and switch MXB's local planner model, and prove the switch with numbers.

Why: on a real laptop MXB shipped with llama3.2:1b, which timed out and couldn't plan multi-step
requests. Current guidance for the smallest local model that reliably drives tools is the ~4B class
(Qwen3-4B-Instruct-2507, Phi-4-mini, Gemma 4 E4B) with grammar-constrained output, which MXB now uses.

    python -m utils.model_setup                 # show the recommendation for this PC
    python -m utils.model_setup --pull          # download it through Ollama
    python -m utils.model_setup --pull --compare --switch
        # download, run the brain benchmark on the current and the new model (no actions are
        # executed), and switch config.json only if the new model scores at least as well.

Everything goes through Ollama's HTTP API on localhost; nothing is sent anywhere else.
"""
import argparse
import json
import sys
import time

import requests

# Tried in order: Ollama library tag, the same weights straight from Hugging Face, the hybrid model.
CANDIDATES = {
    "4b": ["qwen3:4b-instruct-2507-q4_K_M", "hf.co/unsloth/Qwen3-4B-Instruct-2507-GGUF:Q4_K_M", "qwen3:4b"],
    "8b": ["qwen3:8b"],
    "small": ["qwen3:1.7b", "llama3.2:3b"],
}
TOO_SMALL = (":1b", ":0.5b", ":0.6b", ":1.5b", ":360m", ":135m", "1b-", "-1b")


def is_too_small(model: str) -> bool:
    name = (model or "").lower()
    return any(tag in name for tag in TOO_SMALL)


def ram_gb() -> float:
    try:
        import psutil
        return psutil.virtual_memory().total / 2 ** 30
    except Exception:
        return 0.0


def recommend(total_ram_gb: float) -> list[str]:
    """Candidate tags for this much RAM. A 4B model at Q4 needs ~3 GB on top of Whisper and MXB."""
    if total_ram_gb and total_ram_gb < 7.5:
        return CANDIDATES["small"]
    return CANDIDATES["4b"]


class Ollama:
    def __init__(self, base_url: str = "http://localhost:11434", timeout: float = 15):
        self.base = base_url.rstrip("/")
        self.timeout = timeout

    def models(self) -> list[str]:
        resp = requests.get(f"{self.base}/api/tags", timeout=self.timeout)
        resp.raise_for_status()
        return [m.get("name", "") for m in resp.json().get("models", [])]

    def has(self, model: str) -> bool:
        try:
            names = self.models()
        except Exception:
            return False
        want = model if ":" in model.split("/")[-1] else model + ":latest"
        return model in names or want in names

    def pull(self, model: str, progress=print) -> bool:
        """Streams Ollama's pull progress; True when the model is ready."""
        try:
            with requests.post(f"{self.base}/api/pull", json={"model": model, "name": model, "stream": True},
                               stream=True, timeout=(10, 600)) as resp:
                if resp.status_code != 200:
                    progress(f"  {model}: Ollama said {resp.status_code} {resp.text[:120]}")
                    return False
                last = ("", -10)
                for line in resp.iter_lines(decode_unicode=True):
                    if not line:
                        continue
                    msg = json.loads(line)
                    if msg.get("error"):
                        progress(f"  {model}: {msg['error']}")
                        return False
                    status = msg.get("status", "")
                    pct = int(100 * msg.get("completed", 0) / msg["total"]) if msg.get("total") else -1
                    if status != last[0] or pct >= last[1] + 10:       # a line per step and per 10%
                        progress(f"  {model}: {status}" + (f" {pct}%" if pct >= 0 else ""))
                        last = (status, pct)
                    if status == "success":
                        return True
        except Exception as e:
            progress(f"  {model}: {e}")
            return False
        return self.has(model)

    def pull_first(self, candidates: list[str], progress=print) -> str | None:
        for model in candidates:
            if self.has(model):
                progress(f"{model} is already downloaded.")
                return model
            progress(f"Downloading {model} ...")
            if self.pull(model, progress):
                return model
        return None


def set_local_model(model: str) -> None:
    from utils.paths import load_config, save_config
    config = load_config()
    config.setdefault("llm", {})["local_model"] = model
    save_config(config)


def compare(current: str, new: str) -> dict:
    """Brain benchmark (plans only, nothing executed) on both models, local only."""
    from bench.brain import run_brain
    out = {}
    for model in dict.fromkeys([current, new]):
        t0 = time.time()
        res = run_brain(model=model, local_only=True)
        s = res["summary"]
        out[model] = s
        print(f"  {model}: {s['passed']}/{s['cases']} plans right ({s['accuracy']}%), "
              f"{s['model_failures']} failures, p50 {s['p50_s']} s ({time.time() - t0:.0f} s total)")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--pull", action="store_true", help="download the recommended model")
    ap.add_argument("--model", default="", help="use this Ollama model instead of the recommendation")
    ap.add_argument("--compare", action="store_true", help="benchmark the current and the new model")
    ap.add_argument("--switch", action="store_true", help="make the new model MXB's local model")
    args = ap.parse_args(argv)

    if sys.platform != "win32":
        import tests._stubs  # noqa: F401  (Windows-only packages, for the benchmark's router)
    from utils.paths import load_config
    current = load_config().get("llm", {}).get("local_model", "llama3.2:1b")
    ram = ram_gb()
    candidates = [args.model] if args.model else recommend(ram)
    print(f"This PC: {ram:.1f} GB RAM. Current local model: {current}"
          + (" (too small to plan reliably)" if is_too_small(current) else ""))
    print(f"Recommended: {candidates[0]}")
    if not args.pull:
        return 0

    ollama = Ollama()
    try:
        ollama.models()
    except Exception:
        print("Ollama isn't running. Start it (ollama serve, or the Ollama app) and try again.")
        return 2
    new = ollama.pull_first(candidates)
    if not new:
        print("Couldn't download any of: " + ", ".join(candidates))
        return 3

    results = {}
    if args.compare:
        print("Brain benchmark (plans only, nothing is executed):")
        results = compare(current, new)
    if args.switch:
        better = (not results or new == current
                  or results[new]["accuracy"] >= results.get(current, {"accuracy": -1})["accuracy"])
        if better:
            set_local_model(new)
            print(f"MXB now uses {new}. Restart MXB to load it.")
        else:
            print(f"Kept {current}: {new} scored lower on this PC.")
    try:
        from utils.paths import data_dir
        (data_dir() / "logs").mkdir(exist_ok=True)
        (data_dir() / "logs" / "model_setup.json").write_text(
            json.dumps({"current": current, "new": new, "ram_gb": round(ram, 1), "results": results}, indent=2),
            encoding="utf-8")
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
