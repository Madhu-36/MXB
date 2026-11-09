@echo off
rem Gives MXB a stronger local brain: downloads the recommended model through Ollama (about 2.5 GB),
rem benchmarks it against the current one (plans only, nothing is executed) and switches config.json
rem only if it scores at least as well. Needs Ollama running.
cd /d "%~dp0\.."
set PYTHONUTF8=1
call .\.venv\Scripts\activate.bat
if not exist logs mkdir logs
python -u -m utils.model_setup --pull --compare --switch
pause
