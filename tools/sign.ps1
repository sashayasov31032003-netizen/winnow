<#
    Подпись собранных файлов Winnow сертификатом.

    Зачем подпись: Windows показывает предупреждение «Windows защитила ваш
    компьютер» для программ без подписи. Что даёт подпись на самом деле:

      * КУПЛЕННЫЙ сертификат (OV или EV) - убирает предупреждение. У OV оно
        уходит не сразу, а по мере набора репутации; у EV - сразу;
      * САМОПОДПИСАННЫЙ сертификат (этот скрипт умеет его создать) -
        предупреждение НЕ убирает. Он подтверждает целостность файла и годится
        для проверки механизма и для своих компьютеров, где сертификат добавлен
        в доверенные. На чужом компьютере подпись будет считаться недоверенной.

    Поэтому для диплома самоподписи достаточно, чтобы показать, как это
    делается; убирать предупреждение она не будет.

    Как запускать:

        # самоподписанным сертификатом (создастся сам, если его ещё нет)
        pwsh -File tools\sign.ps1

        # купленным сертификатом из файла .pfx
        pwsh -File tools\sign.ps1 -Pfx C:\cert\winnow.pfx -PfxPassword "пароль"

        # сертификатом, который уже лежит в хранилище
        pwsh -File tools\sign.ps1 -Thumbprint 3B3FD9B8...

    Порядок работы: СНАЧАЛА сборка, ПОТОМ подпись. Любая правка файла после
    подписи ломает подпись, и её нужно наложить заново.
#>

[CmdletBinding()]
param(
    # Путь к файлу сертификата .pfx (купленный или выданный организацией).
    [string]$Pfx,
    # Пароль от .pfx.
    [string]$PfxPassword,
    # Отпечаток сертификата в хранилище текущего пользователя.
    [string]$Thumbprint,
    # Какие файлы подписывать.
    [string[]]$Files,
    # Сервер метки времени. Без метки подпись перестаёт действовать вместе с
    # сертификатом; с меткой - остаётся действительной навсегда.
    [string]$TimestampServer = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$friendlyName = "Winnow code signing (self-signed)"
$thumbprintFile = Join-Path $PSScriptRoot ".cert-thumbprint"

if (-not $Files -or $Files.Count -eq 0) {
    $Files = @(
        (Join-Path $root "Winnow.exe"),
        (Join-Path $root "dist\Winnow\Winnow.exe")
    )
}

function Get-SigningCertificate {
    <#
        Возвращает сертификат для подписи: из .pfx, из хранилища по отпечатку
        или самоподписанный (создаётся, если его ещё нет).
    #>
    if ($Pfx) {
        if (-not (Test-Path -LiteralPath $Pfx)) {
            throw "Файл сертификата не найден: $Pfx"
        }
        $secure = ConvertTo-SecureString -String $PfxPassword -Force -AsPlainText
        # Сертификат импортируется в личное хранилище: Windows умеет подписывать
        # только сертификатом из хранилища, файл .pfx для этого не годится.
        $imported = Import-PfxCertificate -FilePath $Pfx -CertStoreLocation "Cert:\CurrentUser\My" `
            -Password $secure -Exportable
        Write-Host "Импортирован сертификат из $Pfx"
        return $imported
    }

    if ($Thumbprint) {
        $found = Get-Item "Cert:\CurrentUser\My\$Thumbprint" -ErrorAction SilentlyContinue
        if (-not $found) { throw "Сертификат с отпечатком $Thumbprint не найден в хранилище" }
        return $found
    }

    # Ищем ранее созданный самоподписанный сертификат.
    $existing = Get-ChildItem "Cert:\CurrentUser\My" |
        Where-Object { $_.FriendlyName -eq $friendlyName } |
        Sort-Object NotAfter -Descending |
        Select-Object -First 1
    if ($existing) {
        Write-Host "Используется существующий сертификат: $($existing.Subject)"
        return $existing
    }

    Write-Host "Создаётся самоподписанный сертификат для подписи кода..."
    $created = New-SelfSignedCertificate `
        -Type CodeSigningCert `
        -Subject "CN=Winnow, O=Winnow Project, C=RU" `
        -FriendlyName $friendlyName `
        -CertStoreLocation "Cert:\CurrentUser\My" `
        -KeyUsage DigitalSignature `
        -KeyAlgorithm RSA `
        -KeyLength 3072 `
        -HashAlgorithm SHA256 `
        -NotAfter (Get-Date).AddYears(5)
    Write-Host "Создан: $($created.Subject), действует до $($created.NotAfter.ToString('yyyy-MM-dd'))"
    return $created
}

$certificate = Get-SigningCertificate
$certificate.Thumbprint | Set-Content -LiteralPath $thumbprintFile -Encoding utf8

$signed = 0
$missing = 0
foreach ($file in $Files) {
    if (-not (Test-Path -LiteralPath $file)) {
        Write-Host "пропуск (файла нет): $file"
        $missing++
        continue
    }
    Write-Host "Подписываю: $file"
    try {
        $result = Set-AuthenticodeSignature -FilePath $file -Certificate $certificate `
            -HashAlgorithm SHA256 -TimestampServer $TimestampServer
        if ($result.Status -eq "Valid") {
            Write-Host "  подпись наложена и доверена"
        } else {
            # Недоверенный корень - обычное дело для самоподписанного
            # сертификата, и это не ошибка подписи: она наложена.
            Write-Host "  подпись наложена (проверка: $($result.Status))"
        }
        $signed++
    }
    catch {
        Write-Host "  ОШИБКА: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host ""
Write-Host "Подписано файлов: $signed$(if ($missing) { ", пропущено: $missing" })"
Write-Host "Отпечаток сертификата: $($certificate.Thumbprint)"
Write-Host ""
Write-Host "Что дальше:"
Write-Host "  * подпись наложена заново после КАЖДОЙ сборки; правка файла подпись ломает;"
if (-not $Pfx) {
    Write-Host "  * это самоподписанный сертификат: предупреждение Windows на чужом"
    Write-Host "    компьютере он НЕ убирает - там корень сертификата недоверенный;"
    Write-Host "  * на своих компьютерах сертификат можно сделать доверенным, добавив его"
    Write-Host "    в «Доверенные корневые центры сертификации» и «Доверенные издатели»;"
    Write-Host "  * удалить сертификат: Remove-Item Cert:\CurrentUser\My\$($certificate.Thumbprint)"
}
