#!/bin/bash
set -e

# Download ProtonVPN config and credentials from Azure Blob using IMDS
STORAGE_ACCOUNT="arknovastorage"
CONTAINER="data"
UAMI_RESOURCE_ID="/subscriptions/6dec0042-21fa-419c-9be1-7b94eb1a58ed/resourceGroups/ArkNovaStats/providers/Microsoft.ManagedIdentity/userAssignedIdentities/arknovauami"

ENCODED_UAMI=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$UAMI_RESOURCE_ID', safe=''))")
IMDS_URL="http://169.254.169.254/metadata/identity/oauth2/token?api-version=2018-02-01&resource=https://storage.azure.com/&mi_res_id=$ENCODED_UAMI"

TOKEN_JSON=$(curl -s -H "Metadata: true" "$IMDS_URL")
ACCESS_TOKEN=$(python3 -c "import json,sys; print(json.loads(sys.stdin.read())['access_token'])" <<< "$TOKEN_JSON")

if [ -z "$ACCESS_TOKEN" ] || [ "$ACCESS_TOKEN" = "null" ]; then
    echo "ERROR: Failed to get Azure access token for blob download"
    exit 1
fi

# Download .ovpn config
curl -s -o /tmp/proton.ovpn \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "x-ms-version: 2020-10-02" \
    "https://$STORAGE_ACCOUNT.blob.core.windows.net/$CONTAINER/us-free-12.protonvpn.udp.ovpn"

# Download credentials
curl -s -o /tmp/proton-creds.txt \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "x-ms-version: 2020-10-02" \
    "https://$STORAGE_ACCOUNT.blob.core.windows.net/$CONTAINER/proton-creds.txt"

chmod 600 /tmp/proton-creds.txt

# Install OpenVPN
apt-get install -y -qq openvpn

# Connect to VPN in background
openvpn --config /tmp/proton.ovpn --auth-user-pass /tmp/proton-creds.txt --daemon --log /tmp/openvpn.log

# Wait for VPN to establish (check for TUN device)
echo "Waiting for VPN connection..."
for i in $(seq 1 30); do
    if ip addr show tun0 &>/dev/null; then
        echo "VPN connected! (attempt $i)"
        echo "Public IP: $(curl -s ifconfig.me)"
        exit 0
    fi
    sleep 2
done

echo "ERROR: VPN failed to connect in 60s"
echo "OpenVPN log:"
cat /tmp/openvpn.log
exit 1
