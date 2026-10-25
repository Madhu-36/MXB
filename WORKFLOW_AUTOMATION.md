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


