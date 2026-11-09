@echo off
rem One-click setup and self-check for MXB on Windows (double-click it).
rem 1. installs requirements.txt into .venv (creates .venv if there isn't one)
rem 2. runs the cross-platform test suites
rem 3. runs the Windows integration check (python -m utils.windows_check)
rem Everything goes to logs\setup_and_check.log. Nothing is pressed, spoken, or recorded to disk.
setlocal
cd /d "%~dp0.."
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
if not exist logs mkdir logs
set "LOG=%CD%\logs\setup_and_check.log"
echo MXB setup and check, started %date% %time% > "%LOG%"
if not exist ".venv\Scripts\python.exe" (
    echo Creating .venv ... >> "%LOG%"
    py -3 -m venv .venv >> "%LOG%" 2>&1 || python -m venv .venv >> "%LOG%" 2>&1
)
set "PY=.venv\Scripts\python.exe"
echo Installing packages (a few minutes the first time) ...
echo === pip >> "%LOG%"
"%PY%" -m pip install --upgrade pip >> "%LOG%" 2>&1
"%PY%" -m pip install -r requirements.txt >> "%LOG%" 2>&1
echo PIP_EXIT=%ERRORLEVEL% >> "%LOG%"
echo Running the test suites ...
echo === tests >> "%LOG%"
"%PY%" scripts\verify_all.py --portable >> "%LOG%" 2>&1
echo TESTS_EXIT=%ERRORLEVEL% >> "%LOG%"
echo Checking the Windows integrations ...
echo === windows check >> "%LOG%"
"%PY%" -m utils.windows_check >> "%LOG%" 2>&1
echo CHECK_EXIT=%ERRORLEVEL% >> "%LOG%"
echo === done %date% %time% >> "%LOG%"
echo.
findstr /b /c:"PIP_EXIT" /c:"TESTS_EXIT" /c:"CHECK_EXIT" /c:"VERIFICATION SUMMARY" /c:"FAIL " "%LOG%"
echo.
echo Full results: %LOG%
pause
