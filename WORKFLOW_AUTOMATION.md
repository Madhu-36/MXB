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


