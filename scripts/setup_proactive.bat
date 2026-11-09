@echo off
rem Connects MXB to your calendar (its private iCal link) and email (IMAP + an app password).
rem Both secrets are stored in MXB's encrypted vault on this PC, never in config.json.
cd /d "%~dp0\.."
set PYTHONUTF8=1
call .\.venv\Scripts\activate.bat
python -u -m engine.proactive --setup
pause
