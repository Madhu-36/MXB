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


