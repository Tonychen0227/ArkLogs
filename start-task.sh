#!/bin/bash
set -e

# === BGA Scraper Setup for Ubuntu (Azure Batch) ===

REPO_DIR="/arklogs/ArkLogs-main"

echo "=== BGA Scraper Setup for Linux ==="

# --- 1. Install Python 3 + pip ---
echo ""
echo "[1/6] Checking Python installation..."
if command -v python3 &>/dev/null; then
    echo "  Python already installed: $(python3 --version)"
else
    echo "  Installing Python 3..."
    apt-get update -qq
    apt-get install -y -qq python3 python3-pip python3-venv
    echo "  Installed: $(python3 --version)"
fi

# Ensure pip is available
python3 -m pip install --upgrade pip -q

# --- 2. Install pip dependencies ---
echo ""
echo "[2/6] Installing pip dependencies..."

REQUIREMENTS="$REPO_DIR/requirements.txt"
if [ ! -f "$REQUIREMENTS" ]; then
    echo "  ERROR: requirements.txt not found at $REQUIREMENTS"
    exit 1
fi

python3 -m pip install -r "$REQUIREMENTS" -q
echo "  pip dependencies installed."

# --- 3. Install Playwright Chromium + deps ---
echo ""
echo "[3/6] Installing Playwright Chromium browser..."
python3 -m playwright install --with-deps chromium
echo "  Playwright Chromium installed."

# --- 4. Install Proton VPN CLI ---
echo ""
echo "[4/6] Installing Proton VPN CLI..."
PROTON_RELEASE="protonvpn-stable-release_1.0.8_all.deb"
PROTON_SHA256="0b14e71586b22e498eb20926c48c7b434b751149b1f2af9902ef1cfe6b03e180"
wget -q "https://repo.protonvpn.com/debian/dists/stable/main/binary-all/$PROTON_RELEASE" -O "/tmp/$PROTON_RELEASE"
echo "$PROTON_SHA256  /tmp/$PROTON_RELEASE" | sha256sum --check -
dpkg -i "/tmp/$PROTON_RELEASE"
apt-get update -qq
apt-get install -y -qq proton-vpn-cli
rm -f "/tmp/$PROTON_RELEASE"
apt-get clean && rm -rf /var/lib/apt/lists/*
echo "  Proton VPN CLI installed."

# --- 5. Download GCP service account key from Azure Blob Storage ---
echo ""
echo "[5/6] Downloading GCP service account key..."

GCP_KEY_PATH="$REPO_DIR/gcp-sa-key.json"
STORAGE_ACCOUNT="arknovastorage"
CONTAINER="data"
UAMI_RESOURCE_ID="/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/ArkNovaStats/providers/Microsoft.ManagedIdentity/userAssignedIdentities/arknovauami"

# Get access token from Azure IMDS
ENCODED_UAMI=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$UAMI_RESOURCE_ID', safe=''))")
IMDS_URL="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://storage.azure.com/&mi_res_id=$ENCODED_UAMI"

TOKEN_JSON=$(curl -s -H "Metadata: true" "$IMDS_URL")
ACCESS_TOKEN=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['access_token'])" <<< "$TOKEN_JSON")

if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "null" ]; then
    # Download GCP SA key
    curl -s -o "$GCP_KEY_PATH" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "x-ms-version: 2020-10-02" \
        "https://$STORAGE_ACCOUNT.blob.core.windows.net/$CONTAINER/gcp-sa-key.json"

    export GOOGLE_APPLICATION_CREDENTIALS="$GCP_KEY_PATH"
    echo "  GCP SA key downloaded to $GCP_KEY_PATH"
else
    echo "  WARNING: Failed to get Azure access token. GCP key not downloaded."
fi

# --- 6. Verify installation ---
echo ""
echo "[6/6] Verifying installation..."

ALL_OK=true
for check in \
    "Python:python3 --version" \
    "pip:python3 -m pip --version" \
    "greenlet:python3 -c 'import greenlet; print(\"greenlet OK\")'" \
    "playwright:python3 -c 'from playwright._impl._driver import compute_driver_executable; print(\"playwright OK\")'" \
    "protonvpn:protonvpn --version" \
    "python-dotenv:python3 -c 'import dotenv; print(\"python-dotenv OK\")'" \
    "google-cloud-bigquery:python3 -c 'from google.cloud import bigquery; print(\"google-cloud-bigquery OK\")'"
do
    NAME="${check%%:*}"
    CMD="${check#*:}"
    if RESULT=$(eval "$CMD" 2>&1); then
        echo "  [OK] $NAME: $RESULT"
    else
        echo "  [FAIL] $NAME: $RESULT"
        ALL_OK=false
    fi
done

echo ""
if $ALL_OK; then
    echo "=== Setup complete! ==="
else
    echo "=== Setup completed with errors. Review above. ==="
fi
