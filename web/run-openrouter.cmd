@echo off
rem Winnow + OpenRouter (free model with tool calling). The key is asked at
rem startup and is kept only in this process; nothing is written to the project.
setlocal
cd /d "%~dp0.."

if "%OPENROUTER_API_KEY%"=="" set /p OPENROUTER_API_KEY=OpenRouter API key: 
if "%WINNOW_AI_KEY%"=="" set "WINNOW_AI_KEY=%OPENROUTER_API_KEY%"
if "%WINNOW_AI_MODEL%"=="" set "WINNOW_AI_MODEL=dots-studio/dots-3-note-preview:free"
set "WINNOW_AI_PROVIDER=openrouter"
if "%WINNOW_PORT%"=="" set "WINNOW_PORT=8010"

call "%~dp0run.cmd"
