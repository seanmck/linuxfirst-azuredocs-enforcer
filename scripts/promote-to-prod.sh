#!/bin/bash
set -euo pipefail

# ============================================================================
# DEPRECATED: This script reads from your LOCAL dev overlay which may be stale.
# Use the GitHub Action instead:
#   gh workflow run promote-to-prod.yml
#   gh workflow run promote-to-prod.yml -f dry_run=true  # Preview only
#
# The Action always reads from origin/main and creates a PR for review.
# This script is kept for offline/emergency use only.
# ============================================================================

# Verify kustomize is installed
if ! command -v kustomize &> /dev/null; then
  echo "Error: kustomize is not installed"
  exit 1
fi

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
  # Extract current tag from dev overlay using yq for robust YAML parsing
  TAG=$(yq eval ".images[] | select(.name == \"${REGISTRY}/${IMAGE}\") | .newTag" "${DEV_OVERLAY}/kustomization.yaml")

  if [[ -z "$TAG" ]]; then
    echo "Error: Could not find tag for ${IMAGE} in ${DEV_OVERLAY}/kustomization.yaml" >&2
    exit 1
  fi

  echo "Promoting ${IMAGE} to ${TAG}"
  (cd "$PROD_OVERLAY" && kustomize edit set image "${REGISTRY}/${IMAGE}:${TAG}")
done

echo "Done. Review changes with: git diff ${PROD_OVERLAY}/kustomization.yaml"
