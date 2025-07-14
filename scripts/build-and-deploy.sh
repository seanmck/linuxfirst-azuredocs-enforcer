#!/bin/bash

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

ACR_NAME="seanmckdemo.azurecr.io"
NAMESPACE="azuredocs-app"

declare -A SERVICE_CONFIG=(
    ["web,dockerfile"]="services/web/Dockerfile"
    ["web,manifests"]="infra/k8s/webui.yaml"
    ["web,image_name"]="webui"
    ["web,context"]="."
    
    ["worker,dockerfile"]="services/worker/Dockerfile"
    ["worker,manifests"]="infra/k8s/scan-worker.yaml infra/k8s/doc-worker-keda.yaml"
    ["worker,image_name"]="queue-worker"
    ["worker,context"]="."
    
    ["mcp-server,dockerfile"]="services/mcp-server/Dockerfile"
    ["mcp-server,manifests"]="infra/k8s/mcp-server.yaml"
    ["mcp-server,image_name"]="mcp-server"
    ["mcp-server,context"]="."
    
    ["db-migrate,dockerfile"]="infra/db/Dockerfile"
    ["db-migrate,manifests"]="infra/k8s/db-migrate.yaml"
    ["db-migrate,image_name"]="db-migrate"
    ["db-migrate,context"]="."
)

usage() {
    echo "Usage: $0 [--web] [--worker] [--mcp-server] [--db-migrate] [--services] [--all]"
    echo "  --web        Build and deploy web service"
    echo "  --worker     Build and deploy worker service"
    echo "  --mcp-server Build and deploy MCP server service"
    echo "  --db-migrate Build and deploy database migration job"
    echo "  --services   Build and deploy web, worker, and mcp-server services only"
    echo "  --all        Build and deploy all services and db-migrate"
    echo ""
    echo "At least one service must be specified."
    exit 1
}

check_prerequisites() {
    echo "Checking prerequisites..."
    
    if ! command -v docker &> /dev/null; then
        echo "Error: docker is not installed"
        exit 1
    fi
    
    if ! command -v kubectl &> /dev/null; then
        echo "Error: kubectl is not installed"
        exit 1
    fi
    
    if ! command -v az &> /dev/null; then
        echo "Error: Azure CLI is not installed"
        exit 1
    fi
    
    echo "Prerequisites check passed"
}

login_acr() {
    echo "Logging into Azure Container Registry..."
    if ! az acr login --name seanmckdemo; then
        echo "Error: Failed to login to ACR"
        exit 1
    fi
    echo "Successfully logged into ACR"
}

get_current_version() {
    local manifest_file="$1"
    local image_name="$2"
    
    if [[ ! -f "$manifest_file" ]]; then
        echo "Error: Manifest file $manifest_file not found"
        exit 1
    fi
    
    local version=$(grep -o "${ACR_NAME}/${image_name}:[0-9]\+\.[0-9]\+\.[0-9]\+" "$manifest_file" | head -1 | cut -d: -f2)
    
    if [[ -z "$version" ]]; then
        echo "Error: Could not find version in $manifest_file"
        exit 1
    fi
    
    echo "$version"
}

increment_version() {
    local version="$1"
    local major=$(echo "$version" | cut -d. -f1)
    local minor=$(echo "$version" | cut -d. -f2)
    local patch=$(echo "$version" | cut -d. -f3)
    
    patch=$((patch + 1))
    
    echo "${major}.${minor}.${patch}"
}

build_and_push_image() {
    local service="$1"
    local dockerfile="${SERVICE_CONFIG[${service},dockerfile]}"
    local image_name="${SERVICE_CONFIG[${service},image_name]}"
    local context="${SERVICE_CONFIG[${service},context]}"
    local manifests="${SERVICE_CONFIG[${service},manifests]}"
    
    # Get current version from first manifest
    local first_manifest=$(echo $manifests | cut -d' ' -f1)
    local current_version=$(get_current_version "${ROOT_DIR}/${first_manifest}" "$image_name")
    local new_version=$(increment_version "$current_version")
    
    echo "Building $service service..."
    echo "  Current version: $current_version"
    echo "  New version: $new_version"
    echo "  Dockerfile: $dockerfile"
    echo "  Context: $context"
    
    # Build the image
    echo "Building Docker image..."
    cd "$ROOT_DIR"
    if ! docker build -f "$dockerfile" -t "${ACR_NAME}/${image_name}:${new_version}" "$context"; then
        echo "Error: Failed to build Docker image for $service"
        exit 1
    fi
    
    # Push the image
    echo "Pushing Docker image..."
    if ! docker push "${ACR_NAME}/${image_name}:${new_version}"; then
        echo "Error: Failed to push Docker image for $service"
        exit 1
    fi
    
    echo "Successfully built and pushed ${ACR_NAME}/${image_name}:${new_version}"
    
    # Update manifest files
    update_manifests "$service" "$image_name" "$current_version" "$new_version"
}

