# MXB V2.0 - Workflow Automation & Task Orchestration Engine Manual

## 1. Executive Summary & Automation Vision
MXB V2.0 transforms natural language voice commands into deterministic, multi-step desktop workflows. By unifying Windows UI Automation (UIA), simulated input injection, background script execution, and filesystem event watchers, MXB serves as an autonomous desktop orchestrator.

```
+---------------------------------------------------------------------------------+
|                        MXB Workflow Orchestration Engine                        |
|                                                                                 |
| [ Voice Trigger / Hotkey / Cron ] ---> [ Workflow Parser & DAG Builder ]        |
|                                                      |                          |
|                                                      v                          |
|       +---------------------------------[ Step Pipeline ]----------------+      |
|       |                                                                  |      |
|       v                                  v                               v      |
|  [ UI Automation (UIA) ]       [ PowerShell Sandbox ]         [ Browser (CDP) ] |
|  - Window Focus                - Script Execution             - DOM Scraping    |
|  - Control Click               - Environment Capture          - Form Fill       |
|       |                                  |                               |      |
|       +----------------------------------+-------------------------------+      |
|                                          |                                      |
|                                          v                                      |
|                 [ State Store & Audit Log (SQLite WAL) ]                        |
+---------------------------------------------------------------------------------+
```

All workflows execute locally under strict principle-of-least-privilege sandboxing, ensuring complete user visibility and reversibility.


## 2. Declarative YAML Workflow Schema
Workflows are defined declaratively in human-readable YAML with schema validation enforcing parameter typing, timeout ceilings, and failure recovery policies.

```yaml
version: "2.0"
workflow:
  id: "daily_standup_prep"
  name: "Daily Standup Preparation"
  description: "Launches work tools, gathers git commits, and copies status to clipboard."
  trigger:
    type: "voice"
    phrases: ["prepare standup", "ready for standup", "start morning routine"]
  concurrency: "forbid"
  timeout_seconds: 45
  steps:
    - id: "open_term"
      action: "os.launch_app"
      params:
        app_name: "Windows Terminal"
    - id: "git_log"
      action: "shell.execute"
      params:
        command: "git log --since='24 hours ago' --oneline"
        working_dir: "%USERPROFILE%/Projects"
      output_var: "recent_commits"
    - id: "notify"
      action: "notification.toast"
      params:
        title: "Standup Ready"
        message: "Found {{ recent_commits | length }} commits in the last 24h."
```


## 3. Directed Acyclic Graph (DAG) Execution Engine
Workflows with interdependent tasks are compiled into a Directed Acyclic Graph (DAG) where steps without mutual dependencies execute concurrently.

### DAG Compilation & Topological Sort
```python
from collections import defaultdict, deque

class WorkflowDAG:
    def __init__(self, steps: list[dict]):
        self.adj = defaultdict(list)
        self.in_degree = defaultdict(int)
        self.steps = {s["id"]: s for s in steps}
        for s in steps:
            for dep in s.get("depends_on", []):
                self.adj[dep].append(s["id"])
                self.in_degree[s["id"]] += 1

    def get_execution_order(self) -> list[list[str]]:
        queue = deque([s_id for s_id in self.steps if self.in_degree[s_id] == 0])
        stages = []
        while queue:
            current_stage = list(queue)
            stages.append(current_stage)
            queue.clear()
            for u in current_stage:
                for v in self.adj[u]:
                    self.in_degree[v] -= 1
                    if self.in_degree[v] == 0:
                        queue.append(v)
        return stages
```


## 4. Windows UI Automation (UIA) Control Traversal
Rather than relying solely on brittle pixel-coordinate clicking, MXB navigates the Windows Accessibility UI Automation tree via Microsoft UIAutomation Core COM APIs.

### Element Locators
- **AutomationId**: Unique developer-assigned identifier (e.g., `SubmitButton`).
- **Name / BoundingRectangle**: Localized control text and layout bounds.
- **ControlType**: Semantic role (e.g., `UIA_ButtonControlTypeId`, `UIA_EditControlTypeId`).

```python
import uiautomation as auto

def click_element_by_id(root_window: auto.WindowControl, automation_id: str):
    control = root_window.Control(AutomationId=automation_id, searchDepth=4)
    if control.Exists(maxSearchSeconds=2):
        control.Click(simulateMove=False)
        return True
    return False
```


## 5. Low-Level Input Simulation with Win32 SendInput
When standard UIA control patterns are unavailable (e.g. in legacy Win32 apps or games), MXB falls back to hardware-level keyboard and mouse simulation via `SendInput`.

```c
// Low-level Win32 Input Injection
INPUT input;
input.type = INPUT_KEYBOARD;
input.ki.wVk = VK_SPACE;
input.ki.dwFlags = 0; // Key down
SendInput(1, &input, sizeof(INPUT));

input.ki.dwFlags = KEYEVENTF_KEYUP; // Key up
SendInput(1, &input, sizeof(INPUT));
```

All simulated keystrokes include randomized micro-jitter delays (10-30ms) to ensure desktop message queues process inputs without dropped characters.


