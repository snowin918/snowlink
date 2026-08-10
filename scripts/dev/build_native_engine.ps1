# Build snowlink_engine.dll with VS 2022 + CMake (MSVC).
# Usage (from repo root):
#   powershell -ExecutionPolicy Bypass -File scripts/dev/build_native_engine.ps1
#   powershell -ExecutionPolicy Bypass -File scripts/dev/build_native_engine.ps1 -Config Debug

param(
    [ValidateSet("Release", "Debug", "RelWithDebInfo")]
    [string]$Config = "Release"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..\..")
$NativeRoot = Join-Path $RepoRoot "native"
$BuildDir = Join-Path $NativeRoot "build"

$CMakeCandidates = @(
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Community\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Professional\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\Enterprise\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "${env:ProgramFiles}\Microsoft Visual Studio\2022\BuildTools\Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe",
    "${env:ProgramFiles}\CMake\bin\cmake.exe"
)

$CMake = $null
foreach ($candidate in $CMakeCandidates) {
    if (Test-Path $candidate) {
        $CMake = $candidate
        break
    }
}
if (-not $CMake) {
    $cmd = Get-Command cmake -ErrorAction SilentlyContinue
    if ($cmd) { $CMake = $cmd.Source }
}
if (-not $CMake) {
    throw "cmake.exe not found. Install Visual Studio 2022 C++ workload or CMake."
}

Write-Host "Using CMake: $CMake"
Write-Host "Configure: $NativeRoot -> $BuildDir"

& $CMake -S $NativeRoot -B $BuildDir -G "Visual Studio 17 2022" -A x64
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed ($LASTEXITCODE)" }

& $CMake --build $BuildDir --config $Config
if ($LASTEXITCODE -ne 0) { throw "CMake build failed ($LASTEXITCODE)" }

$Dll = Join-Path $BuildDir "bin\$Config\snowlink_engine.dll"
if (-not (Test-Path $Dll)) {
    $Alt = Join-Path $BuildDir "bin\snowlink_engine.dll"
    if (Test-Path $Alt) { $Dll = $Alt }
}
if (-not (Test-Path $Dll)) {
    throw "Build succeeded but snowlink_engine.dll was not found under $BuildDir\bin"
}

Write-Host "Built: $Dll"
Write-Host "Python loader searches this path automatically (or set SNOWLINK_ENGINE_DLL)."
