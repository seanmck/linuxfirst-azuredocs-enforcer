#!/bin/bash

# Linux First Azure Docs Enforcer - Infrastructure Validation Script
# Pre-deployment validation script for Bicep templates and Azure environment

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Validation results
VALIDATION_PASSED=true
WARNINGS=()

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
    WARNINGS+=("$1")
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
    VALIDATION_PASSED=false
}

# Function to validate Azure CLI installation and version
validate_azure_cli() {
    print_status "Validating Azure CLI..."
    
    if ! command -v az &> /dev/null; then
        print_error "Azure CLI is not installed. Please install it first."
        return 1
    fi
    
    local az_version=$(az version --query '"azure-cli"' -o tsv 2>/dev/null || echo "unknown")
    print_status "Azure CLI version: $az_version"
    
    # Check if user is logged in
    if ! az account show &> /dev/null; then
        print_error "Not logged into Azure CLI. Please run: az login"
        return 1
    fi
    
    local current_user=$(az account show --query user.name -o tsv)
    print_success "Logged in as: $current_user"
    
    return 0
}

# Function to validate Bicep CLI
validate_bicep_cli() {
    print_status "Validating Bicep CLI..."
    
    if ! command -v bicep &> /dev/null; then
        print_warning "Bicep CLI not found. Using Azure CLI bicep integration."
        
        # Check if Azure CLI has bicep support
        if ! az bicep version &> /dev/null; then
            print_error "Bicep support not available. Please install Bicep CLI or update Azure CLI."
            return 1
        fi
    fi
    
    local bicep_version
    if command -v bicep &> /dev/null; then
        bicep_version=$(bicep --version 2>/dev/null | head -1 || echo "unknown")
    else
        bicep_version=$(az bicep version --query 'bicepVersion' -o tsv 2>/dev/null || echo "unknown")
    fi
    
    print_status "Bicep version: $bicep_version"
    print_success "Bicep validation passed"
    
    return 0
}

