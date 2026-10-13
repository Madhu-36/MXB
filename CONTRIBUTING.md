
## Section 1: Initialize CONTRIBUTING guidelines
Welcome to MXB contributor guide. We welcome community contributions to build the best local AI assistant.

## Section 2: Define code of conduct
Contributors must adhere to inclusive, professional, and constructive collaboration standards.

## Section 3: Outline development environment prerequisites
Requires Python 3.10+, Ollama with Llama 3.1, Windows 10/11, and a working microphone input.

## Section 4: Detail repository fork and branch conventions
Branch naming follows feature/<name>, fix/<name>, or docs/<name> branched from main.

## Section 5: Document virtual environment isolation
Use a dedicated .venv virtual environment to prevent dependency conflicts with system Python.

## Section 6: Add pre-commit hooks and linting standards
Run pre-commit checks before pushing any changes to maintain repository hygiene.

## Section 7: Define Black and Flake8 formatting rules
Format code using Black with line length 100 and enforce Flake8 PEP8 guidelines.

## Section 8: Document type hinting and mypy checks
All new functions and methods must provide strict type annotations verified with mypy.

## Section 9: Specify unit testing guidelines with pytest
Tests reside in tests/ and must be executable via pytest with coverage metrics.

## Section 10: Detail PySide6 UI component testing conventions
Use QtTest module for testing frameless HUD event loops and animations headless.

## Section 11: Document Mock audio streaming for tests
Audio tests should use synthetic numpy audio buffers instead of hardware devices.

## Section 12: Add LLM prompt engineering guidelines
Ensure system prompt modifications maintain strict JSON schema output formatting.

## Section 13: Define Modelfile versioning procedures
Update the LLM hash and document template tweaks when modifying the Ollama Modelfile.

## Section 14: Document Conventional Commits standards
Follow conventional commit format: feat, fix, docs, style, refactor, perf, test, chore.

## Section 15: Outline pull request submission process
Ensure PRs reference relevant issue IDs with detailed descriptions and passing test suites.

## Section 16: Detail code review checklist
Reviewers will verify security, thread safety in QThreads, and offline execution integrity.

## Section 17: Add performance profiling and benchmarking requirements
Measure audio VAD latency and memory overhead to ensure zero frame drops on host OS.
