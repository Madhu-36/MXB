# Contributing to Machine eXecutive Brain (MXB)

Welcome to MXB development! This project operates with a decoupled, parallel real-time architecture designed for sub-second response times and bulletproof stability.

---

## Architecture Rules & Code Conventions

1. **Non-Blocking Ingestion**:
   - The audio callback thread and neural VAD loop must **never** perform synchronous I/O, heavy calculations, or blocking network requests.
   - Long operations must be dispatched to worker queues (`utterance_queue` or `action_task_queue`).

2. **Windows 64-bit ctypes Safety**:
   - Every `user32.dll` API (`keybd_event`, `mouse_event`, `GetCursorPos`, etc.) must have explicit `argtypes` and `restype` defined in the class `__init__`.
   - Never call native Windows APIs with untyped Python integers (prevents `0xC0000409` stack canary corruption).

3. **Plan Interruptibility**:
   - Any long action in `ActionPlanner` must poll `self._abort_event.is_set()` every 50 ms.
   - Always honor user interrupts (`"stop"`, `"cancel"`).

---

## Running the checks

```powershell
python scripts/verify_all.py --portable     # the cross-platform suites (what Linux CI runs)
python scripts/verify_all.py                # everything, on Windows
python -m bench.run                         # routing gate: tuned precision must stay 100%
python -m bench.run --suite brain           # planner accuracy with your model (plans only, nothing runs)
scripts\listening_bench.bat                 # the voice pipeline on this PC, with your room's noise
```

Install the pre-push hook once per clone; every `git push` then runs lint, the portable suites and
the routing gate first (the same checks as CI):

```powershell
python scripts/install_hooks.py
```

A test that failed before your change is the best evidence it works. Numbers beat adjectives:
"3/6 -> 6/6 commands in the listening bench" is a better commit message than "improved listening".

---

## Branches, pull requests and releases

- **`main` is the release branch.** It only changes through merged pull requests. Never commit to
  it directly, never force-push it.
- **One feature or fix per branch** (`feature/<name>`, `fix/<name>`), one pull request each, kept small
  enough to review in one sitting. Fill in the PR template, including how it was checked.
- **AI coding agents follow the same rules as people** (Antigravity, Claude, Copilot...): they work on
  their own branch, open a pull request, and a person reviews it before it is merged. Two people or
  agents never commit to the same branch at the same time: pull first, and if someone else is active
  on a branch, use your own.
- **Commit messages:** an imperative subject under 72 characters with a type (`feat`, `fix`, `test`,
  `docs`, `refactor`, `perf`), and a body saying why and how it was verified.
- **Releases:** bump `utils/version.py` and `CHANGELOG.md` in a PR, merge it, then tag `vX.Y.Z` on `main`.
  `.github/workflows/release.yml` builds the installer and `SHA256SUMS.txt` from the tag.

### Repository settings (the owner, once)

GitHub > Settings > Rules > Rulesets > New branch ruleset for `main`:
require a pull request before merging (1 approval), require status checks to pass
(**Lint (fatal errors)**, both **Portable tests** jobs, **Windows tests**), block force pushes,
restrict deletions. Settings > General: turn on "Automatically delete head branches".

---

## Adding a New OS Action

1. Add the core capability method to `engine/executor.py` or the appropriate submodule (`mouse.py`, `keyboard_ext.py`, `file_ops.py`, `screen.py`).
2. Map the action name in `OSExecutionManager.execute_action(self, action, target)`.
3. Add aliases and normalization rules.
4. Add the action to the available action lists in `engine/router.py` (both system prompts).
5. Document the action in `docs/ACTIONS_REFERENCE.md`.
6. Add unit tests in `tests/`.
