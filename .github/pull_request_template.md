## What changed and why

<!-- One feature or fix per PR. Say what was wrong (with the evidence: a log line, a test, a bench number) and what is different now. -->

## How it was checked

- [ ] `python scripts/verify_all.py --portable` passes (paste the summary line)
- [ ] `python -m bench.run` routing: tuned precision still 100%, held-out not lower
- [ ] New behaviour has tests (a test that failed before the change is best)
- [ ] Tried on Windows where it touches audio, UI automation, hardware or the installer
- [ ] No secrets, personal paths or `config.json` personal settings in the diff

## Risk

<!-- What could this break? Anything the user must do (new model download, new setting, restart)? -->
