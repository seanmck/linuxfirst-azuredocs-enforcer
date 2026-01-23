#!/bin/bash

# Linux First Azure Docs Enforcer - Infrastructure Deployment Script
# Interactive deployment script for Azure infrastructure

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Function to get current date in YYYYMMDD format
get_current_date() {
    date +%Y%m%d
}

# Function to validate Azure CLI installation and login
validate_azure_cli() {
    print_status "Validating Azure CLI..."
    
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI is not installed. Please install it first."
        exit 1
    fi
    
    # Check if user is logged in
    if ! az account show &> /dev/null; then
        print_error "Please log in to Azure CLI first: az login"
        exit 1
    fi
    
    print_success "Azure CLI validation passed"
}

# Function to get and validate subscription
get_subscription() {
    local current_sub=$(az account show --query id -o tsv 2>/dev/null || echo "")
    local current_name=$(az account show --query name -o tsv 2>/dev/null || echo "")
    
    if [ -n "$1" ]; then
        SUBSCRIPTION_ID="$1"
        print_status "Using provided subscription: $SUBSCRIPTION_ID"
    elif [ "$ACCEPT_DEFAULTS" = true ]; then
        SUBSCRIPTION_ID="$current_sub"
        print_status "Using current subscription (--accept-defaults): $current_name"
    else
        echo
        print_status "Current subscription: $current_name ($current_sub)"
        read -p "Use current subscription? (y/n) [y]: " use_current
        use_current=${use_current:-y}
        
        if [[ "$use_current" =~ ^[Yy]$ ]]; then
            SUBSCRIPTION_ID="$current_sub"
        else
            echo
            print_status "Available subscriptions:"
            az account list --query "[].{Name:name, SubscriptionId:id}" -o table
            echo
            read -p "Enter subscription ID: " SUBSCRIPTION_ID
        fi
    fi
    
    # Set the subscription
    az account set --subscription "$SUBSCRIPTION_ID"
    print_success "Using subscription: $(az account show --query name -o tsv)"
}

# Function to get resource group
get_resource_group() {
    local default_rg="linuxdocsrg-$(get_current_date)"
    
    if [ -n "$1" ]; then
        RESOURCE_GROUP="$1"
        print_status "Using provided resource group: $RESOURCE_GROUP"
    elif [ "$ACCEPT_DEFAULTS" = true ]; then
        RESOURCE_GROUP="$default_rg"
        print_status "Using default resource group (--accept-defaults): $RESOURCE_GROUP"
    else
        echo
        read -p "Enter resource group name [$default_rg]: " RESOURCE_GROUP
        RESOURCE_GROUP=${RESOURCE_GROUP:-$default_rg}
    fi
    
    # Check if resource group exists
    if az group show --name "$RESOURCE_GROUP" &> /dev/null; then
        print_status "Resource group '$RESOURCE_GROUP' already exists"
    else
        print_status "Resource group '$RESOURCE_GROUP' will be created"
    fi
}

# Function to get location
get_location() {
    local default_location="westus3"
    
    if [ -n "$1" ]; then
        LOCATION="$1"
        print_status "Using provided location: $LOCATION"
    elif [ "$ACCEPT_DEFAULTS" = true ]; then
        LOCATION="$default_location"
        print_status "Using default location (--accept-defaults): $LOCATION"
    else
        echo
        read -p "Enter location [$default_location]: " LOCATION
        LOCATION=${LOCATION:-$default_location}
    fi
    
    # Validate location
    if ! az account list-locations --query "[?name=='$LOCATION']" -o tsv | head -1 | grep -q "$LOCATION"; then
        print_warning "Location '$LOCATION' may not be valid. Continuing anyway..."
    fi
}