## 6. Accessibility Control Pattern Handlers
MXB leverages specialized UIA Control Patterns to manipulate UI elements directly without moving the mouse pointer:

### Supported Patterns
- **IUIAutomationInvokePattern**: Triggers buttons and menu items directly via internal COM dispatches.
- **IUIAutomationValuePattern**: Sets or reads text inside input boxes without emulating clipboard typing.
- **IUIAutomationSelectionItemPattern**: Selects radio buttons, list items, or dropdown options.
- **IUIAutomationTogglePattern**: Toggles checkboxes between checked and unchecked states.


## 7. Intelligent Window Layout & Snap Automation
MXB orchestrates multi-window layouts across multiple physical monitors to prepare optimal workspaces for development, research, or gaming.

### Window Operations
```python
import win32gui
import win32con

def snap_window_left(hwnd: int, screen_width: int, screen_height: int):
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    # Move window to left half of target display
    win32gui.SetWindowPos(
        hwnd, win32con.HWND_TOP,
        0, 0, screen_width // 2, screen_height,
        win32con.SWP_SHOWWINDOW
    )
```

Supports predefined layout profiles: `DualSplit`, `QuarterGrid`, `FocusedCenter`, and `ZenPresentation`.


## 8. Headless Browser Orchestration via Chrome DevTools Protocol (CDP)
To interact with modern web applications without installing heavy external browser drivers, MXB connects to existing Chromium browsers via WebSocket CDP sessions.

```python
import websockets
import json

async def attach_cdp_tab(ws_url: str):
    async with websockets.connect(ws_url) as ws:
        # Navigate tab to target URL
        await ws.send(json.dumps({
            "id": 1,
            "method": "Page.navigate",
            "params": {"url": "https://calendar.google.com"}
        }))
        response = await ws.recv()
        return json.loads(response)
```

Enables DOM scraping, cookie extraction, and form entry within user-authenticated browser tabs.


## 9. File Watcher Triggers via ReadDirectoryChangesW
Automations can trigger reactively upon filesystem events—such as new downloads, modified markdown files, or log file appends.

### Win32 Directory Notification Loop
```python
import win32file
import win32con

def watch_directory(path: str, on_created_callback):
    h_dir = win32file.CreateFile(
        path, win32con.GENERIC_READ,
        win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
        None, win32con.OPEN_EXISTING, win32con.FILE_FLAG_BACKUP_SEMANTICS, None
    )
    while True:
        results = win32file.ReadDirectoryChangesW(
            h_dir, 1024, True,
            win32con.FILE_NOTIFY_CHANGE_FILE_NAME | win32con.FILE_NOTIFY_CHANGE_LAST_WRITE,
            None, None
        )
        for action, file in results:
            if action == 1: # File Created
                on_created_callback(file)
```


## 10. Cron & Recurring Schedule Orchestrator
MXB incorporates an in-process cron evaluator supporting standard 5-part cron expressions, interval frequencies, and ISO 8601 timestamps.

### Schedule Rules Schema
```json
{
  "schedules": [
    {
      "workflow_id": "backup_memory_bank",
      "cron": "0 2 * * *",
      "description": "Daily snapshot at 02:00 AM"
    },
    {
      "workflow_id": "clean_temp_downloads",
      "interval_hours": 12,
      "description": "Every 12 hours purge files older than 7 days"
    }
  ]
}
```

Schedules survive application restarts, persisting execution timestamps in SQLite.


## 11. Windows Session State & Power Event Triggers
Automations can bind to Windows desktop lifecycle events using `WTSRegisterSessionNotification`:

### Monitored Session Events
- **WTS_SESSION_LOCK**: Automatically pause voice recording and clear active clipboard caches.
- **WTS_SESSION_UNLOCK**: Restore assistant HUD and run pending scheduled reminders.
- **PBT_APMSUSPEND**: Flush write-ahead logs and release GPU inference locks before laptop sleep.
- **PBT_APMRESUMEAUTOMATIC**: Re-initialize WASAPI audio device streams upon system wakeup.


## 12. Global Hotkey Interception & Chord Combinations
Fast keyboard shortcuts allow power users to trigger complex workflows with zero voice interaction.

### Win32 RegisterHotKey Integration
```python
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_NOREPEAT = 0x4000

# Bind Ctrl + Alt + Space to Instant Assistant Trigger
HOTKEY_ID = 101
user32.RegisterHotKey(None, HOTKEY_ID, MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, wintypes.VK_SPACE)
```

Supports two-stroke key chords (e.g., `Ctrl+K, Ctrl+W` to open workflow manager).


## 13. Voice Trigger Matching & Entity Slot Extraction
When users invoke workflows via voice, the engine extracts runtime arguments directly from transcribed speech.

### Slot Extraction Engine
```python
import re

pattern = re.compile(r"^(?:set|turn)\s+timer\s+for\s+(?P<duration>\d+)\s+(?P<unit>seconds|minutes|hours)$", re.IGNORECASE)

def parse_voice_slots(utterance: str) -> dict | None:
    match = pattern.match(utterance.strip())
    if match:
        return match.groupdict()
    return None
```

Extracted parameters (`duration=10`, `unit="minutes"`) are bound to the workflow execution context as typed variables.


