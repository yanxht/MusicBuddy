#!/usr/bin/env bash
# Build the image in ACR (no local Docker needed) and deploy/update the Container App.
# Idempotent: safe to re-run for every release.
set -euo pipefail
cd "$(dirname "$0")/.."

RG=${RG:-musicbuddy-rg}
LOC=${LOC:-westus2}
ACR=${ACR:-musicbuddyacr}
ENVNAME=${ENVNAME:-musicbuddy-env}
APP=${APP:-musicbuddy}
TAG=${TAG:-$(date +%Y%m%d%H%M%S)}
PY=.venv/bin/python

val() { $PY -c "from dotenv import dotenv_values; print(dotenv_values('.env')['$1'])"; }

az group create -n "$RG" -l "$LOC" -o none

if ! az acr show -n "$ACR" -g "$RG" -o none 2>/dev/null; then
  az acr create -n "$ACR" -g "$RG" -l "$LOC" --sku Basic --admin-enabled true -o none
fi
az acr build -r "$ACR" -t "musicbuddy:$TAG" -t musicbuddy:latest . -o none
IMAGE="$ACR.azurecr.io/musicbuddy:$TAG"

if ! az containerapp env show -n "$ENVNAME" -g "$RG" -o none 2>/dev/null; then
  az containerapp env create -n "$ENVNAME" -g "$RG" -l "$LOC" -o none
fi

ACR_USER=$(az acr credential show -n "$ACR" --query username -o tsv)
ACR_PASS=$(az acr credential show -n "$ACR" --query "passwords[0].value" -o tsv)

SECRETS=(
  "deepseek-key=$(val DEEPSEEK_API_KEY)"
  "speech-key=$(val AZURE_SPEECH_KEY)"
  "storage-conn=$(val AZURE_STORAGE_CONNECTION_STRING)"
  "session-secret=$(val MB_SESSION_SECRET)"
  "passcode=$(val MB_PASSCODE)"
)
ENVVARS=(
  DEEPSEEK_API_KEY=secretref:deepseek-key
  AZURE_SPEECH_KEY=secretref:speech-key
  "AZURE_SPEECH_REGION=$(val AZURE_SPEECH_REGION)"
  AZURE_STORAGE_CONNECTION_STRING=secretref:storage-conn
  MB_SESSION_SECRET=secretref:session-secret
  MB_PASSCODE=secretref:passcode
  MB_RUN_WORKER=1
)

if ! az containerapp show -n "$APP" -g "$RG" -o none 2>/dev/null; then
  az containerapp create -n "$APP" -g "$RG" --environment "$ENVNAME" --image "$IMAGE" \
    --registry-server "$ACR.azurecr.io" --registry-username "$ACR_USER" --registry-password "$ACR_PASS" \
    --target-port 8000 --ingress external --cpu 0.75 --memory 1.5Gi --min-replicas 1 --max-replicas 1 \
    --secrets "${SECRETS[@]}" --env-vars "${ENVVARS[@]}" -o none
else
  az containerapp secret set -n "$APP" -g "$RG" --secrets "${SECRETS[@]}" -o none
  az containerapp update -n "$APP" -g "$RG" --image "$IMAGE" --set-env-vars "${ENVVARS[@]}" -o none
fi

FQDN=$(az containerapp show -n "$APP" -g "$RG" --query properties.configuration.ingress.fqdn -o tsv)
echo "Deployed $IMAGE"
echo "URL: https://$FQDN"
