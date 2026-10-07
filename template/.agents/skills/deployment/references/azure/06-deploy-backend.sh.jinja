#!/usr/bin/env bash
# =============================================================================
# Step 6: Deploy Backend to Azure Container Apps
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

# Load required credential files
for FILE in "acr-credentials" "database-credentials" "image-tags" "azure-storage"; do
    CRED_FILE="$SCRIPT_DIR/${FILE}${ENV_SUFFIX}.env"
    if [[ ! -f "$CRED_FILE" ]]; then
        echo "ERROR: $CRED_FILE not found. Run previous setup scripts first."
        exit 1
    fi
    source "$CRED_FILE"
done

# Load app secrets and the identity provider's issuer. Never set the `local` Spring profile on a deployed
# app: it enables the development identity.
SECRETS_FILE="$SCRIPT_DIR/app-secrets.env"
if [[ ! -f "$SECRETS_FILE" ]]; then
    echo "ERROR: app-secrets.env not found. Copy app-secrets.env.example and fill in values."
    exit 1
fi
source "$SECRETS_FILE"

echo "============================================"
echo "  Deploying Backend"
echo "  App: $BACKEND_APP_NAME"
echo "  Image: $BACKEND_IMAGE"
echo "============================================"

az containerapp create \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --environment "$CONTAINER_APPS_ENV_NAME" \
    --image "$BACKEND_IMAGE" \
    --registry-server "$ACR_LOGIN_SERVER" \
    --registry-username "$ACR_USERNAME" \
    --registry-password "$ACR_PASSWORD" \
    --target-port 8080 \
    --ingress external \
    --min-replicas "$BACKEND_MIN_REPLICAS" \
    --max-replicas "$BACKEND_MAX_REPLICAS" \
    --cpu "$BACKEND_CPU" \
    --memory "$BACKEND_MEMORY" \
    --secrets \
        "postgres-password=$POSTGRES_PASSWORD" \
        "azure-storage-key=$AZURE_STORAGE_ACCOUNT_KEY" \
    --env-vars \
        "SPRING_PROFILES_ACTIVE=prod" \
        "SPRING_DATASOURCE_URL=$POSTGRES_JDBC_URL" \
        "SPRING_DATASOURCE_USERNAME=$POSTGRES_USER" \
        "SPRING_DATASOURCE_PASSWORD=secretref:postgres-password" \
        "SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_ISSUER_URI=$IDENTITY_PROVIDER_ISSUER_URI" \
        "SPRING_SECURITY_OAUTH2_RESOURCESERVER_JWT_AUDIENCES=$IDENTITY_PROVIDER_AUDIENCE" \
        "AZURE_STORAGE_ACCOUNT_NAME=$AZURE_STORAGE_ACCOUNT_NAME" \
        "AZURE_STORAGE_ACCOUNT_KEY=secretref:azure-storage-key" \
        "CORS_ALLOWED_ORIGINS=${CORS_ALLOWED_ORIGINS:-}" \
        "APP_STAGE=$ENVIRONMENT"

# Get backend URL
BACKEND_FQDN=$(az containerapp show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

BACKEND_URL="https://$BACKEND_FQDN"

# Save backend URL
URL_FILE="$SCRIPT_DIR/backend-url${ENV_SUFFIX}.env"
echo "BACKEND_URL=$BACKEND_URL" > "$URL_FILE"

# Health check
echo ""
echo "Testing health endpoint..."
sleep 10
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${BACKEND_URL}/actuator/health" || echo "000")
if [[ "$HTTP_STATUS" == "200" ]]; then
    echo "Backend is healthy!"
else
    echo "WARNING: Health check returned $HTTP_STATUS (may still be starting up)"
fi

echo ""
echo "Backend deployed."
echo "  URL: $BACKEND_URL"
echo "  Health: ${BACKEND_URL}/actuator/health"
echo "Next: Run 07-show-deployment-info.sh"