# Function to get resource names
get_resource_names() {
    local default_prefix="linuxfirstdocs"
    
    if [ "$ACCEPT_DEFAULTS" = true ]; then
        RESOURCE_PREFIX="$default_prefix"
        AKS_NAME="${RESOURCE_PREFIX}-aks"
        POSTGRESQL_NAME="${RESOURCE_PREFIX}-pgsql"
        OPENAI_NAME="${RESOURCE_PREFIX}-aoai"
        print_status "Using default resource names (--accept-defaults):"
        print_status "  Resource prefix: $RESOURCE_PREFIX"
        print_status "  AKS cluster: $AKS_NAME"
        print_status "  PostgreSQL server: $POSTGRESQL_NAME"
        print_status "  OpenAI service: $OPENAI_NAME"
    else
        echo
        print_status "Configure resource names:"
        
        read -p "Resource prefix [$default_prefix]: " RESOURCE_PREFIX
        RESOURCE_PREFIX=${RESOURCE_PREFIX:-$default_prefix}
        
        read -p "AKS cluster name [${RESOURCE_PREFIX}-aks]: " AKS_NAME
        AKS_NAME=${AKS_NAME:-${RESOURCE_PREFIX}-aks}
        
        read -p "PostgreSQL server name [${RESOURCE_PREFIX}-pgsql]: " POSTGRESQL_NAME
        POSTGRESQL_NAME=${POSTGRESQL_NAME:-${RESOURCE_PREFIX}-pgsql}
        
        read -p "OpenAI service name [${RESOURCE_PREFIX}-aoai]: " OPENAI_NAME
        OPENAI_NAME=${OPENAI_NAME:-${RESOURCE_PREFIX}-aoai}
    fi
}

# Function to get optional services
get_optional_services() {
    if [ "$ACCEPT_DEFAULTS" = true ]; then
        CREATE_KEY_VAULT="y"
        KV_NAME="${RESOURCE_PREFIX}-akv"
        CREATE_ACR="y"
        ACR_NAME=$(echo "${RESOURCE_PREFIX}acr" | tr -d '-')
        print_status "Using default optional services (--accept-defaults):"
        print_status "  Create Key Vault: yes ($KV_NAME)"
        print_status "  Create Container Registry: yes ($ACR_NAME)"
    else
        echo
        print_status "Configure optional services:"
        
        read -p "Create Key Vault? (y/n) [y]: " create_kv
        CREATE_KEY_VAULT=${create_kv:-y}
        
        if [[ "$CREATE_KEY_VAULT" =~ ^[Yy]$ ]]; then
            read -p "Key Vault name [${RESOURCE_PREFIX}-akv]: " KV_NAME
            KV_NAME=${KV_NAME:-${RESOURCE_PREFIX}-akv}
        fi
        
        read -p "Create Container Registry? (y/n) [y]: " create_acr
        CREATE_ACR=${create_acr:-y}
        
        if [[ "$CREATE_ACR" =~ ^[Yy]$ ]]; then
            local default_acr_name=$(echo "${RESOURCE_PREFIX}acr" | tr -d '-')
            read -p "Container Registry name [$default_acr_name]: " ACR_NAME
            ACR_NAME=${ACR_NAME:-$default_acr_name}
        fi
    fi
}

