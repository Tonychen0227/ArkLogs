#!/bin/bash
set -e

echo "=== Proton VPN CLI Connect Script ==="

# Download Proton VPN CLI credentials from Azure Blob using IMDS
STORAGE_ACCOUNT="arknovastorage"
CONTAINER="data"
UAMI_RESOURCE_ID="/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/ArkNovaStats/providers/Microsoft.ManagedIdentity/userAssignedIdentities/arknovauami"

echo "Fetching IMDS token..."
ENCODED_UAMI=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$UAMI_RESOURCE_ID', safe=''))")
IMDS_URL="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://storage.azure.com/&mi_res_id=$ENCODED_UAMI"

TOKEN_JSON=$(curl -s -H "Metadata: true" "$IMDS_URL")
ACCESS_TOKEN=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['access_token'])" <<< "$TOKEN_JSON")

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
    echo "ERROR: Failed to get Azure access token for blob download"
    echo "Token response: $TOKEN_JSON"
    exit 1
fi
echo "Got access token."

# Download credentials
echo "Downloading Proton CLI credentials..."
curl -fsS -o /tmp/proton-cli-credentials.txt \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "x-ms-version: 2020-10-02" \
    "https://$STORAGE_ACCOUNT.blob.core.windows.net/$CONTAINER/proton-cli-credentials.txt"
echo "  credentials downloaded."

chmod 600 /tmp/proton-cli-credentials.txt
mapfile -t PROTON_CREDENTIALS < /tmp/proton-cli-credentials.txt
PROTON_USERNAME="${PROTON_CREDENTIALS[0]:-}"
PROTON_PASSWORD="${PROTON_CREDENTIALS[1]:-}"
if [ -z "$PROTON_USERNAME" ] || [ -z "$PROTON_PASSWORD" ]; then
    echo "ERROR: Proton CLI credentials must contain username and password lines"
    exit 1
fi

if ! command -v protonvpn &>/dev/null; then
    echo "ERROR: Proton VPN CLI is not installed by the pool start task"
    exit 1
fi

echo "Resetting any previous Proton VPN session..."
protonvpn disconnect || true
protonvpn signout || true

echo "Signing in to Proton VPN CLI..."
if ! printf '%s\n' "$PROTON_PASSWORD" | script -qefc "protonvpn signin '$PROTON_USERNAME'" /dev/null; then
    echo "ERROR: Proton VPN CLI sign-in failed"
    exit 1
fi

protonvpn config set kill-switch off
protonvpn config set ipv6 off
echo "Connecting to the fastest United States server..."
protonvpn connect --country US

echo "Public IP: $(curl -fsS --max-time 20 ifconfig.me)"
echo "Testing BGA connectivity..."
BGA_STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 30 https://en.boardgamearena.com/account)
echo "  BGA HTTP status: $BGA_STATUS"
if [ "$BGA_STATUS" = "000" ]; then
    echo "ERROR: BGA is not reachable through Proton VPN"
    exit 1
fi
