#!/bin/bash
# Quick setup for Key Vault integration with existing AKS cluster

set -e

# Configuration
NAMESPACE="azuredocs-app"
AKS_CLUSTER_NAME="linuxdocs"
RESOURCE_GROUP="linuxdocsrg"
LOCATION="westus3"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() {
    echo -e "${GREEN}[$(date +'%H:%M:%S')] $1${NC}"
}

warn() {
    echo -e "${YELLOW}[$(date +'%H:%M:%S')] $1${NC}"
}

info() {
    echo -e "${BLUE}[$(date +'%H:%M:%S')] $1${NC}"
}

# Function to prompt for secrets
get_secrets() {
    echo
    info "Setting up secrets for Azure Docs Enforcer"
    echo
    
    # Admin password
    while true; do
        read -s -p "Enter admin password (min 12 chars, mix of letters/numbers/symbols): " ADMIN_PASSWORD
        echo
        read -s -p "Confirm admin password: " ADMIN_PASSWORD_CONFIRM
        echo
        
        if [[ "$ADMIN_PASSWORD" != "$ADMIN_PASSWORD_CONFIRM" ]]; then
            warn "Passwords don't match. Please try again."
            continue
        fi
        
        if [[ ${#ADMIN_PASSWORD} -lt 12 ]]; then
            warn "Password must be at least 12 characters. Please try again."
            continue
        fi
        
        if ! echo "$ADMIN_PASSWORD" | grep -q '[A-Z]' || \
           ! echo "$ADMIN_PASSWORD" | grep -q '[a-z]' || \
           ! echo "$ADMIN_PASSWORD" | grep -q '[0-9]' || \
           ! echo "$ADMIN_PASSWORD" | grep -q '[^A-Za-z0-9]'; then
            warn "Password must contain uppercase, lowercase, numbers, and special characters."
            continue
        fi
        
        break
    done
    
    # GitHub token
    echo
    read -s -p "Enter GitHub personal access token (ghp_...): " GITHUB_TOKEN
    echo
    
    if [[ ! "$GITHUB_TOKEN" =~ ^ghp_ ]]; then
        warn "GitHub token should start with 'ghp_'"
    fi
}

# Main setup function
main() {
    log "Setting up Azure Key Vault integration for Azure Docs Enforcer"
    
    # Get tenant and subscription info
    TENANT_ID=$(az account show --query tenantId -o tsv)
    SUBSCRIPTION_ID=$(az account show --query id -o tsv)
    
    log "Using tenant: $TENANT_ID"
    log "Using subscription: $SUBSCRIPTION_ID"
    
    # Check if we can reuse existing Key Vault or create new one
    echo
    info "Available Key Vaults in your subscription:"
    az keyvault list --query '[].{Name:name, ResourceGroup:resourceGroup, Location:location}' -o table
    echo
    
    read -p "Enter Key Vault name to use (or press Enter to create new): " KEY_VAULT_NAME
    
    if [[ -z "$KEY_VAULT_NAME" ]]; then
        # Create new Key Vault
        KEY_VAULT_NAME="azuredocs-kv-$(date +%s)"
        log "Creating new Key Vault: $KEY_VAULT_NAME"
        
        az keyvault create \
            --name "$KEY_VAULT_NAME" \
            --resource-group "$RESOURCE_GROUP" \
            --location "$LOCATION" \
            --enable-rbac-authorization false \
            --enabled-for-template-deployment true
    else
        log "Using existing Key Vault: $KEY_VAULT_NAME"
    fi
    
    # Get OIDC issuer URL
    OIDC_ISSUER_URL=$(az aks show --name "$AKS_CLUSTER_NAME" --resource-group "$RESOURCE_GROUP" --query "securityProfile.oidcIssuer.issuerUrl" -o tsv)
    log "OIDC Issuer URL: $OIDC_ISSUER_URL"
    
    # Create user-assigned managed identity
    IDENTITY_NAME="azuredocs-secret-reader"
    log "Creating managed identity: $IDENTITY_NAME"
    
    az identity create --name "$IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --location "$LOCATION"
    
    # Get identity details
    IDENTITY_CLIENT_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --query clientId -o tsv)
    IDENTITY_PRINCIPAL_ID=$(az identity show --name "$IDENTITY_NAME" --resource-group "$RESOURCE_GROUP" --query principalId -o tsv)
    
    log "Identity Client ID: $IDENTITY_CLIENT_ID"
    
    # Create federated identity credential
    log "Creating federated identity credential"
    az identity federated-credential create \
        --name "azuredocs-federated-credential" \
        --identity-name "$IDENTITY_NAME" \
        --resource-group "$RESOURCE_GROUP" \
        --issuer "$OIDC_ISSUER_URL" \
        --subject "system:serviceaccount:$NAMESPACE:secret-reader-sa" \
        --audience "api://AzureADTokenExchange"
    
    # Set Key Vault access policy
    log "Setting Key Vault access policy"
    az keyvault set-policy \
        --name "$KEY_VAULT_NAME" \
        --object-id "$IDENTITY_PRINCIPAL_ID" \
        --secret-permissions get list
    
    # Get secrets from user
    get_secrets
    
    # Store secrets in Key Vault
    log "Storing secrets in Key Vault"
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "admin-password" --value "$ADMIN_PASSWORD" > /dev/null
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "github-token" --value "$GITHUB_TOKEN" > /dev/null
    
    # Generate MCP secret key
    MCP_SECRET_KEY=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-32)
    az keyvault secret set --vault-name "$KEY_VAULT_NAME" --name "mcp-secret-key" --value "$MCP_SECRET_KEY" > /dev/null
    
    log "Secrets stored successfully"
    
    # Create namespace
    kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
    
    # Create ServiceAccount
    log "Creating Kubernetes ServiceAccount"
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: secret-reader-sa
  namespace: $NAMESPACE
  annotations:
    azure.workload.identity/client-id: "$IDENTITY_CLIENT_ID"
  labels:
    azure.workload.identity/use: "true"
EOF
    
    # Create SecretProviderClass
    log "Creating SecretProviderClass"
    cat <<EOF | kubectl apply -f -
apiVersion: secrets-store.csi.x-k8s.io/v1
kind: SecretProviderClass
metadata:
  name: azuredocs-secrets
  namespace: $NAMESPACE
spec:
  provider: azure
  parameters:
    usePodIdentity: "false"
    useVMManagedIdentity: "false"
    userAssignedIdentityID: "$IDENTITY_CLIENT_ID"
    keyvaultName: "$KEY_VAULT_NAME"
    cloudName: ""
    objects: |
      array:
        - |
          objectName: admin-password
          objectType: secret
          objectVersion: ""
        - |
          objectName: github-token
          objectType: secret
          objectVersion: ""
        - |
          objectName: mcp-secret-key
          objectType: secret
          objectVersion: ""
    tenantId: "$TENANT_ID"
  secretObjects:
  - secretName: azuredocs-secrets
    type: Opaque
    data:
    - objectName: admin-password
      key: ADMIN_PASSWORD
    - objectName: github-token
      key: GITHUB_TOKEN
    - objectName: mcp-secret-key
      key: MCP_SECRET_KEY
EOF
    
    # Create test pod to verify secrets work
    log "Creating test pod to verify secret mounting"
    cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: secret-test
  namespace: $NAMESPACE
spec:
  serviceAccountName: secret-reader-sa
  containers:
  - name: test
    image: mcr.microsoft.com/oss/nginx/nginx:1.17.3-alpine
    volumeMounts:
    - name: secrets-store
      mountPath: "/mnt/secrets-store"
      readOnly: true
    env:
    - name: ADMIN_PASSWORD
      valueFrom:
        secretKeyRef:
          name: azuredocs-secrets
          key: ADMIN_PASSWORD
  volumes:
  - name: secrets-store
    csi:
      driver: secrets-store.csi.k8s.io
      readOnly: true
      volumeAttributes:
        secretProviderClass: "azuredocs-secrets"
EOF
    
    log "Waiting for test pod to be ready..."
    kubectl wait --for=condition=ready pod/secret-test -n "$NAMESPACE" --timeout=60s
    
    # Test secret access
    log "Testing secret access..."
    if kubectl exec secret-test -n "$NAMESPACE" -- ls /mnt/secrets-store/ | grep -q admin-password; then
        log "✅ Secrets successfully mounted!"
        kubectl exec secret-test -n "$NAMESPACE" -- ls -la /mnt/secrets-store/
    else
        warn "❌ Secret mounting failed"
    fi
    
    # Check if Kubernetes secret was created
    if kubectl get secret azuredocs-secrets -n "$NAMESPACE" &>/dev/null; then
        log "✅ Kubernetes secret created successfully"
        kubectl get secret azuredocs-secrets -n "$NAMESPACE" -o jsonpath='{.data}' | jq -r 'keys[]'
    fi
    
    # Cleanup test pod
    kubectl delete pod secret-test -n "$NAMESPACE"
    
    # Update existing webui deployment if it exists
    if kubectl get deployment webui -n "$NAMESPACE" &>/dev/null; then
        log "Updating existing webui deployment to use secrets"
        
        # Patch the deployment to use the service account and secrets
        kubectl patch deployment webui -n "$NAMESPACE" --type='merge' -p='{
          "spec": {
            "template": {
              "spec": {
                "serviceAccountName": "secret-reader-sa"
              }
            }
          }
        }'
        
        # Add environment variables for admin password
        kubectl patch deployment webui -n "$NAMESPACE" --type='json' -p='[
          {
            "op": "add",
            "path": "/spec/template/spec/containers/0/env/-",
            "value": {
              "name": "ADMIN_PASSWORD",
              "valueFrom": {
                "secretKeyRef": {
                  "name": "azuredocs-secrets",
                  "key": "ADMIN_PASSWORD"
                }
              }
            }
          }
        ]'
        
        # Add volume mount for secrets
        kubectl patch deployment webui -n "$NAMESPACE" --type='json' -p='[
          {
            "op": "add",
            "path": "/spec/template/spec/volumes/-",
            "value": {
              "name": "secrets-store",
              "csi": {
                "driver": "secrets-store.csi.k8s.io",
                "readOnly": true,
                "volumeAttributes": {
                  "secretProviderClass": "azuredocs-secrets"
                }
              }
            }
          },
          {
            "op": "add",
            "path": "/spec/template/spec/containers/0/volumeMounts/-",
            "value": {
              "name": "secrets-store",
              "mountPath": "/mnt/secrets-store",
              "readOnly": true
            }
          }
        ]'
        
        log "Restarting webui deployment..."
        kubectl rollout restart deployment/webui -n "$NAMESPACE"
        kubectl rollout status deployment/webui -n "$NAMESPACE" --timeout=120s
        
        log "✅ WebUI updated to use Key Vault secrets"
    fi
    
    echo
    info "🎉 Setup completed successfully!"
    echo
    echo "📋 Summary:"
    echo "  Key Vault: $KEY_VAULT_NAME"
    echo "  Managed Identity: $IDENTITY_NAME"
    echo "  Client ID: $IDENTITY_CLIENT_ID"
    echo "  Namespace: $NAMESPACE"
    echo
    echo "🔧 Next steps:"
    echo "  1. Test admin login with your new password"
    echo "  2. View secrets: kubectl get secret azuredocs-secrets -n $NAMESPACE"
    echo "  3. Check pods: kubectl get pods -n $NAMESPACE"
    echo "  4. Manage secrets: ./scripts/manage-secrets.sh list"
    echo
    echo "🔐 Your admin password is now securely stored in Azure Key Vault!"
}

main "$@"