# Function to get database credentials
get_database_credentials() {
    if [ "$ACCEPT_DEFAULTS" = true ]; then
        PG_ADMIN_USER="pgadmin"
        PG_ADMIN_PASSWORD="ChangeMe123!"
        print_status "Using default PostgreSQL credentials (--accept-defaults):"
        print_status "  Username: $PG_ADMIN_USER"
        print_warning "  Password: Using default password - CHANGE THIS BEFORE PRODUCTION!"
    else
        echo
        print_status "Configure PostgreSQL credentials:"
        
        read -p "PostgreSQL admin username [pgadmin]: " PG_ADMIN_USER
        PG_ADMIN_USER=${PG_ADMIN_USER:-pgadmin}
        
        while true; do
            read -s -p "PostgreSQL admin password: " PG_ADMIN_PASSWORD
            echo
            read -s -p "Confirm password: " PG_ADMIN_PASSWORD_CONFIRM
            echo
            
            if [ "$PG_ADMIN_PASSWORD" = "$PG_ADMIN_PASSWORD_CONFIRM" ]; then
                if [ ${#PG_ADMIN_PASSWORD} -lt 8 ]; then
                    print_error "Password must be at least 8 characters long"
                    continue
                fi
                break
            else
                print_error "Passwords do not match"
            fi
        done
    fi
}

# Function to display deployment summary
show_deployment_summary() {
    echo
    print_status "=== Deployment Summary ==="
    echo "Subscription: $(az account show --query name -o tsv)"
    echo "Resource Group: $RESOURCE_GROUP"
    echo "Location: $LOCATION"
    echo "Resource Prefix: $RESOURCE_PREFIX"
    echo "AKS Cluster: $AKS_NAME"
    echo "PostgreSQL Server: $POSTGRESQL_NAME"
    echo "OpenAI Service: $OPENAI_NAME"
    
    if [[ "$CREATE_KEY_VAULT" =~ ^[Yy]$ ]]; then
        echo "Key Vault: $KV_NAME"
    fi
    
    if [[ "$CREATE_ACR" =~ ^[Yy]$ ]]; then
        echo "Container Registry: $ACR_NAME"
    fi
    
    echo
}

# Function to create parameters file
create_parameters_file() {
    local params_file="parameters.json"
    
    print_status "Creating parameters file..."
    
    cat > "$params_file" << EOF
{
  "\$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentParameters.json#",
  "contentVersion": "1.0.0.0",
  "parameters": {
    "location": {
      "value": "$LOCATION"
    },
    "environment": {
      "value": "production"
    },
    "resourcePrefix": {
      "value": "$RESOURCE_PREFIX"
    },
    "aksClusterName": {
      "value": "$AKS_NAME"
    },
    "postgresqlServerName": {
      "value": "$POSTGRESQL_NAME"
    },
    "openaiServiceName": {
      "value": "$OPENAI_NAME"
    },
    "postgresqlAdminLogin": {
      "value": "$PG_ADMIN_USER"
    },
    "postgresqlAdminPassword": {
      "value": "$PG_ADMIN_PASSWORD"
    },
    "createKeyVault": {
      "value": $([ "$CREATE_KEY_VAULT" = "y" ] && echo "true" || echo "false")
    },
    "createContainerRegistry": {
      "value": $([ "$CREATE_ACR" = "y" ] && echo "true" || echo "false")
    }$([ "$CREATE_KEY_VAULT" = "y" ] && echo ",
    \"keyVaultName\": {
      \"value\": \"$KV_NAME\"
    }")$([ "$CREATE_ACR" = "y" ] && echo ",
    \"containerRegistryName\": {
      \"value\": \"$ACR_NAME\"
    }")
  }
}
EOF
    
    print_success "Parameters file created: $params_file"
}

# Function to deploy infrastructure
deploy_infrastructure() {
    local params_file="parameters.json"
    local deployment_name="linuxdocs-$(get_current_date)-$(date +%H%M%S)"
    
    print_status "Starting infrastructure deployment..."
    
    # Create resource group if it doesn't exist
    if ! az group show --name "$RESOURCE_GROUP" &> /dev/null; then
        print_status "Creating resource group '$RESOURCE_GROUP'..."
        az group create --name "$RESOURCE_GROUP" --location "$LOCATION"
        print_success "Resource group created"
    fi
    
    # Build debug flag string
    local debug_flag=""
    if [ "$DEBUG_MODE" = true ]; then
        debug_flag="--debug"
        print_status "Debug mode enabled - Azure CLI will show detailed output"
    fi
    
    # Validate the deployment using what-if (workaround for Azure CLI validation bug)
    print_status "Validating Bicep template using what-if analysis..."
    if az deployment group what-if \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "./main.bicep" \
        --parameters "@$params_file" \
        $debug_flag; then
        print_success "Template validation passed"
    else
        print_error "Template validation failed"
        exit 1
    fi
    
    # Deploy the infrastructure
    print_status "Deploying infrastructure (this may take 15-30 minutes)..."
    if az deployment group create \
        --resource-group "$RESOURCE_GROUP" \
        --template-file "./main.bicep" \
        --parameters "@$params_file" \
        --name "$deployment_name" \
        --output table \
        $debug_flag; then
        print_success "Infrastructure deployment completed successfully!"
    else
        print_error "Infrastructure deployment failed"
        exit 1
    fi
    
    # Get outputs
    print_status "Retrieving deployment outputs..."
    az deployment group show \
        --resource-group "$RESOURCE_GROUP" \
        --name "$deployment_name" \
        --query properties.outputs \
        --output table
}

# Function to show next steps
show_next_steps() {
    echo
    print_success "=== Deployment Complete ==="
    echo
    print_status "Next steps:"
    echo "1. Configure kubectl to connect to your AKS cluster:"
    echo "   az aks get-credentials --resource-group $RESOURCE_GROUP --name $AKS_NAME"
    echo
    echo "2. Verify your cluster is running:"
    echo "   kubectl get nodes"
    echo
    echo "3. Access your Grafana dashboard:"
    echo "   Check the Azure portal for your Managed Grafana instance"
    echo
    echo "4. Deploy your application to the 'linuxdocs-namespace' namespace"
    echo
    print_status "Infrastructure deployment completed successfully!"
}

# Function to check if running from correct directory
check_directory() {
    if [ ! -f "main.bicep" ] || [ ! -f "parameters.json" ]; then
        print_error "Please run this script from the infra/azure directory where main.bicep is located"
        exit 1
    fi
}

# Main execution
main() {
    echo
    print_status "=== Linux First Azure Docs Enforcer - Infrastructure Deployment ==="
    echo
    
    # Check if we're in the right directory
    check_directory
    
    # Initialize variables
    ACCEPT_DEFAULTS=false
    DEBUG_MODE=false
    
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --subscription|-s)
                CMD_SUBSCRIPTION="$2"
                shift 2
                ;;
            --resource-group|-g)
                CMD_RESOURCE_GROUP="$2"
                shift 2
                ;;
            --location|-l)
                CMD_LOCATION="$2"
                shift 2
                ;;
            --accept-defaults|-d)
                ACCEPT_DEFAULTS=true
                shift
                ;;
            --debug)
                DEBUG_MODE=true
                shift
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --subscription, -s      Azure subscription ID"
                echo "  --resource-group, -g    Resource group name"
                echo "  --location, -l          Azure location"
                echo "  --accept-defaults, -d   Accept all default values (non-interactive)"
                echo "  --debug                Enable debug output for Azure CLI commands"
                echo "  --help, -h             Show this help message"
                echo
                echo "Examples:"
                echo "  $0                                    # Interactive mode"
                echo "  $0 --accept-defaults                  # Use all defaults"
                echo "  $0 -d -l eastus2 -g my-rg           # Defaults with custom location and RG"
                echo "  $0 --debug                           # Run with debug output"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Validate prerequisites
    validate_azure_cli
    
    # Get deployment configuration
    get_subscription "$CMD_SUBSCRIPTION"
    get_resource_group "$CMD_RESOURCE_GROUP"
    get_location "$CMD_LOCATION"
    get_resource_names
    get_optional_services
    get_database_credentials
    
    # Show summary and confirm
    show_deployment_summary
    
    if [ "$ACCEPT_DEFAULTS" = true ]; then
        print_status "Proceeding with deployment (--accept-defaults)"
    else
        read -p "Proceed with deployment? (y/n) [n]: " proceed
        proceed=${proceed:-n}
        
        if [[ ! "$proceed" =~ ^[Yy]$ ]]; then
            print_status "Deployment cancelled"
            exit 0
        fi
    fi
    
    # Create parameters and deploy
    create_parameters_file
    deploy_infrastructure
    show_next_steps
}

# Run main function
main "$@"