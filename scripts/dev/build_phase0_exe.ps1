# Build the Phase 0 console exe (Experiments A + B only).
#
# Usage (from repo root, with venv activated):
#   .\scripts\dev\build_phase0_exe.ps1
#
# Output:
#   packaging\dist\snowlink-phase0.exe
#
# This does NOT freeze the PySide6 product GUI. Run the GUI with:
#   pip install -e ".[ui]"
#   python -m snowlink

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

Write-Host "Repository: $RepoRoot"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python not found on PATH. Activate the project venv first."
}

Write-Host "Python: $(python -c 'import sys; print(sys.executable)')"

Write-Host "Ensuring PyInstaller is available (pip install -e `".[dev]`")..."
python -m pip install -e ".[dev]" | Out-Host

$spec = Join-Path $RepoRoot "packaging\snowlink-phase0.spec"
if (-not (Test-Path $spec)) {
    Write-Error "Missing spec file: $spec"
}

$dist = Join-Path $RepoRoot "packaging\dist"
$work = Join-Path $RepoRoot "packaging\build"

Write-Host "Running PyInstaller..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $dist `
    --workpath $work `
    $spec

$exe = Join-Path $dist "snowlink-phase0.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build finished but exe not found at $exe"
}

Write-Host ""
Write-Host "Built: $exe"
Write-Host "This exe is console-only for Experiments A and B."
Write-Host "Product GUI is not packaged — use: python -m snowlink"
