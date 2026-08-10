# Build and run the two-process native media acceptance harness.
# Opens a small local viewer window and captures the current desktop.

param(
    [double]$Duration = 15,
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $Python)) {
    throw "Virtual environment Python not found: $Python"
}

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "build_native_engine.ps1") -Config Release
    if ($LASTEXITCODE -ne 0) { throw "Native engine build failed ($LASTEXITCODE)" }
}

& $Python (Join-Path $RepoRoot "tools\native_loopback_harness.py") --duration $Duration
if ($LASTEXITCODE -ne 0) { throw "Native loopback acceptance test failed ($LASTEXITCODE)" }

Write-Host "Native two-process loopback acceptance test passed."
