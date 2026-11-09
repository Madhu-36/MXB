"""
Installs a git pre-push hook that runs the same checks as CI before anything leaves this PC:
fatal lint (ruff E9,F63,F7,F82 when ruff is installed), the portable test suites and the routing
benchmark gate. A push with a failing check is stopped; `git push --no-verify` overrides it.

    python scripts/install_hooks.py
"""
import stat
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

HOOK = """#!/bin/sh
# MXB pre-push checks (installed by scripts/install_hooks.py). Skip once with: git push --no-verify
cd "$(git rev-parse --show-toplevel)" || exit 1
if [ -x .venv/Scripts/python.exe ]; then PY=.venv/Scripts/python.exe
elif [ -x .venv/bin/python ]; then PY=.venv/bin/python
elif command -v python >/dev/null 2>&1; then PY=python
else PY=python3
fi
echo "MXB pre-push: lint, portable tests, routing bench..."
if "$PY" -m ruff --version >/dev/null 2>&1; then
  "$PY" -m ruff check --select E9,F63,F7,F82 . || exit 1
fi
mkdir -p logs
"$PY" scripts/verify_all.py --portable >logs/prepush.log 2>&1 || { tail -40 logs/prepush.log; echo "Tests failed; push stopped (full log: logs/prepush.log)."; exit 1; }
"$PY" -m bench.run --suite routing --min-precision 0.95 >/dev/null 2>&1 || { echo "Routing benchmark regressed; push stopped."; exit 1; }
echo "MXB pre-push: all checks passed."
"""


def hooks_dir() -> Path | None:
    """Where git looks for hooks: respects worktrees and core.hooksPath."""
    try:
        out = subprocess.run(["git", "rev-parse", "--git-path", "hooks"], cwd=ROOT,
                             capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        out = None
    if out is not None and out.returncode == 0 and out.stdout.strip():
        path = Path(out.stdout.strip())
        return path if path.is_absolute() else ROOT / path
    fallback = ROOT / ".git"
    return fallback / "hooks" if fallback.is_dir() else None


def main() -> int:
    hooks = hooks_dir()
    if hooks is None:
        print("Not a git checkout; nothing to install.")
        return 1
    hooks.mkdir(parents=True, exist_ok=True)
    hook = hooks / "pre-push"
    hook.write_text(HOOK, encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Installed {hook}. Every git push now runs the CI checks first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