## 14. Human-In-The-Loop Approval Gates
Privileged or destructive actions (such as deleting files, killing processes, or submitting forms) require explicit user consent.

```
+-------------------------------------------------------------+
|                     MXB Security Guard                      |
|                                                             |
| Action Requested: os.delete_directory                       |
| Target: C:\Users\User\Downloads\Staging                 |
| Risk Level: HIGH (Irreversible File Deletion)               |
|                                                             |
| [ Confirm (Voice: 'Proceed') ]      [ Cancel (Escape) ]     |
+-------------------------------------------------------------+
```

Workflows pause in a pending state until confirmation is received via voice keyword or UI button press; unapproved requests timeout after 30 seconds.


## 15. Transactional Rollback & Compensation Actions
If a workflow fails halfway through a 5-step sequence, prior actions must be cleanly undone to avoid leaving the system in an inconsistent state.

### Compensation Pattern Definition
```yaml
steps:
  - id: "backup_file"
    action: "fs.copy"
    params: {src: "config.json", dest: "config.json.bak"}
    rollback:
      action: "fs.delete"
      params: {target: "config.json.bak"}
  - id: "write_new_config"
    action: "fs.write"
    params: {target: "config.json", content: "{{ new_data }}"}
    rollback:
      action: "fs.copy"
      params: {src: "config.json.bak", dest: "config.json"}
```

Upon step failure, compensation handlers execute in reverse order (LIFO).


## 16. Subprocess Shell Execution Sandboxing
Scripts dispatched by workflows are executed inside an isolated Windows process container with strict resource limits.

### Sandbox Safeguards
- **No Elevated Privileges**: Subprocesses spawn with token filtering preventing automatic UAC bypass.
- **Process Job Objects**: CPU utilization capped at 50%; memory usage limited to 1 GB per execution.
- **Hard Timeout**: Default 15-second process timeout, after which `TerminateProcess` is called automatically.
- **Output Sanitization**: Stdout/stderr streams are scrubbed of environment tokens and passwords before logging.


## 17. Clipboard Transformation Pipelines
Workflows can capture, transform, and paste clipboard content seamlessly.

### Pipeline Stages
1. **Read Clipboard**: Supports text, HTML, and image formats (`CF_UNICODETEXT`, `CF_DIB`).
2. **Transform**: Apply regex replacement, markdown-to-HTML conversion, or LLM summarization.
3. **Commit & Paste**: Write transformed text back to clipboard and synthesize `Ctrl+V` keypress into foreground application.


## 18. Windows Action Center Toast Notifications
Workflows communicate asynchronous progress using native Windows 11 Toast notifications via the WinRT `ToastNotificationManager` API.

### Toast XML Architecture
```xml
<toast scenario="reminder">
    <visual>
        <binding template="ToastGeneric">
            <text>MXB Automation Complete</text>
            <text>Processed 14 report PDFs and archived to Cloud Vault.</text>
        </binding>
    </visual>
    <actions>
        <action content="Open Folder" arguments="action=open_dir&amp;path=C:\Vault" activationType="foreground"/>
        <action content="Dismiss" arguments="action=dismiss" activationType="system"/>
    </actions>
</toast>
```


## 19. Audio Feedback & Earcon Cues
In headless or voice-only mode, auditory cues ("earcons") confirm task states without requiring the user to look at the screen.

### Sound Map
- `workflow_start.wav`: Low-frequency chime indicating workflow initialization.
- `step_complete.wav`: Crisp 20ms tactile tick marking intermediate step completion.
- `workflow_success.wav`: Harmonic chord confirming overall success.
- `workflow_error.wav`: Gentle dual-tone warning prompting user intervention.


## 20. Variable Scope & State Persistence
Each workflow execution maintains an isolated variable dictionary that prevents cross-tenant state leakage.

### Variable Scopes
- **Local Scope**: Step outputs and loop variables (e.g. `{{ steps.git_log.stdout }}`); destroyed on completion.
- **Workflow Scope**: Parameters passed at workflow invocation.
- **Global Vault Scope**: Persistent key-value pairs stored in local encrypted SQLite (e.g. `{{ global.default_workspace }}`).


## 21. Failure Policies & Exponential Backoff
Transient failures (such as a busy database lock or a slow browser page load) are handled gracefully via automated retry policies.

```yaml
retry_policy:
  max_attempts: 3
  initial_delay_ms: 250
  backoff_multiplier: 2.0
  max_delay_ms: 2000
  retryable_errors:
    - "TimeoutError"
    - "UIAElementNotFoundException"
```

If all attempts fail, the workflow execution context is moved to a dead-letter queue (`dlq_workflows`) for user inspection.


## 22. Dry-Run Simulation & Visual Step Preview
Users can test complex or unfamiliar automations in Dry-Run mode before allowing actions to touch the live operating system.

### Dry-Run Mechanics
- All read actions (queries, window lookups, file reads) execute normally.
- All write actions (file writes, clicks, keystrokes, process kills) are intercepted by a mock driver.
- The PySide6 HUD displays an interactive step-by-step preview showing exact parameters and intended changes.


