@echo off
rem Winnow + local Ollama: no key, no network, data stays on this computer.
rem Install Ollama first, then: ollama pull qwen3:8b
setlocal
cd /d "%~dp0.."

if "%WINNOW_AI_MODEL%"=="" set "WINNOW_AI_MODEL=qwen3:8b"
set "WINNOW_AI_PROVIDER=ollama"
if "%WINNOW_PORT%"=="" set "WINNOW_PORT=8010"

call "%~dp0run.cmd"
