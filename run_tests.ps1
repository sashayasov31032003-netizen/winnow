# Запуск тестов Winnow.
#
#   powershell -File run_tests.ps1          # все тесты движка
#   powershell -File run_tests.ps1 -Fast    # без тестов Word и Excel
#
# Веб-тесты запускаются отдельно из окружения web\.venv:
#   web\.venv\Scripts\python -m pytest web\tests -q
#
# Скрипт сам выбирает интерпретатор, в котором есть pytest, scipy и numpy:
# в системе их несколько, и "просто python" может оказаться неподходящим.

param(
    [switch]$Fast
)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot

$candidates = @(
    "python",
    "py",
    "D:\ds\deepseekk\resources\runtime\primary-runtime\dependencies\python\python.exe",
    "C:\Users\dance\AppData\Local\Programs\Python\Python313\python.exe"
)

# Проверяем не только наличие файла, но и что в нём есть нужные пакеты.
$probe = "import importlib.util as u, sys; sys.exit(0 if all(u.find_spec(m) for m in ('pytest','scipy','numpy')) else 1)"

$python = $null
foreach ($candidate in $candidates) {
    if ($candidate -match '\\') {
        if (Test-Path $candidate) { $exe = $candidate } else { continue }
    }
    else {
        $found = Get-Command $candidate -ErrorAction SilentlyContinue
        if (-not $found) { continue }
        $exe = $found.Source
    }

    & $exe -c $probe 2>$null
    if ($LASTEXITCODE -eq 0) {
        $python = $exe
        break
    }
}

if (-not $python) {
    Write-Host "Не найден интерпретатор с пакетами pytest, scipy и numpy." -ForegroundColor Red
    Write-Host "Установите их, например:"
    Write-Host '  python -m pip install pytest scipy numpy pandas'
    exit 1
}

Write-Host "Python: $python" -ForegroundColor Cyan
$env:PYTHONPATH = Join-Path $root "src"
$env:PYTHONIOENCODING = "utf-8"
Push-Location $root
$testCode = 1
try {
    if ($Fast) {
        $skip = Join-Path $root "tests\test_export_and_engine.py"
        & $python -B -m pytest -q --ignore=$skip
    }
    else {
        & $python -B -m pytest -q
    }
    $testCode = $LASTEXITCODE
}
finally {
    Pop-Location
}

exit $testCode