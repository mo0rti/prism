#!/usr/bin/env bash
# =============================================================================
# Step 4: Create Azure Blob Storage
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

echo "============================================"
echo "  Setting up Blob Storage"
echo "  Account: $STORAGE_ACCOUNT_NAME"
echo "============================================"

# --- Storage Account ---
az storage account create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STORAGE_ACCOUNT_NAME" \
    --location "$LOCATION" \
    --sku "Standard_LRS" \
    --kind "StorageV2" \
    --min-tls-version "TLS1_2" \
    --https-only true \
    --allow-blob-public-access false

STORAGE_KEY=$(az storage account keys list \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT_NAME" \
    --query "[0].value" -o tsv)

STORAGE_CONNECTION_STRING=$(az storage account show-connection-string \
    --resource-group "$RESOURCE_GROUP" \
    --name "$STORAGE_ACCOUNT_NAME" \
    --query connectionString -o tsv)

# --- Create containers ---
echo ""
echo "Creating blob containers..."
for CONTAINER in "uploads" "public-assets"; do
    az storage container create \
        --account-name "$STORAGE_ACCOUNT_NAME" \
        --account-key "$STORAGE_KEY" \
        --name "$CONTAINER" \
        --public-access off
    echo "  Created container: $CONTAINER"
done

# --- Lifecycle policy (auto-delete temp files after 30 days) ---
echo "Setting up lifecycle policies..."
az storage account management-policy create \
    --resource-group "$RESOURCE_GROUP" \
    --account-name "$STORAGE_ACCOUNT_NAME" \
    --policy '{
        "rules": [
            {
                "name": "cleanup-temp-uploads",
                "enabled": true,
                "type": "Lifecycle",
                "definition": {
                    "filters": {
                        "blobTypes": ["blockBlob"],
                        "prefixMatch": ["uploads/temp/"]
                    },
                    "actions": {
                        "baseBlob": {
                            "delete": { "daysAfterModificationGreaterThan": 30 }
                        }
                    }
                }
            }
        ]
    }'

# --- Save credentials ---
STORAGE_FILE="$SCRIPT_DIR/azure-storage${ENV_SUFFIX}.env"
cat > "$STORAGE_FILE" <<EOF
AZURE_STORAGE_ACCOUNT_NAME=$STORAGE_ACCOUNT_NAME
AZURE_STORAGE_ACCOUNT_KEY=$STORAGE_KEY
AZURE_STORAGE_CONNECTION_STRING=$STORAGE_CONNECTION_STRING
EOF

echo ""
echo "Storage created: $STORAGE_ACCOUNT_NAME"
echo "  Credentials saved to: $STORAGE_FILE"
echo "Next: Run 05-build-and-push-images.sh"
