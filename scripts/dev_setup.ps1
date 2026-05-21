<#
.SYNOPSIS
    Agno Development Setup

.DESCRIPTION
    Create a virtual environment and install libraries in editable mode.
    Please install uv before running this script.
    Please deactivate the existing virtual environment before running.

.EXAMPLE
    .\scripts\dev_setup.ps1
#>

$ErrorActionPreference = "Stop"

$CurrDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $CurrDir
$AgnoDir = Join-Path $RepoRoot "libs\agno"
$AgnoInfraDir = Join-Path $RepoRoot "libs\agno_infra"
$VenvDir = Join-Path $RepoRoot ".venv"

function Print-Heading {
    param([string]$Message)
    Write-Host ""
    Write-Host "------------------------------------------------------------"
    Write-Host "-*- $Message"
    Write-Host "------------------------------------------------------------"
}

function Print-Info {
    param([string]$Message)
    Write-Host "-*- $Message"
}

Print-Heading "Development setup..."

# Preflight
if ($env:VIRTUAL_ENV) {
    Write-Host "Deactivate your current venv first."
    exit 1
}

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host "uv not found. Install: https://docs.astral.sh/uv/"
    exit 1
}

Print-Heading "Removing virtual env"
Print-Info "Remove-Item -Recurse -Force $VenvDir"
if (Test-Path $VenvDir) {
    Remove-Item -Path $VenvDir -Recurse -Force
}

Print-Heading "Creating virtual env"
Print-Info "uv venv $VenvDir --python 3.12"
uv venv $VenvDir --python 3.12
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Print-Heading "Installing agno"
Print-Info "VIRTUAL_ENV=$VenvDir uv pip install -r $AgnoDir\requirements.txt"
$env:VIRTUAL_ENV = $VenvDir
uv pip install -r "$AgnoDir\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Print-Heading "Installing agno in editable mode with dev dependencies"
Print-Info "VIRTUAL_ENV=$VenvDir uv pip install -U -e $AgnoDir[dev]"
uv pip install -U -e "${AgnoDir}[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Print-Heading "Installing agno-infra"
Print-Info "VIRTUAL_ENV=$VenvDir uv pip install -r $AgnoInfraDir\requirements.txt"
uv pip install -r "$AgnoInfraDir\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Print-Heading "Installing agno-infra in editable mode with dev dependencies"
Print-Info "VIRTUAL_ENV=$VenvDir uv pip install -U -e $AgnoInfraDir[dev]"
uv pip install -U -e "${AgnoInfraDir}[dev]"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Print-Heading "uv pip list"
uv pip list

# Clear VIRTUAL_ENV
$env:VIRTUAL_ENV = $null

Print-Heading "Development setup complete"
Print-Heading "Activate venv using: .\.venv\Scripts\Activate.ps1"
