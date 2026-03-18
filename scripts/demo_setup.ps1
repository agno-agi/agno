<#
.SYNOPSIS
    Agno Demo Environment Setup

.DESCRIPTION
    Usage: .\scripts\demo_setup.ps1
    Run:   python cookbook/01_demo/run.py
#>

$ErrorActionPreference = "Stop"

$CurrDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $CurrDir
$AgnoDir = Join-Path $RepoRoot "libs\agno"
$VenvDir = Join-Path $RepoRoot ".venvs\demo"

$ESC = [char]27
$Orange = "$ESC[38;5;208m"
$Reset = "$ESC[0m"

Write-Host ""
Write-Host "$Orange     █████╗  ██████╗ ███╗   ██╗ ██████╗$Reset"
Write-Host "$Orange    ██╔══██╗██╔════╝ ████╗  ██║██╔═══██╗$Reset"
Write-Host "$Orange    ███████║██║  ███╗██╔██╗ ██║██║   ██║$Reset"
Write-Host "$Orange    ██╔══██║██║   ██║██║╚██╗██║██║   ██║$Reset"
Write-Host "$Orange    ██║  ██║╚██████╔╝██║ ╚████║╚██████╔╝$Reset"
Write-Host "$Orange    ╚═╝  ╚═╝ ╚═════╝ ╚═╝  ╚═══╝ ╚═════╝$Reset"
Write-Host "    Demo Environment Setup" -ForegroundColor Gray
Write-Host ""

# Preflight
if ($env:VIRTUAL_ENV) {
    Write-Host "    Deactivate your current venv first."
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "    uv not found. Install: https://docs.astral.sh/uv/"
    exit 1
}

# Setup
Write-Host "    Removing old environment..." -ForegroundColor Gray
Write-Host "    > Remove-Item -Recurse -Force $VenvDir" -ForegroundColor Gray
if (Test-Path $VenvDir) {
    Remove-Item -Path $VenvDir -Recurse -Force
}

Write-Host ""
Write-Host "    Creating Python 3.12 venv..." -ForegroundColor Gray
Write-Host "    > uv venv $VenvDir --python 3.12" -ForegroundColor Gray
uv venv $VenvDir --python 3.12 --quiet
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ""
Write-Host "    Installing agno[demo]..." -ForegroundColor Gray
Write-Host "    > uv pip install -e ${AgnoDir}[demo]" -ForegroundColor Gray

# Set VIRTUAL_ENV for the install command
$OldVenv = $env:VIRTUAL_ENV
$env:VIRTUAL_ENV = $VenvDir
try {
    uv pip install -e "${AgnoDir}[demo]" --quiet
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} finally {
    $env:VIRTUAL_ENV = $OldVenv
}

# Copy activation command to clipboard
$ActivateCmd = ".venvs\demo\Scripts\activate"
$ActivateCmd | Set-Clipboard

Write-Host ""
Write-Host "    Done." -ForegroundColor White
Write-Host ""
Write-Host "    Activate:  $ActivateCmd" -ForegroundColor Gray
Write-Host "    Run Demo:  python cookbook/01_demo/run.py" -ForegroundColor Gray
Write-Host ""
Write-Host "    (Activation command copied to clipboard. Just paste and hit enter.)" -ForegroundColor Gray
Write-Host ""