"""
Plugin skills: drop a .py file into plugins/ to teach MXB new abilities.

    # plugins/my_skill.py
    from engine.skills import skill

    @skill(name="open_github", patterns=[r"^open my github$"],
           description="Open the user's GitHub profile", target="none")
    def open_github(target, ctx):
        ctx.executor.execute_action("open_url", "github.com/srinivas-rc0408")
        return "Opening your GitHub."

- patterns: regexes matched against the lowercased command (named group "target",
  or the first group, becomes the target). Matched before the LLM, so they're instant.
- Every skill is also added to the LLM's action list, so "plan" requests can use it.
- risk="confirm" makes MXB ask before running it (same as delete/shutdown).
- ctx gives: executor (mouse, keyboard, files, hardware...), speak(text), llm, memory, config, log.

Plugins run with your user's permissions. Only install plugins you have read and trust.
List disabled plugin files in config.json -> skills.disabled.
"""
import importlib.util
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from engine.actions_catalog import ActionSpec, register_dynamic, get_spec
from utils.logger import log

_PENDING: list["Skill"] = []   # filled by @skill while a plugin module is imported


@dataclass
class Skill:
    name: str
    func: object
    patterns: list = field(default_factory=list)
    description: str = ""
    target: str = "text"
    risk: str = "safe"
    uses_input: bool = False
    source: str = ""


def skill(name: str, patterns: list[str] | None = None, description: str = "", target: str = "text",
          risk: str = "safe", uses_input: bool = False):
    """Decorator used inside plugin files."""
    def wrap(func):
        _PENDING.append(Skill(name=name, func=func, patterns=[re.compile(p, re.I) for p in (patterns or [])],
                              description=description or (func.__doc__ or name).strip().splitlines()[0],
                              target=target, risk=risk, uses_input=uses_input))
        return func
    return wrap


class SkillContext:
    def __init__(self, executor=None, speak=None, llm=None, memory=None, config=None):
        self.executor = executor
        self.speak = speak or (lambda text: None)
        self.llm = llm
        self.memory = memory
        self.config = config or {}
        self.log = log


class SkillRegistry:
    def __init__(self, plugin_dir: str | Path | None = None, disabled: list[str] | None = None):
        if plugin_dir:
            self.plugin_dirs = [Path(plugin_dir)]
        else:
            from utils.paths import plugin_dirs
            self.plugin_dirs = plugin_dirs()   # shipped examples + %APPDATA%\MXB\plugins when installed
        self.plugin_dir = self.plugin_dirs[-1]
        self.disabled = {d.lower().removesuffix(".py") for d in (disabled or [])}
        self.skills: dict[str, Skill] = {}
        self.errors: dict[str, str] = {}
        self.context = SkillContext()

    def load_all(self) -> int:
        for folder in self.plugin_dirs:
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.py")):
                if path.name.startswith("_") or path.stem.lower() in self.disabled:
                    continue
                self.load_file(path)
        log.info(f"Skills: loaded {len(self.skills)} skills from {', '.join(map(str, self.plugin_dirs))} ({len(self.errors)} errors)")
        return len(self.skills)

    def load_file(self, path: Path) -> list[str]:
        _PENDING.clear()
        mod_name = f"mxb_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = module
            spec.loader.exec_module(module)
            if hasattr(module, "register"):
                module.register(self)
        except Exception as e:
            self.errors[path.name] = f"{e}"
            log.error(f"Skills: failed to load {path.name}: {e}\n{traceback.format_exc()}")
            _PENDING.clear()
            return []
        loaded = []
        for sk in list(_PENDING):
            sk.source = path.name
            if self.add(sk):
                loaded.append(sk.name)
        _PENDING.clear()
        return loaded

    def add(self, sk: Skill) -> bool:
        key = sk.name.lower().strip().replace(" ", "_")
        builtin = get_spec(key)
        if builtin is not None and key not in self.skills:
            if not getattr(builtin, "_plugin", False) and builtin.category != "plugin":
                log.warning(f"Skills: '{key}' clashes with a built-in action; skipped.")
                return False
        sk.name = key
        self.skills[key] = sk
        register_dynamic(ActionSpec(key, sk.target, sk.description, "plugin", risk=sk.risk, uses_input=sk.uses_input))
        return True

    def has(self, name: str) -> bool:
        return (name or "").lower() in self.skills

    def match(self, text: str) -> tuple[Skill, str] | None:
        t = (text or "").strip()
        for sk in self.skills.values():
            for pat in sk.patterns:
                m = pat.search(t)
                if m:
                    if "target" in pat.groupindex:
                        target = m.group("target") or ""
                    elif m.groups():
                        target = m.group(1) or ""
                    else:
                        target = ""
                    return sk, target.strip()
        return None

    def run(self, name: str, target: str) -> str:
        sk = self.skills.get((name or "").lower())
        if sk is None:
            return f"No skill named '{name}'."
        try:
            out = sk.func(target, self.context)
            return "" if out is None else str(out)
        except Exception as e:
            log.error(f"Skills: '{name}' crashed: {e}\n{traceback.format_exc()}")
            return f"The {name} skill failed: {e}"

    def describe(self) -> str:
        if not self.skills:
            return "No plugin skills are installed. Add .py files to the plugins folder."
        lines = [f"{s.name} ({s.source}): {s.description}" for s in self.skills.values()]
        return "Installed skills: " + "; ".join(lines)
