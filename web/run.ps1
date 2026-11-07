# Запуск веб-приложения Winnow. Работает из любой папки.
#
#   powershell -ExecutionPolicy Bypass -File web\run.ps1   (из папки проекта)
#
# -Reload включает автоперезапуск при изменении кода (для разработки).
# -NoBrowser не открывает браузер автоматически.

param([switch]$Reload, [switch]$NoBrowser)

$ErrorActionPreference = 'Stop'

$web = $PSScriptRoot
$root = Split-Path -Parent $web
$python = Join-Path $web '.venv\Scripts\python.exe'

if (-not (Test-Path $python)) {
    Write-Host 'Окружение не найдено. Выполните в папке проекта:' -ForegroundColor Yellow
    Write-Host '  python -m venv --system-site-packages web\.venv'
    Write-Host '  web\.venv\Scripts\python -m pip install -r web\requirements.txt'
    exit 1
}

$env:PYTHONPATH = Join-Path $root 'src'
Set-Location $root
if ($NoBrowser) { $env:WINNOW_OPEN_BROWSER = '0' }

if ($Reload) {
    $arguments = @('-m', 'uvicorn', 'winnow.web.main:app', '--port', '8000', '--reload')
} else {
    $arguments = @('-m', 'winnow.web')
}
& $python @arguments
