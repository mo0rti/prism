#!/usr/bin/env bash
# =============================================================================
# Step 1: Create Azure Container Registry + Log Analytics Workspace
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

echo "============================================"
echo "  Setting up Foundation"
echo "  ACR: $ACR_NAME"
echo "  Log Analytics: $LOG_ANALYTICS_NAME"
echo "============================================"

# --- Container Registry ---
echo ""
echo "Creating Azure Container Registry..."
az acr create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$ACR_NAME" \
    --sku "$ACR_SKU" \
    --admin-enabled true

ACR_LOGIN_SERVER=$(az acr show --name "$ACR_NAME" --query loginServer -o tsv)
ACR_USERNAME=$(az acr credential show --name "$ACR_NAME" --query username -o tsv)
ACR_PASSWORD=$(az acr credential show --name "$ACR_NAME" --query "passwords[0].value" -o tsv)

# --- Log Analytics ---
echo ""
echo "Creating Log Analytics Workspace..."
az monitor log-analytics workspace create \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_NAME"

LOG_ANALYTICS_ID=$(az monitor log-analytics workspace show \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_NAME" \
    --query customerId -o tsv)

LOG_ANALYTICS_KEY=$(az monitor log-analytics workspace get-shared-keys \
    --resource-group "$RESOURCE_GROUP" \
    --workspace-name "$LOG_ANALYTICS_NAME" \
    --query primarySharedKey -o tsv)

# --- Save credentials ---
CRED_FILE="$SCRIPT_DIR/acr-credentials${ENV_SUFFIX}.env"
cat > "$CRED_FILE" <<EOF
ACR_LOGIN_SERVER=$ACR_LOGIN_SERVER
ACR_USERNAME=$ACR_USERNAME
ACR_PASSWORD=$ACR_PASSWORD
EOF

LOG_FILE="$SCRIPT_DIR/log-analytics${ENV_SUFFIX}.env"
cat > "$LOG_FILE" <<EOF
LOG_ANALYTICS_ID=$LOG_ANALYTICS_ID
LOG_ANALYTICS_KEY=$LOG_ANALYTICS_KEY
EOF

echo ""
echo "Foundation created."
echo "  ACR: $ACR_LOGIN_SERVER"
echo "  Credentials saved to: $CRED_FILE"
echo "  Log Analytics saved to: $LOG_FILE"
echo ""
echo "Next: Run 02-setup-database.sh"
