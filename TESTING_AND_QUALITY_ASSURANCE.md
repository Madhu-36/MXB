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


