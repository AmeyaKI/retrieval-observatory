#!/usr/bin/env bash
# One-command deploy of the hosted demo to Azure Container Apps.
# Prerequisites: `az login` done; the GHCR package is public (see deploy/README.md).
# Idempotent: re-running updates the app to the current image.
set -euo pipefail

RG="${RETOBS_AZ_RG:-rg-retobs-demo}"
LOCATION="${RETOBS_AZ_LOCATION:-eastus}"
ENV_NAME="${RETOBS_AZ_ENV:-retobs-demo-env}"
APP="${RETOBS_AZ_APP:-retobs-demo}"
IMAGE="${RETOBS_DEMO_IMAGE:-ghcr.io/ameyaki/retrieval-observatory:demo}"

echo "==> resource providers (one-time per subscription; no-op if registered)"
for provider in Microsoft.App Microsoft.OperationalInsights; do
  if [ "$(az provider show -n "$provider" --query registrationState -o tsv 2>/dev/null)" != "Registered" ]; then
    az provider register -n "$provider" --wait
  fi
done

echo "==> resource group $RG ($LOCATION)"
az group create --name "$RG" --location "$LOCATION" --output none

echo "==> container apps environment $ENV_NAME"
if ! az containerapp env show --name "$ENV_NAME" --resource-group "$RG" --output none 2>/dev/null; then
  az containerapp env create --name "$ENV_NAME" --resource-group "$RG" --location "$LOCATION" --output none
fi

echo "==> container app $APP from $IMAGE"
if az containerapp show --name "$APP" --resource-group "$RG" --output none 2>/dev/null; then
  az containerapp update --name "$APP" --resource-group "$RG" --image "$IMAGE" --output none
else
  az containerapp create \
    --name "$APP" --resource-group "$RG" --environment "$ENV_NAME" \
    --image "$IMAGE" --target-port 8000 --ingress external \
    --cpu 0.5 --memory 1.0Gi --min-replicas 0 --max-replicas 1 \
    --env-vars RETOBS_READ_ONLY=1 RETOBS_RATE_LIMIT_PER_MINUTE=300 \
    --output none
fi

FQDN="$(az containerapp show --name "$APP" --resource-group "$RG" --query properties.configuration.ingress.fqdn --output tsv)"
URL="https://${FQDN}"
echo "==> health check $URL/healthz"
for _ in $(seq 1 30); do
  if curl -fsS "$URL/healthz" | grep -q '"read_only":true'; then
    echo "OK: $URL"
    echo "Now put $URL in README.md (Hosted demo line) and HANDOFF.md (provider: Azure Container Apps)."
    exit 0
  fi
  sleep 5
done
echo "health check did not pass; inspect: az containerapp logs show -n $APP -g $RG --follow" >&2
exit 1
