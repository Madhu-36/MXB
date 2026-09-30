@echo off
echo Building the custom MXB-Brain model via Ollama...
echo Ensure Ollama is installed and running before executing this!
echo.
cd /d "%~dp0"
ollama create mxb-brain -f Modelfile
echo.
echo Done! MXB is now equipped with its own specialized LLM.
pause
