# Build the Snowlink windowed GUI app (PySide6 onedir).
#
# Usage (from repo root, with venv activated):
#   .\scripts\dev\build_gui_exe.ps1
#
# Output:
#   packaging\dist\Snowlink\Snowlink.exe
#
# For Diagnostics capture / WebRTC tabs, install extras before building:
#   pip install -e ".[dev,ui,capture,audio,webrtc]"

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $RepoRoot

Write-Host "Repository: $RepoRoot"

$python = Get-Command python -ErrorAction SilentlyContinue
if (-not $python) {
    Write-Error "python not found on PATH. Activate the project venv first."
}

Write-Host "Python: $(python -c 'import sys; print(sys.executable)')"

Write-Host "Ensuring GUI + packaging deps..."
python -m pip install -e ".[dev,ui]" | Out-Host

$spec = Join-Path $RepoRoot "packaging\snowlink-gui.spec"
if (-not (Test-Path $spec)) {
    Write-Error "Missing spec file: $spec"
}

$dist = Join-Path $RepoRoot "packaging\dist"
$work = Join-Path $RepoRoot "packaging\build"

Write-Host "Running PyInstaller (windowed onedir)..."
python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $dist `
    --workpath $work `
    $spec

$exe = Join-Path $dist "Snowlink\Snowlink.exe"
if (-not (Test-Path $exe)) {
    Write-Error "Build finished but exe not found at $exe"
}

Write-Host ""
Write-Host "Built GUI app folder: $(Join-Path $dist 'Snowlink')"
Write-Host "Launch: $exe"
Write-Host "Distribute the whole Snowlink\ folder (onedir), not only the exe."
Write-Host "LAN Share/View streaming is still Phase 1 (not ready)."