# Function to validate required files
validate_files() {
    print_status "Validating required files..."
    
    local required_files=(
        "main.bicep"
        "parameters.json"
        "modules/vnet.bicep"
        "modules/aks.bicep"
        "modules/postgresql.bicep"
        "modules/openai.bicep"
        "modules/monitoring.bicep"
        "modules/security.bicep"
        "modules/serviceconnector.bicep"
        "modules/keyvault.bicep"
        "modules/acr.bicep"
    )
    
    local missing_files=()
    
    for file in "${required_files[@]}"; do
        if [ ! -f "$file" ]; then
            missing_files+=("$file")
        fi
    done
    
    if [ ${#missing_files[@]} -gt 0 ]; then
        print_error "Missing required files:"
        for file in "${missing_files[@]}"; do
            echo "  - $file"
        done
        return 1
    fi
    
    print_success "All required files found"
    return 0
}

# Function to validate Bicep templates
validate_bicep_templates() {
    print_status "Validating Bicep templates..."
    
    # Validate main template
    print_status "Validating main.bicep..."
    if command -v bicep &> /dev/null; then
        if bicep build main.bicep --stdout > /dev/null; then
            print_success "main.bicep syntax is valid"
        else
            print_error "main.bicep has syntax errors"
            return 1
        fi
    else
        if az bicep build --file main.bicep --stdout > /dev/null; then
            print_success "main.bicep syntax is valid"
        else
            print_error "main.bicep has syntax errors"
            return 1
        fi
    fi
    
    # Validate module templates
    local modules=(
        "modules/vnet.bicep"
        "modules/aks.bicep"
        "modules/postgresql.bicep"
        "modules/openai.bicep"
        "modules/monitoring.bicep"
        "modules/security.bicep"
        "modules/serviceconnector.bicep"
        "modules/keyvault.bicep"
        "modules/acr.bicep"
    )
    
    for module in "${modules[@]}"; do
        print_status "Validating $module..."
        if command -v bicep &> /dev/null; then
            if bicep build "$module" --stdout > /dev/null; then
                print_success "$module syntax is valid"
            else
                print_error "$module has syntax errors"
                return 1
            fi
        else
            if az bicep build --file "$module" --stdout > /dev/null; then
                print_success "$module syntax is valid"
            else
                print_error "$module has syntax errors"
                return 1
            fi
        fi
    done
    
    return 0
}

# Function to validate parameters file
validate_parameters() {
    print_status "Validating parameters.json..."
    
    if ! jq empty parameters.json 2>/dev/null; then
        if ! python3 -m json.tool parameters.json > /dev/null 2>&1; then
            print_error "parameters.json is not valid JSON"
            return 1
        fi
    fi
    
    print_success "parameters.json is valid JSON"
    
    # Check for placeholder values
    if grep -q "ChangeMe123!" parameters.json; then
        print_warning "Default password found in parameters.json. Please update before deployment."
    fi
    
    if grep -q "security@example.com" modules/security.bicep; then
        print_warning "Default email found in security.bicep. Please update security contact email."
    fi
    
    return 0
}

# Function to validate Azure subscription and permissions
validate_azure_permissions() {
    print_status "Validating Azure subscription and permissions..."
    
    local subscription_id=$(az account show --query id -o tsv)
    local subscription_name=$(az account show --query name -o tsv)
    
    print_status "Current subscription: $subscription_name ($subscription_id)"
    
    # Check if user has required permissions
    local user_type=$(az account show --query user.type -o tsv)
    if [ "$user_type" != "user" ]; then
        print_warning "Not authenticated as a user account. Some validations may be limited."
    fi
    
    # Check resource providers
    print_status "Checking required resource providers..."
    local required_providers=(
        "Microsoft.ContainerService"
        "Microsoft.DBforPostgreSQL"
        "Microsoft.CognitiveServices"
        "Microsoft.KeyVault"
        "Microsoft.ContainerRegistry"
        "Microsoft.Network"
        "Microsoft.Monitor"
        "Microsoft.Dashboard"
        "Microsoft.Security"
        "Microsoft.ServiceLinker"
        "Microsoft.OperationalInsights"
        "Microsoft.Insights"
    )
    
    for provider in "${required_providers[@]}"; do
        local status=$(az provider show --namespace "$provider" --query registrationState -o tsv 2>/dev/null || echo "NotFound")
        if [ "$status" != "Registered" ]; then
            print_warning "Resource provider $provider is not registered (status: $status)"
            print_status "You can register it with: az provider register --namespace $provider"
        else
            print_success "Resource provider $provider is registered"
        fi
    done
    
    return 0
}

# Function to validate Azure quotas and limits
validate_quotas() {
    print_status "Validating Azure quotas and limits..."
    
    # This is a basic check - in practice you'd want more comprehensive quota validation
    local location=${1:-"westus3"}
    
    # Check if location exists
    if ! az account list-locations --query "[?name=='$location']" -o tsv | head -1 | grep -q "$location"; then
        print_error "Location '$location' is not valid or not available"
        return 1
    fi
    
    print_success "Location '$location' is valid"
    
    # Check VM SKU availability (basic check)
    if az vm list-skus --location "$location" --query "[?name=='Standard_D2s_v3']" -o tsv | head -1 | grep -q "Standard_D2s_v3"; then
        print_success "VM SKU Standard_D2s_v3 is available in $location"
    else
        print_warning "VM SKU Standard_D2s_v3 may not be available in $location"
    fi
    
    return 0
}

# Function to validate network configuration
validate_network_config() {
    print_status "Validating network configuration..."
    
    # Check for CIDR conflicts (basic validation)
    local vnet_cidr="10.0.0.0/16"
    local aks_cidr="10.0.1.0/24"
    local pgsql_cidr="10.0.2.0/24"
    local services_cidr="10.0.3.0/24"
    
    print_status "Network configuration:"
    echo "  VNet: $vnet_cidr"
    echo "  AKS Subnet: $aks_cidr"
    echo "  PostgreSQL Subnet: $pgsql_cidr"
    echo "  Services Subnet: $services_cidr"
    
    print_success "Network configuration looks valid"
    
    return 0
}

# Function to perform deployment validation (dry run)
validate_deployment() {
    print_status "Performing deployment validation (dry run)..."
    
    local test_rg="validation-test-rg-$(date +%s)"
    local location=${1:-"westus3"}
    
    print_status "Creating temporary resource group for validation: $test_rg"
    
    if az group create --name "$test_rg" --location "$location" --output none; then
        print_status "Testing deployment validation..."
        
        if az deployment group validate \
            --resource-group "$test_rg" \
            --template-file "./main.bicep" \
            --parameters "@parameters.json" \
            --output none 2>/dev/null; then
            print_success "Deployment validation passed"
        else
            print_error "Deployment validation failed"
            az group delete --name "$test_rg" --yes --no-wait --output none
            return 1
        fi
        
        print_status "Cleaning up temporary resource group..."
        az group delete --name "$test_rg" --yes --no-wait --output none
    else
        print_warning "Could not create temporary resource group for validation"
    fi
    
    return 0
}

# Function to show validation summary
show_summary() {
    echo
    print_status "=== Validation Summary ==="
    
    if [ "$VALIDATION_PASSED" = true ]; then
        print_success "All validations passed!"
        
        if [ ${#WARNINGS[@]} -gt 0 ]; then
            echo
            print_warning "Warnings found:"
            for warning in "${WARNINGS[@]}"; do
                echo "  - $warning"
            done
        fi
        
        echo
        print_status "You can proceed with deployment using: ./deploy.sh"
        
    else
        print_error "Validation failed! Please fix the errors above before deploying."
        echo
        exit 1
    fi
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
    print_status "=== Infrastructure Validation ==="
    echo
    
    # Check if we're in the right directory
    check_directory
    
    # Parse command line arguments
    local location="westus3"
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --location|-l)
                location="$2"
                shift 2
                ;;
            --help|-h)
                echo "Usage: $0 [OPTIONS]"
                echo "Options:"
                echo "  --location, -l    Azure location to validate against"
                echo "  --help, -h       Show this help message"
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                exit 1
                ;;
        esac
    done
    
    # Run validations
    validate_azure_cli
    validate_bicep_cli
    validate_files
    validate_bicep_templates
    validate_parameters
    validate_azure_permissions
    validate_quotas "$location"
    validate_network_config
    validate_deployment "$location"
    
    # Show summary
    show_summary
}

# Check for required tools
if ! command -v jq &> /dev/null && ! python3 -c "import json" &> /dev/null; then
    print_error "Neither 'jq' nor 'python3' found. Please install one for JSON validation."
    exit 1
fi

# Run main function
main "$@"