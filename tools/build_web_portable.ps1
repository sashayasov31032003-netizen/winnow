# Сборка переносимой веб-версии Winnow (Windows).
#
#   powershell -ExecutionPolicy Bypass -File tools\build_web_portable.ps1
#
# Что получается в dist-web:
#   Winnow-web.exe            один файл — проще передать, дольше запускается
#   Winnow-web\               каталог — быстрее запускается, рядом лежат данные
#   Winnow-web-portable.zip   архив каталога для переноса на другую машину
#
# Перед сборкой нужен собранный интерфейс: web\frontend\dist.
# Если его нет, скрипт напомнит, как собрать. Данные пользователя в собранном
# виде лежат в папке web рядом с exe и при обновлении сборки не теряются, пока
# эта папка не удалена.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$venv = Join-Path $root "web\.venv\Scripts\python.exe"
$frontend = Join-Path $root "web\frontend\dist\index.html"

if (-not (Test-Path $venv)) {
    Write-Host "Не найдено окружение: $venv" -ForegroundColor Red
    Write-Host "Создайте его: python -m venv --system-site-packages web\.venv"
    Write-Host "Затем: web\.venv\Scripts\python -m pip install -r web\requirements.txt"
    exit 1
}

if (-not (Test-Path $frontend)) {
    Write-Host "Интерфейс не собран: нет web\frontend\dist\index.html" -ForegroundColor Red
    Write-Host "Соберите: cd web\frontend; npm.cmd run build"
    exit 1
}

$env:PYTHONPATH = Join-Path $root "src"
Set-Location $root

Write-Host "1/3 Каталог Winnow-web..." -ForegroundColor Cyan
& $venv -m PyInstaller --noconfirm --clean `
    --workpath build\web-dir --distpath dist-web winnow-web-dir.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "2/3 Один файл Winnow-web.exe..." -ForegroundColor Cyan
& $venv -m PyInstaller --noconfirm --clean `
    --workpath build\web-onefile --distpath dist-web winnow-web.spec
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "3/3 README и архив для переноса..." -ForegroundColor Cyan
$folder = Join-Path $root "dist-web\Winnow-web"
$zip = Join-Path $root "dist-web\Winnow-web-portable.zip"

# README кладём в саму папку: PyInstaller пересоздаёт её при каждой сборке,
# поэтому текст пишется здесь, а не руками один раз.
$readme = @"
Winnow - веб-версия, переносимая сборка
=======================================

Запуск
------
Двойной щелчок по Winnow-web.exe. Сервер поднимется на http://127.0.0.1:8000/
и сам откроет браузер. Окно консоли закрывать нельзя: это и есть сервер.

Где данные
----------
База (аккаунты, опросы, ответы, наборы) и загруженные файлы лежат в папке web\
рядом с exe. Чтобы перенести всё вместе с данными, копируйте папку целиком.

Настройки (необязательно)
-------------------------
Перед запуском в командной строке:

  set WINNOW_PORT=8080          другой порт
  set WINNOW_HOST=0.0.0.0       доступ с других машин в сети
  set WINNOW_INVITE_ONLY=0      свободная регистрация (по умолчанию по приглашению)
  set WINNOW_SECRET=длинная-строка   свой ключ подписи сессий;
                                для доступа из интернета обязателен

Если Windows пишет "Could not create temporary directory"
---------------------------------------------------------
Это бывает только у однофайловой сборки (Winnow-web.exe без папки _internal):
она распаковывается во временную папку. Укажите свою:

  set TMP=%CD%\tmp
  set TEMP=%CD%\tmp
  Winnow-web.exe

У версии-каталога (эта папка) такой проблемы нет.
"@
Set-Content -Path (Join-Path $folder "README.txt") -Value $readme -Encoding UTF8

if (Test-Path $zip) { Remove-Item $zip -Force }
Add-Type -AssemblyName System.IO.Compression.FileSystem
[System.IO.Compression.ZipFile]::CreateFromDirectory(
    $folder,
    $zip,
    [System.IO.Compression.CompressionLevel]::Optimal,
    $true
)

Get-ChildItem (Join-Path $root "dist-web") |
    Select-Object LastWriteTime, @{n = "МБ"; e = { [math]::Round($_.Length / 1MB, 1) } }, Name |
    Format-Table -AutoSize
Write-Host "Готово. Архив: $zip" -ForegroundColor Green
