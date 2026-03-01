#!/usr/bin/env bash
# =============================================================================
# Add Custom Domain with Managed SSL
# Usage: ./add-custom-domain.sh [prod|acc|dev] <domain>
# Example: ./add-custom-domain.sh prod api.example.com
# =============================================================================
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/load-env-config.sh" "${1:-prod}"

CUSTOM_DOMAIN="${2:-}"
if [[ -z "$CUSTOM_DOMAIN" ]]; then
    echo "Usage: $0 [prod|acc|dev] <domain>"
    echo "Example: $0 prod api.example.com"
    exit 1
fi

echo "============================================"
echo "  Adding Custom Domain: $CUSTOM_DOMAIN"
echo "  Container App: $BACKEND_APP_NAME"
echo "============================================"

# Get verification token
echo ""
echo "Step 1: Get verification token..."
VERIFICATION_ID=$(az containerapp show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --query "properties.customDomainVerificationId" -o tsv)

FQDN=$(az containerapp show \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --query "properties.configuration.ingress.fqdn" -o tsv)

echo ""
echo "Step 2: Add these DNS records to your domain provider:"
echo ""
echo "  CNAME record:"
echo "    Name:  $CUSTOM_DOMAIN"
echo "    Value: $FQDN"
echo ""
echo "  TXT record (for verification):"
echo "    Name:  asuid.$CUSTOM_DOMAIN"
echo "    Value: $VERIFICATION_ID"
echo ""
read -p "Press Enter after adding DNS records (wait for propagation)..."

# Verify and add domain
echo ""
echo "Step 3: Adding domain to container app..."
az containerapp hostname add \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN"

# Bind managed certificate
echo ""
echo "Step 4: Provisioning managed SSL certificate..."
az containerapp hostname bind \
    --resource-group "$RESOURCE_GROUP" \
    --name "$BACKEND_APP_NAME" \
    --hostname "$CUSTOM_DOMAIN" \
    --environment "$CONTAINER_APPS_ENV_NAME" \
    --validation-method "CNAME"

echo ""
echo "Custom domain configured!"
echo "  https://$CUSTOM_DOMAIN"
echo "  SSL certificate will be provisioned automatically (may take a few minutes)."
