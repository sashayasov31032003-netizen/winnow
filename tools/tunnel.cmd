@echo off
rem Cloudflare quick tunnel to the locally running Winnow web app.
rem Start the server first (Winnow-web.exe or web\run.cmd), then run this.
setlocal
cd /d "%~dp0.."

if not exist "tools\cloudflared.exe" (
    echo cloudflared.exe not found in tools\\. Download it from:
    echo   https://github.com/cloudflare/cloudflared/releases/latest
    pause
    exit /b 1
)

echo.
echo   Public link appears below - send it to the person you show the app to.
echo   Keep this window open. Ctrl+C stops the tunnel.
echo.
"tools\cloudflared.exe" tunnel --url http://127.0.0.1:8000 --no-autoupdate
pause
