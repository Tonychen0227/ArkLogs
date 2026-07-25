# Recreate arknovalogspool as a Linux pool
# Run this after deleting the existing Windows pool

$batchAccount = "arknovastats"
$batchEndpoint = "https://arknovastats.eastus.batch.azure.com"
$resourceGroup = "ArkNovaStats"
$poolId = "arknovalogspool"

# --- 1. Delete existing Windows pool ---
Write-Host "Deleting existing pool '$poolId'..." -ForegroundColor Yellow
az batch pool delete `
    --pool-id $poolId `
    --account-name $batchAccount `
    --account-endpoint $batchEndpoint `
    --yes

Write-Host "Waiting for pool deletion..." -ForegroundColor Yellow
do {
    Start-Sleep -Seconds 5
    $pool = az batch pool show --pool-id $poolId --account-name $batchAccount --account-endpoint $batchEndpoint 2>&1
    if ($pool -match "not found" -or $pool -match "does not exist" -or $LASTEXITCODE -ne 0) { break }
    Write-Host "  Still deleting..."
} while ($true)
Write-Host "Pool deleted." -ForegroundColor Green

# --- 2. Create Linux pool with UAMI via ARM API ---
Write-Host "`nCreating Linux pool '$poolId' with UAMI..." -ForegroundColor Yellow

$startTaskCmd = '/bin/bash -c "apt-get update -qq && apt-get install -y -qq curl unzip python3 python3-pip && curl -sL https://github.com/Tonychen0227/arklogs/archive/refs/heads/main.zip -o /tmp/arklogs.zip && unzip -oq /tmp/arklogs.zip -d /arklogs && bash /arklogs/ArkLogs-main/start-task.sh"'

$uamiResourceId = "/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/ArkNovaStats/providers/Microsoft.ManagedIdentity/userAssignedIdentities/arknovauami"

$poolBody = @{
    identity = @{
        type = "UserAssigned"
        userAssignedIdentities = @{
            $uamiResourceId = @{}
        }
    }
    properties = @{
        vmSize = "STANDARD_A1_V2"
        deploymentConfiguration = @{
            virtualMachineConfiguration = @{
                imageReference = @{
                    publisher = "canonical"
                    offer = "0001-com-ubuntu-server-jammy"
                    sku = "22_04-lts"
                    version = "latest"
                }
                nodeAgentSkuId = "batch.node.ubuntu 22.04"
            }
        }
        scaleSettings = @{
            fixedScale = @{
                targetDedicatedNodes = 1
                targetLowPriorityNodes = 0
            }
        }
        startTask = @{
            commandLine = $startTaskCmd
            userIdentity = @{
                autoUser = @{
                    scope = "Pool"
                    elevationLevel = "Admin"
                }
            }
            maxTaskRetryCount = 1
            waitForSuccess = $true
        }
        taskSlotsPerNode = 1
        networkConfiguration = @{
            publicIPAddressConfiguration = @{
                provision = "BatchManaged"
            }
        }
    }
} | ConvertTo-Json -Depth 10

# Write JSON to temp file (az rest --body from string has quoting issues on Windows)
$tmpFile = "$env:TEMP\pool-body.json"
$poolBody | Out-File -FilePath $tmpFile -Encoding utf8NoBOM

$armUrl = "https://management.azure.com/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/$resourceGroup/providers/Microsoft.Batch/batchAccounts/$batchAccount/pools/${poolId}?api-version=2024-07-01"

az rest --method PUT --url $armUrl --body "@$tmpFile" --headers "Content-Type=application/json"
Remove-Item $tmpFile -Force -ErrorAction SilentlyContinue

Write-Host "`nPool created. Waiting for node to become idle..." -ForegroundColor Yellow

# --- 4. Wait for node ---
do {
    Start-Sleep -Seconds 15
    $status = az batch pool show --pool-id $poolId --account-name $batchAccount --account-endpoint $batchEndpoint --query "allocationState" -o tsv 2>&1
    $dedicated = az batch pool show --pool-id $poolId --account-name $batchAccount --account-endpoint $batchEndpoint --query "currentDedicatedNodes" -o tsv 2>&1
    Write-Host "  Allocation: $status, Nodes: $dedicated"
} while ($status -ne "steady" -or $dedicated -ne "1")

Write-Host "`n=== Linux pool '$poolId' is ready! ===" -ForegroundColor Green
Write-Host "Submit a job with: python .\_submit_batch.py"
