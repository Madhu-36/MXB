# MXB V2.0 - Testing Strategy & Quality Assurance Architecture

## 1. Executive Summary & Quality Principles
MXB V2.0 operates at the confluence of real-time audio streams, neural model inference, desktop GUI composition, and native Windows operating system hooks. To guarantee zero regressions in sub-second voice latency, memory stability, and security boundaries, MXB implements a rigorous, automated testing pyramid.

```
+-----------------------------------------------------------------------------+
|                           MXB Testing Pyramid                               |
|                                                                             |
|                               /\                                            |
|                              /  \   E2E Voice-to-Action Flows (<5%)         |
|                             /----\                                          |
|                            /      \  Integration & Hardware Chaos (15%)     |
|                           /--------\                                        |
|                          /          \  Component & Subsystem Tests (30%)    |
|                         /------------\                                      |
|                        /              \  Unit, Logic & Grammar Mocks (50%)   |
|                       +----------------+                                    |
+-----------------------------------------------------------------------------+
```

### Core Testing Mandates
- **Deterministic Oracles**: Eliminate non-deterministic test failures by mocking dynamic LLM outputs via GBNF grammar validators and synthetic audio streams.
- **Sub-Second Execution**: Unit test suites must complete under 15 seconds to support continuous pre-commit feedback.
- **Air-Gapped CI Validation**: Automated tests run with socket connections locked to loopback (`127.0.0.1`), ensuring zero stealth telemetry or network reliance.


## 2. Multi-Tiered Test Architecture & Coverage SLAs
Quality targets are enforced through strict branch and line coverage thresholds measured via `coverage.py`.

### SLA Matrix
| Subsystem Tier | Target Line Coverage | Target Branch Coverage | Maximum Allowed Latency |
|----------------|----------------------|------------------------|-------------------------|
| Core Engine (`engine/`) | >= 92% | >= 88% | < 50ms per test |
| Audio Pipeline (`audio/`) | >= 85% | >= 80% | < 100ms per test |
| UI & HUD (`ui/`) | >= 80% | >= 75% | < 250ms per test |
| Safety & Sandboxing (`safety/`) | **100%** | **100%** | < 10ms per test |
| Automation & Workflows (`automation/`) | >= 90% | >= 85% | < 150ms per test |

Any pull request that drops safety test coverage below 100% or global coverage below 88% fails the automated CI gate.


## 3. Pytest Configuration & Test Tagging Taxonomy
MXB centralizes its test suite configuration in `pytest.ini` with custom markers isolating long-running hardware tests from rapid unit passes.

```ini
[pytest]
minversion = 8.0
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -ra -q --strict-markers --durations=10
markers =
    unit: Fast in-memory unit tests with zero I/O
    audio: Tests requiring virtual WASAPI audio loopback
    llm: Tests validating local model inference and GBNF grammars
    gui: Tests exercising PySide6 windows via pytest-qt
    slow: Long-running stress, memory leak, or benchmark tests
    chaos: Fault-injection and hardware disconnection scenarios
```


## 4. Win32 & COM API Mocking Framework
Native Windows APIs (`win32gui`, `win32process`, `win32con`, and COM `pythoncom`) require robust abstraction stubs when tests run on headless CI runners.

```python
from unittest.mock import MagicMock
import pytest

@pytest.fixture
def mock_win32_desktop(monkeypatch):
    mock_gui = MagicMock()
    mock_gui.GetForegroundWindow.return_value = 0x10294
    mock_gui.GetWindowText.return_value = "Visual Studio Code"
    mock_gui.GetWindowRect.return_value = (0, 0, 1920, 1080)
    
    monkeypatch.setattr("win32gui.GetForegroundWindow", mock_gui.GetForegroundWindow)
    monkeypatch.setattr("win32gui.GetWindowText", mock_gui.GetWindowText)
    monkeypatch.setattr("win32gui.GetWindowRect", mock_gui.GetWindowRect)
    return mock_gui
```


