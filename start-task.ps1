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

$chromePaths = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chromeFound = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($chromeFound) {
    Write-Host "  Google Chrome already installed at $chromeFound" -ForegroundColor Green
} else {
    Write-Host "  Installing Google Chrome (enterprise MSI)..." -ForegroundColor Yellow
    $chromeUrl = "https://dl.google.com/dl/chrome/install/googlechromestandaloneenterprise64.msi"
    $chromeMsi = "$env:TEMP\chrome_enterprise.msi"
    Invoke-WebRequest -Uri $chromeUrl -OutFile $chromeMsi -UseBasicParsing
    Start-Process msiexec.exe -ArgumentList "/i `"$chromeMsi`" /quiet /norestart" -Wait
    Remove-Item $chromeMsi -Force -ErrorAction SilentlyContinue
    $chromeFound = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
    if ($chromeFound) {
        Write-Host "  Google Chrome installed at $chromeFound" -ForegroundColor Green
    } else {
        Write-Host "  WARNING: Chrome MSI installed but binary not found in expected paths." -ForegroundColor Yellow
    }
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

# --- 5. Download GCP service account key from Azure Blob Storage ---
Write-Host "`n[5/6] Downloading GCP service account key..." -ForegroundColor Yellow

$gcpKeyPath = Join-Path $scriptDir "gcp-sa-key.json"
$storageAccount = "arknovastorage"
$container = "data"
$blobName = "gcp-sa-key.json"
$uamiClientId = "$(
    # Resolve client ID from the user-assigned managed identity resource
    # The UAMI is attached to the VM; we use IMDS to get a token with it
)"

# Get access token from Azure IMDS using the user-assigned managed identity
$imdsUrl = "http://169.254.169.254/metadata/identity/oauth2/token"
$imdsUrl += "?api-version=2018-02-01"
$imdsUrl += "&resource=https://storage.azure.com/"
# Use the specific UAMI resource ID
$uamiResourceId = "/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/ArkNovaStats/providers/Microsoft.ManagedIdentity/userAssignedIdentities/arknovauami"
$imdsUrl += "&mi_res_id=$([uri]::EscapeDataString($uamiResourceId))"

try {
    $tokenResponse = Invoke-RestMethod -Uri $imdsUrl -Headers @{ Metadata = "true" } -Method Get -UseBasicParsing
    $accessToken = $tokenResponse.access_token

    # Download blob from Azure Blob Storage
    $blobUrl = "https://$storageAccount.blob.core.windows.net/$container/$blobName"
    Invoke-RestMethod -Uri $blobUrl -Headers @{
        Authorization  = "Bearer $accessToken"
        "x-ms-version" = "2020-10-02"
    } -OutFile $gcpKeyPath -UseBasicParsing

    # Set the env var so google-cloud-bigquery auto-discovers it
    $env:GOOGLE_APPLICATION_CREDENTIALS = $gcpKeyPath
    [Environment]::SetEnvironmentVariable("GOOGLE_APPLICATION_CREDENTIALS", $gcpKeyPath, "Machine")

    Write-Host "  GCP SA key downloaded to $gcpKeyPath" -ForegroundColor Green
    Write-Host "  GOOGLE_APPLICATION_CREDENTIALS set." -ForegroundColor Green
} catch {
    Write-Host "  WARNING: Failed to download GCP SA key: $_" -ForegroundColor Yellow
    Write-Host "  BigQuery upload will not work without manual credential setup." -ForegroundColor Yellow
}

# --- 6. Verify installation ---
Write-Host "`n[6/6] Verifying installation..." -ForegroundColor Yellow

$checks = @(
    @{ Name = "Python";                Cmd = @("python", "--version") },
    @{ Name = "pip";                   Cmd = @("python", "-m", "pip", "--version") },
    @{ Name = "playwright";            Cmd = @("python", "-c", "from playwright._impl._driver import compute_driver_executable; print('playwright OK')") },
    @{ Name = "python-dotenv";         Cmd = @("python", "-c", "import dotenv; print('python-dotenv OK')") },
    @{ Name = "google-cloud-bigquery"; Cmd = @("python", "-c", "from google.cloud import bigquery; print('google-cloud-bigquery OK')") }
)

$allOk = $true
foreach ($check in $checks) {
    try {
        $result = & $check.Cmd[0] $check.Cmd[1..($check.Cmd.Length-1)] 2>&1
        if ($LASTEXITCODE -ne 0) { throw "exit code $LASTEXITCODE" }
        Write-Host "  [OK] $($check.Name): $result" -ForegroundColor Green
    } catch {
        Write-Host "  [FAIL] $($check.Name): $_" -ForegroundColor Red
        $allOk = $false
    }
}

$chromeCheck = $chromePaths | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($chromeCheck) {
    Write-Host "  [OK] Google Chrome: $chromeCheck" -ForegroundColor Green
} else {
    Write-Host "  [FAIL] Google Chrome not found in expected paths" -ForegroundColor Red
    $allOk = $false
}

Write-Host ""
if ($allOk) {
    Write-Host "=== Setup complete! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Copy .env.example to .env and fill in BGA_EMAIL and BGA_PASSWORD"
    Write-Host "  2. GCP credentials are auto-provisioned from Azure Blob Storage"
    Write-Host "  3. Run:  python main.py <player_id>"
    Write-Host "     Or:   python run.py <table_id1,table_id2,...>"
} else {
    Write-Host "=== Setup completed with errors. Review above. ===" -ForegroundColor Red
}
