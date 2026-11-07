@echo off
rem Winnow + VseGPT: asks for the API key at startup and does not save it.
rem The key lives only in this process; nothing is written to the project.
setlocal
cd /d "%~dp0.."

if "%WINNOW_AI_KEY%"=="" set /p WINNOW_AI_KEY=VseGPT API key: 
if "%WINNOW_AI_MODEL%"=="" set "WINNOW_AI_MODEL=openai/gpt-4o-mini"
set "WINNOW_AI_PROVIDER=vsegpt"
if "%WINNOW_PORT%"=="" set "WINNOW_PORT=8010"

call "%~dp0run.cmd"
