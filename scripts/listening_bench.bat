@echo off
rem Measures how well MXB hears voice commands on this PC. Nobody needs to talk: Windows' own
rem voice says six commands at a quiet-microphone level, mixed with 6 s of noise recorded from your mic.
rem Results: logs\listening_bench.log (and .json). See scripts\listening_bench.py for options.
cd /d "%~dp0\.."
set PYTHONUTF8=1
if not exist logs mkdir logs
call .\.venv\Scripts\activate.bat
echo MXB listening bench - %DATE% %TIME% > logs\listening_bench.log
echo. >> logs\listening_bench.log
echo === Without input gain === >> logs\listening_bench.log
python -u -m scripts.listening_bench --gain off --out logs\listening_bench_gain_off.json >> logs\listening_bench.log 2>&1
echo. >> logs\listening_bench.log
echo === With input gain (default) === >> logs\listening_bench.log
python -u -m scripts.listening_bench --out logs\listening_bench.json >> logs\listening_bench.log 2>&1
echo BENCH FINISHED >> logs\listening_bench.log
type logs\listening_bench.log
timeout /t 60
