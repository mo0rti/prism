#!/usr/bin/env bash
# =============================================================================
# Load environment-specific configuration
# Usage: source ./load-env-config.sh [prod|acc|dev]
# =============================================================================
set -euo pipefail

ENVIRONMENT="${1:-prod}"

if [[ ! "$ENVIRONMENT" =~ ^(prod|acc|dev)$ ]]; then
    echo "ERROR: Invalid environment '$ENVIRONMENT'. Must be: prod, acc, or dev"
    exit 1
fi

# Set suffix for generated credential files
if [[ "$ENVIRONMENT" == "prod" ]]; then
    ENV_SUFFIX=""
else
    ENV_SUFFIX="-${ENVIRONMENT}"
fi

export ENVIRONMENT
export ENV_SUFFIX

# Source the main config
CONFIG_FILE="$(dirname "$0")/azure-config.env"
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "ERROR: Config file not found: $CONFIG_FILE"
    echo "Copy azure-config.env.example to azure-config.env and fill in your values."
    exit 1
fi

source "$CONFIG_FILE"

echo "Loaded config for environment: $ENVIRONMENT"
echo "  Resource Group: $RESOURCE_GROUP"
echo "  Location: $LOCATION"
