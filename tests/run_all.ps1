# Runs every tests\test_*.py in turn and stops on the first failure.
# Usage, from anywhere:  powershell -ExecutionPolicy Bypass -File tests\run_all.ps1
#
# Each test is a standalone script that exits 0 or 1 (no pytest). Bytecode writing is off so that
# importing SiCoPR never leaves a .pyc inside its checkout (Rule 1).

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$env:PYTHONDONTWRITEBYTECODE = "1"
Push-Location $Root
try {
    $tests = Get-ChildItem (Join-Path $Root "tests") -Filter "test_*.py" | Sort-Object Name
    foreach ($t in $tests) {
        Write-Host ""
        Write-Host "=== $($t.Name) ==="
        python $t.FullName
        if ($LASTEXITCODE -ne 0) {
            Write-Host "FAILED: $($t.Name)"
            exit 1
        }
    }
    Write-Host ""
    Write-Host "All tests passed"
    exit 0
}
finally {
    Pop-Location
}
