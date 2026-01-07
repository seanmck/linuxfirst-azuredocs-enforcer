#!/bin/bash
set -euo pipefail

# Copy image tags from dev overlay to prod overlay using kustomize
DEV_OVERLAY="infra/k8s/overlays/dev"
PROD_OVERLAY="infra/k8s/overlays/prod"
REGISTRY="seanmckdemo.azurecr.io"

for dir in "$DEV_OVERLAY" "$PROD_OVERLAY"; do
  if [[ ! -d "$dir" ]]; then
    echo "Error: Directory $dir does not exist"
    exit 1
  fi
done
# Images to promote
IMAGES=("webui" "queue-worker" "bias-scoring-service" "linuxfirst-azuredocs-db-migrations")

for IMAGE in "${IMAGES[@]}"; do
  # Ensure the image exists in the dev overlay before attempting to extract its tag
  if ! grep -q "name: ${REGISTRY}/${IMAGE}$" "${DEV_OVERLAY}/kustomization.yaml"; then
    echo "Warning: Image ${REGISTRY}/${IMAGE} not found in ${DEV_OVERLAY}/kustomization.yaml; skipping."
    continue
  fi
  # Extract current tag from dev overlay
  TAG=$(grep -A1 "name: ${REGISTRY}/${IMAGE}$" "${DEV_OVERLAY}/kustomization.yaml" | grep "newTag:" | awk '{print $2}')

  if [[ -z "$TAG" ]]; then
    echo "Error: Could not find tag for ${IMAGE} in ${DEV_OVERLAY}/kustomization.yaml" >&2
    exit 1
  fi

  echo "Promoting ${IMAGE} to ${TAG}"
  (cd "$PROD_OVERLAY" && kustomize edit set image "${REGISTRY}/${IMAGE}:${TAG}")
done

echo "Done. Review changes with: git diff ${PROD_OVERLAY}/kustomization.yaml"
