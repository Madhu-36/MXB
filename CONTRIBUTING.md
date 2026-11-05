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

## Running Automated Tests

Run the full regression suite using unittest:

```powershell
.\.venv\Scripts\python.exe -m unittest discover tests
```

To run individual test modules:

```powershell
.\.venv\Scripts\python.exe -m unittest tests.test_architecture
.\.venv\Scripts\python.exe -m unittest tests.test_mouse_safety
.\.venv\Scripts\python.exe -m unittest tests.test_keyboard_macros
.\.venv\Scripts\python.exe -m unittest tests.test_config_schema
.\.venv\Scripts\python.exe -m unittest tests.test_file_search
.\.venv\Scripts\python.exe -m unittest tests.test_memory_export
.\.venv\Scripts\python.exe -m unittest tests.test_executor_apps
```

---

## Adding a New OS Action

1. Add the core capability method to `engine/executor.py` or the appropriate submodule (`mouse.py`, `keyboard_ext.py`, `file_ops.py`, `screen.py`).
2. Map the action name in `OSExecutionManager.execute_action(self, action, target)`.
3. Add aliases and normalization rules.
4. Add the action to the available action lists in `engine/router.py` (both system prompts).
5. Document the action in `docs/ACTIONS_REFERENCE.md`.
6. Add unit tests in `tests/`.