update_manifests() {
    local service="$1"
    local image_name="$2"
    local current_version="$3"
    local new_version="$4"
    local manifests="${SERVICE_CONFIG[${service},manifests]}"
    
    echo "Updating Kubernetes manifests..."
    
    for manifest in $manifests; do
        local manifest_path="${ROOT_DIR}/${manifest}"
        echo "  Updating $manifest"
        
        if [[ ! -f "$manifest_path" ]]; then
            echo "Error: Manifest file $manifest_path not found"
            exit 1
        fi
        
        # Update the image version in the manifest
        if ! sed -i "s|${ACR_NAME}/${image_name}:${current_version}|${ACR_NAME}/${image_name}:${new_version}|g" "$manifest_path"; then
            echo "Error: Failed to update $manifest"
            exit 1
        fi
        
        echo "  Updated $manifest with new version $new_version"
    done
}

apply_manifests() {
    local service="$1"
    local manifests="${SERVICE_CONFIG[${service},manifests]}"
    
    echo "Applying Kubernetes manifests for $service..."
    
    for manifest in $manifests; do
        local manifest_path="${ROOT_DIR}/${manifest}"
        echo "  Applying $manifest"
        
        if ! kubectl apply -f "$manifest_path"; then
            echo "Error: Failed to apply $manifest"
            exit 1
        fi
    done
    
    echo "Successfully applied manifests for $service"
}

apply_db_migrate() {
    local manifests="${SERVICE_CONFIG[db-migrate,manifests]}"
    
    echo "Deploying database migration job..."
    
    # Delete existing job if it exists
    echo "  Cleaning up any existing db-migrate job..."
    kubectl delete job db-migrate -n "$NAMESPACE" --ignore-not-found=true
    
    # Wait a moment for cleanup
    sleep 2
    
    for manifest in $manifests; do
        local manifest_path="${ROOT_DIR}/${manifest}"
        echo "  Applying $manifest"
        
        if ! kubectl apply -f "$manifest_path"; then
            echo "Error: Failed to apply $manifest"
            exit 1
        fi
    done
    
    echo "Waiting for migration job to complete..."
    if kubectl wait --for=condition=complete --timeout=600s job/db-migrate -n "$NAMESPACE"; then
        echo "Database migration completed successfully!"
        kubectl logs job/db-migrate -n "$NAMESPACE"
    else
        echo "Database migration failed or timed out"
        kubectl logs job/db-migrate -n "$NAMESPACE" --tail=50
        exit 1
    fi
    
    echo "Successfully deployed and executed db-migrate job"
}

main() {
    local deploy_web=false
    local deploy_worker=false
    local deploy_mcp_server=false
    local deploy_db_migrate=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --web)
                deploy_web=true
                shift
                ;;
            --worker)
                deploy_worker=true
                shift
                ;;
            --mcp-server)
                deploy_mcp_server=true
                shift
                ;;
            --db-migrate)
                deploy_db_migrate=true
                shift
                ;;
            --services)
                deploy_web=true
                deploy_worker=true
                deploy_mcp_server=true
                shift
                ;;
            --all)
                deploy_web=true
                deploy_worker=true
                deploy_mcp_server=true
                deploy_db_migrate=true
                shift
                ;;
            --help|-h)
                usage
                ;;
            *)
                echo "Unknown option: $1"
                usage
                ;;
        esac
    done
    
    # Check if at least one service is specified
    if [[ "$deploy_web" == false && "$deploy_worker" == false && "$deploy_mcp_server" == false && "$deploy_db_migrate" == false ]]; then
        echo "Error: At least one service must be specified"
        usage
    fi
    
    # Run checks
    check_prerequisites
    login_acr
    
    # Deploy specified services
    if [[ "$deploy_web" == true ]]; then
        echo "=== Deploying Web Service ==="
        build_and_push_image "web"
        apply_manifests "web"
        echo "Web service deployment completed successfully"
        echo ""
    fi
    
    if [[ "$deploy_worker" == true ]]; then
        echo "=== Deploying Worker Service ==="
        build_and_push_image "worker"
        apply_manifests "worker"
        echo "Worker service deployment completed successfully"
        echo ""
    fi
    
    if [[ "$deploy_mcp_server" == true ]]; then
        echo "=== Deploying MCP Server Service ==="
        build_and_push_image "mcp-server"
        apply_manifests "mcp-server"
        echo "MCP server service deployment completed successfully"
        echo ""
    fi
    
    if [[ "$deploy_db_migrate" == true ]]; then
        echo "=== Deploying Database Migration ==="
        build_and_push_image "db-migrate"
        apply_db_migrate
        echo "Database migration deployment completed successfully"
        echo ""
    fi
    
    echo "All specified services have been deployed successfully!"
}

main "$@"