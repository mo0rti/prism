#!/usr/bin/env bash
# =============================================================================
# Step 3: Create Container Apps Environment
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

# Load Log Analytics credentials
LOG_FILE="$SCRIPT_DIR/log-analytics${ENV_SUFFIX}.env"
if [[ ! -f "$LOG_FILE" ]]; then
    echo "ERROR: Log Analytics credentials not found. Run 01-setup-foundation.sh first."
    exit 1
fi
source "$LOG_FILE"

echo "============================================"
echo "  Creating Container Apps Environment"
echo "  Name: $CONTAINER_APPS_ENV_NAME"
echo "============================================"

az containerapp env create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$CONTAINER_APPS_ENV_NAME" \
    --location "$LOCATION" \
    --logs-workspace-id "$LOG_ANALYTICS_ID" \
    --logs-workspace-key "$LOG_ANALYTICS_KEY"

# Save environment info
ENV_FILE="$SCRIPT_DIR/container-apps-env${ENV_SUFFIX}.env"
cat > "$ENV_FILE" <<EOF
CONTAINER_APPS_ENV_NAME=$CONTAINER_APPS_ENV_NAME
EOF

echo ""
echo "Container Apps Environment created: $CONTAINER_APPS_ENV_NAME"
echo "Next: Run 04-setup-storage.sh"
