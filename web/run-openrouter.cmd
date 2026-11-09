@echo off
rem Winnow + OpenRouter (DeepSeek R1 free). The key is asked at startup and is
rem kept only in this process; nothing is written to the project.
setlocal
cd /d "%~dp0.."

if "%OPENROUTER_API_KEY%"=="" set /p OPENROUTER_API_KEY=OpenRouter API key: 
if "%WINNOW_AI_KEY%"=="" set "WINNOW_AI_KEY=%OPENROUTER_API_KEY%"
if "%WINNOW_AI_MODEL%"=="" set "WINNOW_AI_MODEL=deepseek/deepseek-r1:free"
set "WINNOW_AI_PROVIDER=openrouter"
if "%WINNOW_PORT%"=="" set "WINNOW_PORT=8010"

call "%~dp0run.cmd"
