# Run from an elevated PowerShell prompt. This script only adds narrowly scoped
# inbound Private-profile rules; it never disables Windows Firewall.
[CmdletBinding()]
param(
    [string]$Executable = "",
    [int]$SignalingPort = 3847,
    [string]$MediaUdpRange = "40000-40100"
)

$ErrorActionPreference = "Stop"

if (-not $Executable) {
    $PortableExecutable = Join-Path $PSScriptRoot "..\Snowlink.exe"
    if (Test-Path -LiteralPath $PortableExecutable -PathType Leaf) {
        $Executable = $PortableExecutable
    } else {
        $Executable = Join-Path $PSScriptRoot "..\..\packaging\dist\Snowlink\Snowlink.exe"
    }
}
$Executable = [System.IO.Path]::GetFullPath($Executable)
if (-not (Test-Path -LiteralPath $Executable -PathType Leaf)) {
    throw "Snowlink executable not found: $Executable"
}

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run this script from an elevated PowerShell prompt (Run as administrator)."
}

$rules = @(
    @{
        DisplayName = "Snowlink LAN signaling (TCP)"
        Protocol = "TCP"
        LocalPort = [string]$SignalingPort
    },
    @{
        DisplayName = "Snowlink LAN media (UDP)"
        Protocol = "UDP"
        LocalPort = $MediaUdpRange
    }
)

foreach ($rule in $rules) {
    Get-NetFirewallRule -DisplayName $rule.DisplayName -ErrorAction SilentlyContinue |
        Remove-NetFirewallRule
    New-NetFirewallRule `
        -DisplayName $rule.DisplayName `
        -Direction Inbound `
        -Action Allow `
        -Profile Private `
        -Program $Executable `
        -Protocol $rule.Protocol `
        -LocalPort $rule.LocalPort `
        -RemoteAddress LocalSubnet | Out-Null
    Write-Host "Installed: $($rule.DisplayName)"
}

Write-Host "Allowed executable: $Executable"
Write-Host "TCP signaling: $SignalingPort; UDP media: $MediaUdpRange; profile: Private"
