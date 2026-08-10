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

$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (Test-Path $VenvPython) {
    $PythonExe = $VenvPython
} else {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        Write-Error "python not found. Create .venv or install Python."
    }
    $PythonExe = $python.Source
}

Write-Host "Python: $(& $PythonExe -c 'import sys; print(sys.executable)')"

Write-Host "Building native Release engine and runtime dependencies..."
& powershell -ExecutionPolicy Bypass -File `
    (Join-Path $RepoRoot "scripts\dev\build_native_engine.ps1") -Config Release
if ($LASTEXITCODE -ne 0) {
    Write-Error "Native Release build failed ($LASTEXITCODE)"
}

Write-Host "Checking GUI + packaging dependencies..."
& $PythonExe -c "import PyInstaller, PySide6, snowlink"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Missing packaging dependencies. Run: .\.venv\Scripts\python.exe -m pip install -e `".[dev,ui,capture,audio,webrtc]`""
}

$spec = Join-Path $RepoRoot "packaging\snowlink-gui.spec"
if (-not (Test-Path $spec)) {
    Write-Error "Missing spec file: $spec"
}

$dist = Join-Path $RepoRoot "packaging\dist"
$work = Join-Path $RepoRoot "packaging\build"

Write-Host "Running PyInstaller (windowed onedir)..."
& $PythonExe -m PyInstaller `
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
Write-Host "The folder includes the native media engine. Copy the entire Snowlink folder."
