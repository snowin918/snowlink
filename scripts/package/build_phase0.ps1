# Build portable Phase 0 exe (Experiments A + B).
# Run from repository root:
#   powershell -File scripts\package\build_phase0.ps1

$ErrorActionPreference = "Stop"
$Root = Resolve-Path (Join-Path $PSScriptRoot "..\..")
Set-Location $Root

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
    Write-Error "Create and activate a venv first (py -3.12 -m venv .venv)."
}

. .\.venv\Scripts\Activate.ps1

python -m pip install -q -e ".[dev]"
python -m pip install -q "pyinstaller>=6.0"

$Dist = Join-Path $Root "packaging\dist"
$Work = Join-Path $Root "packaging\build"
New-Item -ItemType Directory -Force -Path $Dist | Out-Null
New-Item -ItemType Directory -Force -Path $Work | Out-Null

python -m PyInstaller `
    --noconfirm `
    --clean `
    --distpath $Dist `
    --workpath $Work `
    (Join-Path $Root "packaging\snowlink-phase0.spec")

$Exe = Join-Path $Dist "snowlink-phase0.exe"
if (-not (Test-Path $Exe)) {
    Write-Error "Build finished but exe not found: $Exe"
}

Write-Host ""
Write-Host "Built: $Exe"
Write-Host "Copy snowlink-phase0.exe to the other PC (no Python install required)."
Write-Host ""
Write-Host "Examples on the other PC:"
Write-Host "  .\snowlink-phase0.exe a list"
Write-Host "  .\snowlink-phase0.exe b guide"
Write-Host "  .\snowlink-phase0.exe b serve --ip <LAN-IP> --port 3847 --session-name vpn-off-off --serve-forever"
Write-Host "  .\snowlink-phase0.exe b connect --ip <A-LAN-IP> --session-name vpn-off-off --source-ip <B-LAN-IP>"
