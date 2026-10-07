#!/usr/bin/env bash
# =============================================================================
# Step 2: Create PostgreSQL Flexible Server
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

echo "============================================"
echo "  Setting up Databases"
echo "  PostgreSQL: $POSTGRES_SERVER_NAME"
echo "============================================"

# --- Auto-generate password if not set ---
if [[ -z "${POSTGRES_ADMIN_PASSWORD:-}" ]]; then
    POSTGRES_ADMIN_PASSWORD=$(openssl rand -base64 32 | tr -dc 'a-zA-Z0-9' | head -c 32)
    echo "Auto-generated PostgreSQL password (32 chars)"
fi

# Save password
PASS_FILE="$SCRIPT_DIR/postgres-password${ENV_SUFFIX}.env"
echo "POSTGRES_ADMIN_PASSWORD=$POSTGRES_ADMIN_PASSWORD" > "$PASS_FILE"

# --- PostgreSQL ---
echo ""
echo "Creating PostgreSQL Flexible Server..."
az postgres flexible-server create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_SERVER_NAME" \
    --location "$LOCATION" \
    --admin-user "$POSTGRES_ADMIN_USER" \
    --admin-password "$POSTGRES_ADMIN_PASSWORD" \
    --sku-name "$POSTGRES_SKU" \
    --tier "Burstable" \
    --storage-size "$POSTGRES_STORAGE_SIZE_GB" \
    --version "$POSTGRES_VERSION" \
    --yes

echo "Creating database '$POSTGRES_DATABASE_NAME'..."
az postgres flexible-server db create \
    --resource-group "$RESOURCE_GROUP" \
    --server-name "$POSTGRES_SERVER_NAME" \
    --database-name "$POSTGRES_DATABASE_NAME"

echo "Configuring firewall (allow Azure services)..."
az postgres flexible-server firewall-rule create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$POSTGRES_SERVER_NAME" \
    --rule-name "AllowAzureServices" \
    --start-ip-address "0.0.0.0" \
    --end-ip-address "0.0.0.0"

# --- Save credentials ---
POSTGRES_HOST="${POSTGRES_SERVER_NAME}.postgres.database.azure.com"

CRED_FILE="$SCRIPT_DIR/database-credentials${ENV_SUFFIX}.env"
cat > "$CRED_FILE" <<EOF
# PostgreSQL
POSTGRES_HOST=$POSTGRES_HOST
POSTGRES_PORT=5432
POSTGRES_DATABASE=$POSTGRES_DATABASE_NAME
POSTGRES_USER=$POSTGRES_ADMIN_USER
POSTGRES_PASSWORD=$POSTGRES_ADMIN_PASSWORD
POSTGRES_JDBC_URL=jdbc:postgresql://$POSTGRES_HOST:5432/$POSTGRES_DATABASE_NAME?sslmode=require

EOF

echo ""
echo "Databases created."
echo "  PostgreSQL: $POSTGRES_HOST"
echo "  Credentials saved to: $CRED_FILE"
echo ""
echo "Next: Run 03-setup-container-apps-env.sh"
