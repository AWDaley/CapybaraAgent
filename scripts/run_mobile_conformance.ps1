param(
    [switch]$SkipPython,
    [switch]$SkipKotlin
)

$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $taskRoot '.venv\Scripts\python.exe'
$mobileRoot = Join-Path $taskRoot 'mobile'

if (-not $SkipPython) {
    & $pythonPath -m pytest tests\test_mobile_profile_contracts.py tests\test_mobile_simulator.py -q
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

if (-not $SkipKotlin) {
    Push-Location $mobileRoot
    try {
        & .\gradlew.bat :tal-core:test --no-daemon
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    finally {
        Pop-Location
    }
}

Write-Output 'Mobile Python/Kotlin conformance checks passed.'
