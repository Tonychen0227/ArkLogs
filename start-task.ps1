#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Setup script for Windows Server 2022 to run BGA scraper and publish to Google BigQuery.

.DESCRIPTION
    Installs Python 3.12, VC++ Redistributable, pip dependencies (Playwright, BigQuery client, etc.),
    Playwright Chromium browser, and Google Chrome.
    Run this once as Administrator before using main.py or run.py.
#>

$ErrorActionPreference = "Stop"

# Repo code lives here (downloaded by Azure Batch resource files)
$repoDir = "C:\arklogs\arklogs-main"

Write-Host "=== BGA Scraper Setup for Windows Server 2022 ===" -ForegroundColor Cyan

# --- 1. Install Python ---
Write-Host "`n[1/7] Checking Python installation..." -ForegroundColor Yellow

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

# --- 2. Install Visual C++ Redistributable (required by greenlet/Playwright) ---
Write-Host "`n[2/7] Checking Visual C++ Redistributable..." -ForegroundColor Yellow

$vcInstalled = Test-Path "HKLM:\SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64"
if ($vcInstalled) {
    Write-Host "  Visual C++ Redistributable already installed." -ForegroundColor Green
} else {
    Write-Host "  Installing Visual C++ Redistributable..." -ForegroundColor Yellow
    $vcUrl = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
    $vcInstaller = "$env:TEMP\vc_redist.x64.exe"
    Invoke-WebRequest -Uri $vcUrl -OutFile $vcInstaller -UseBasicParsing
    Start-Process -FilePath $vcInstaller -ArgumentList "/install /quiet /norestart" -Wait
    Remove-Item $vcInstaller -Force -ErrorAction SilentlyContinue
    Write-Host "  Visual C++ Redistributable installed." -ForegroundColor Green
}

# --- 3. Install pip dependencies ---
Write-Host "`n[3/7] Installing pip dependencies..." -ForegroundColor Yellow

$requirementsFile = Join-Path $repoDir "requirements.txt"

if (-not (Test-Path $requirementsFile)) {
    Write-Host "  ERROR: requirements.txt not found at $requirementsFile" -ForegroundColor Red
    exit 1
}

& python -m pip install --upgrade pip
& python -m pip install -r $requirementsFile

Write-Host "  pip dependencies installed." -ForegroundColor Green

# --- 4. Install Playwright browsers ---
Write-Host "`n[4/7] Installing Playwright Chromium browser..." -ForegroundColor Yellow
& python -m playwright install chromium
Write-Host "  Playwright Chromium installed." -ForegroundColor Green

# --- 5. Install Cloudflare WARP VPN ---
Write-Host "`n[5/7] Installing Cloudflare WARP VPN..." -ForegroundColor Yellow

$warpUrl = "https://1111-releases.cloudflareclient.com/windows/Cloudflare_WARP_Release-x64.msi"
$warpInstaller = "$env:TEMP\cloudflare-warp.msi"

# Check if WARP service already exists
$warpSvc = Get-Service -Name "CloudflareWARP" -ErrorAction SilentlyContinue
if ($warpSvc) {
    Write-Host "  Cloudflare WARP service already installed (Status: $($warpSvc.Status))." -ForegroundColor Green
} else {
    Write-Host "  Downloading WARP installer..." -ForegroundColor Yellow
    Invoke-WebRequest -Uri $warpUrl -OutFile $warpInstaller -UseBasicParsing
    Write-Host "  Installing WARP (this may take a minute)..." -ForegroundColor Yellow
    Start-Process msiexec.exe -ArgumentList "/i `"$warpInstaller`" /quiet /norestart INSTALL_DIR=`"C:\Program Files\Cloudflare`"" -Wait
    Remove-Item $warpInstaller -Force -ErrorAction SilentlyContinue
}

# Find warp-cli.exe anywhere on the system
$warpExe = Get-ChildItem -Path "C:\" -Filter "warp-cli.exe" -Recurse -ErrorAction SilentlyContinue -Depth 4 | Select-Object -First 1 -ExpandProperty FullName
if (-not $warpExe) {
    # Also check common locations
    $candidates = @(
        "C:\Program Files\Cloudflare\Cloudflare WARP\warp-cli.exe",
        "C:\Program Files (x86)\Cloudflare\Cloudflare WARP\warp-cli.exe",
        "${env:ProgramFiles}\Cloudflare\Cloudflare WARP\warp-cli.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $warpExe = $c; break }
    }
}

if ($warpExe) {
    Write-Host "  warp-cli found at: $warpExe" -ForegroundColor Green
    try {
        & $warpExe registration new 2>&1 | Out-Null
        & $warpExe connect 2>&1 | Out-Null
        Start-Sleep -Seconds 5
        $warpStatus = & $warpExe status 2>&1
        Write-Host "  WARP status: $warpStatus" -ForegroundColor Green
    } catch {
        Write-Host "  WARNING: WARP connect failed: $_" -ForegroundColor Yellow
    }
} else {
    Write-Host "  WARNING: warp-cli.exe not found. Checking service status..." -ForegroundColor Yellow
    $warpSvc = Get-Service -Name "CloudflareWARP" -ErrorAction SilentlyContinue
    if ($warpSvc -and $warpSvc.Status -eq "Running") {
        Write-Host "  WARP service is running (VPN should be active)." -ForegroundColor Green
    } else {
        Write-Host "  WARP not operational. Listing installed Cloudflare files:" -ForegroundColor Yellow
        Get-ChildItem -Path "C:\Program Files*" -Filter "*cloudflare*" -Recurse -Depth 3 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $($_.FullName)" }
        Get-ChildItem -Path "C:\ProgramData" -Filter "*cloudflare*" -Recurse -Depth 3 -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "    $($_.FullName)" }
    }
}

# --- 6. Download GCP service account key from Azure Blob Storage ---
Write-Host "`n[6/7] Downloading GCP service account key..." -ForegroundColor Yellow

$gcpKeyPath = Join-Path $repoDir "gcp-sa-key.json"
$storageAccount = "arknovastorage"
$container = "data"
$blobName = "gcp-sa-key.json"

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

# --- 7. Verify installation ---
Write-Host "`n[7/7] Verifying installation..." -ForegroundColor Yellow

$checks = @(
    @{ Name = "Python";                Cmd = @("python", "--version") },
    @{ Name = "pip";                   Cmd = @("python", "-m", "pip", "--version") },
    @{ Name = "greenlet";              Cmd = @("python", "-c", "import greenlet; print('greenlet OK')") },
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

Write-Host ""
if ($allOk) {
    Write-Host "=== Setup complete! ===" -ForegroundColor Green
    Write-Host ""
    Write-Host "Next steps:" -ForegroundColor Cyan
    Write-Host "  1. Copy .env.example to .env and fill in BGA_EMAIL and BGA_PASSWORD"
    Write-Host "  2. GCP credentials are auto-provisioned from Azure Blob Storage"
    Write-Host '  3. Run:  python main.py <player_id>'
    Write-Host '     Or:   python run.py <table_id1,table_id2,...>'
} else {
    Write-Host "=== Setup completed with errors. Review above. ===" -ForegroundColor Red
}
