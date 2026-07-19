#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup script for Windows Server 2022 to run BGA scraper and publish to Google BigQuery.

.DESCRIPTION
    Installs Python 3.12, pip dependencies (Playwright, BigQuery client, etc.),
    Playwright Chromium browser, and Google Chrome.
    Run this once as Administrator before using main.py or run.py.
#>

$ErrorActionPreference = "Stop"

Write-Host "=== BGA Scraper Setup for Windows Server 2022 ===" -ForegroundColor Cyan

# --- 1. Install Python via winget (or check if already installed) ---
Write-Host "`n[1/5] Checking Python installation..." -ForegroundColor Yellow

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    $pyVersion = & python --version 2>&1
    Write-Host "  Python already installed: $pyVersion" -ForegroundColor Green
} else {
    Write-Host "  Installing Python 3.12..." -ForegroundColor Yellow

    # Download Python installer
    $pyUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $pyInstaller = "$env:TEMP\python-installer.exe"
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $pyUrl -OutFile $pyInstaller -UseBasicParsing

    # Silent install: add to PATH, install pip, install for all users
    & $pyInstaller /quiet InstallAllUsers=1 PrependPath=1 Include_pip=1 | Out-Null

    # Refresh PATH for current session
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machinePath;$userPath"

    Remove-Item $pyInstaller -Force -ErrorAction SilentlyContinue

    $pyVersion = & python --version 2>&1
    Write-Host "  Installed: $pyVersion" -ForegroundColor Green
}

# --- 2. Install Google Chrome (needed by Playwright channel="chrome") ---
Write-Host "`n[2/5] Checking Google Chrome installation..." -ForegroundColor Yellow

$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
if (Test-Path $chromePath) {
    Write-Host "  Google Chrome already installed." -ForegroundColor Green
} else {
    Write-Host "  Installing Google Chrome..." -ForegroundColor Yellow
    $chromeUrl = "https://dl.google.com/chrome/install/latest/chrome_installer.exe"
    $chromeInstaller = "$env:TEMP\chrome_installer.exe"
    Invoke-WebRequest -Uri $chromeUrl -OutFile $chromeInstaller -UseBasicParsing
    Start-Process -FilePath $chromeInstaller -Args "/silent /install" -Wait
    Remove-Item $chromeInstaller -Force -ErrorAction SilentlyContinue
    Write-Host "  Google Chrome installed." -ForegroundColor Green
}

# --- 3. Install pip dependencies ---
Write-Host "`n[3/5] Installing pip dependencies..." -ForegroundColor Yellow

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$requirementsFile = Join-Path $scriptDir "requirements.txt"

if (-not (Test-Path $requirementsFile)) {
    Write-Host "  ERROR: requirements.txt not found at $requirementsFile" -ForegroundColor Red
    exit 1
}

& python -m pip install --upgrade pip
& python -m pip install -r $requirementsFile

# Install Google BigQuery dependencies
& python -m pip install google-cloud-bigquery google-auth

Write-Host "  pip dependencies installed." -ForegroundColor Green

# --- 4. Install Playwright browsers ---
Write-Host "`n[4/5] Installing Playwright Chromium browser..." -ForegroundColor Yellow
& python -m playwright install chromium
Write-Host "  Playwright Chromium installed." -ForegroundColor Green

# --- 5. Verify installation ---
Write-Host "`n[5/5] Verifying installation..." -ForegroundColor Yellow

$checks = @(
    @{ Name = "Python";              Cmd = "python --version" },
    @{ Name = "pip";                 Cmd = "python -m pip --version" },
    @{ Name = "playwright";          Cmd = "python -c `"import playwright; print('playwright', playwright.__version__)`"" },
    @{ Name = "python-dotenv";       Cmd = "python -c `"import dotenv; print('python-dotenv OK')`"" },
    @{ Name = "google-cloud-bigquery"; Cmd = "python -c `"from google.cloud import bigquery; print('google-cloud-bigquery OK')`"" }
)

$allOk = $true
foreach ($check in $checks) {
    try {
        $result = Invoke-Expression $check.Cmd 2>&1
        Write-Host "  [OK] $($check.Name): $result" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $($check.Name)" -ForegroundColor Red
        $allOk = $false
    }
}

if (Test-Path $chromePath) {
    Write-Host "  [OK] Google Chrome" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Google Chrome not found" -ForegroundColor Red
    $allOk = $false
}

Write-Host ""
if ($allOk) {
    Write-Host "=== Setup complete! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Copy .env.example to .env and fill in BGA_EMAIL and BGA_PASSWORD"
    Write-Host "  2. For BigQuery: set GOOGLE_APPLICATION_CREDENTIALS env var to your service account JSON key"
    Write-Host "  3. Run:  python main.py <player_id>"
    Write-Host "     Or:   python run.py <table_id1,table_id2,...>"
} else {
    Write-Host "=== Setup completed with errors. Review above. ===" -ForegroundColor Red
}
