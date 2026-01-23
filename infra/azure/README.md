# Linux First Azure Docs Enforcer - Infrastructure

This directory contains Bicep templates and deployment scripts for the Linux First Azure Docs Enforcer application infrastructure.

## 🏗️ Architecture

The infrastructure includes:

- **AKS Cluster** - Kubernetes cluster with auto-scaling, workload identity, and security features
- **PostgreSQL** - Flexible Server with private endpoint and VNet integration
- **Azure OpenAI** - GPT-4 deployment with private endpoint
- **Monitoring Stack** - Azure managed Prometheus and Grafana
- **Security** - Microsoft Defender across all services
- **Optional Services** - Key Vault and Container Registry with private endpoints

## 📁 File Structure

```
infra/azure/
├── main.bicep              # Main orchestration template
├── parameters.json         # Default parameters template
├── deploy.sh              # Interactive deployment script
├── validate.sh            # Pre-deployment validation script
├── plan.md                # Infrastructure requirements
└── modules/               # Bicep modules
    ├── vnet.bicep         # Virtual network and subnets
    ├── aks.bicep          # AKS cluster
    ├── postgresql.bicep   # PostgreSQL Flexible Server
    ├── openai.bicep       # Azure OpenAI
    ├── monitoring.bicep   # Prometheus/Grafana stack
    ├── security.bicep     # Microsoft Defender
    ├── serviceconnector.bicep # Service connections
    ├── keyvault.bicep     # Key Vault (optional)
    └── acr.bicep          # Container Registry (optional)
```

## 🚀 Quick Start

### Prerequisites

1. **Azure CLI** - Install and login
   ```bash
   az login
   ```

2. **Bicep CLI** (recommended)
   ```bash
   az bicep install
   ```

### Deployment Steps

1. **Navigate to the correct directory:**
   ```bash
   cd infra/azure
   ```

2. **Validate the deployment:**
   ```bash
   ./validate.sh
   ```

3. **Deploy the infrastructure:**
   ```bash
   ./deploy.sh                    # Interactive mode
   # OR
   ./deploy.sh --accept-defaults  # Use all default values (non-interactive)
   ```

4. **Connect to your AKS cluster:**
   ```bash
   az aks get-credentials --resource-group <resource-group> --name <aks-cluster-name>
   kubectl get nodes
   ```

## ⚙️ Configuration

### Default Configuration

- **Location:** WestUS3
- **Resource Group:** `linuxdocsrg-YYYYMMDD`
- **Resource Prefix:** `linuxfirstdocs`
- **Network:** 10.0.0.0/16 (with dedicated subnets)

### Customization

The deployment script will prompt you to customize:
- Azure subscription
- Resource group name
- Location
- All resource names
- Optional services (Key Vault, Container Registry)
- PostgreSQL credentials

You can also edit `parameters.json` directly for automated deployments.

### Non-Interactive Deployment

For CI/CD pipelines or automated deployments, use the `--accept-defaults` flag:

```bash
# Use all default values
./deploy.sh --accept-defaults

# Use defaults but override specific values
./deploy.sh --accept-defaults --location eastus2 --resource-group my-custom-rg

# Combine with other flags
./deploy.sh -d -s "your-subscription-id" -g "prod-rg" -l "westus2"
```

**Default Values when using --accept-defaults:**
- **Resource Group:** `linuxdocsrg-YYYYMMDD` (current date)
- **Location:** `westus3`
- **Resource Prefix:** `linuxfirstdocs`
- **Optional Services:** Both Key Vault and ACR will be created
- **PostgreSQL Password:** `ChangeMe123!` ⚠️ **Change this for production!**

## 🛡️ Security Features

- **Microsoft Defender** enabled for all services
- **Private endpoints** for all services (no public access)
- **Workload identity** for AKS authentication
- **Azure Policy** assignments for compliance
- **Network security groups** with restrictive rules
- **RBAC** authorization for Key Vault

## 📊 Monitoring Features

- **Azure Monitor Workspace** - Fully managed Prometheus
- **Azure Managed Grafana** - Pre-built dashboards
- **Log Analytics** - Centralized logging
- **Application Insights** - Application monitoring
- **Alert rules** - Proactive monitoring

## 🔧 Command Line Options

### deploy.sh
```bash
./deploy.sh [OPTIONS]
  --subscription, -s      Azure subscription ID
  --resource-group, -g    Resource group name
  --location, -l          Azure location
  --accept-defaults, -d   Accept all default values (non-interactive)
  --help, -h             Show help message
```

### validate.sh
```bash
./validate.sh [OPTIONS]
  --location, -l    Azure location to validate against
  --help, -h       Show help message
```

## 🔍 Validation Checks

The validation script checks:
- Azure CLI installation and login
- Bicep CLI availability
- Template syntax validation
- JSON parameter validation
- Azure permissions and quotas
- Resource provider registration
- Network configuration
- Deployment dry-run

## 📝 Important Notes

1. **Default Password**: The `parameters.json` contains a default password. Change it before deployment.
2. **Security Email**: Update the security contact email in `modules/security.bicep`.
3. **Resource Providers**: The script will warn about unregistered providers - register them if needed.
4. **Directory**: Always run scripts from the `infra/azure` directory.

## 🚨 Troubleshooting

### Common Issues

1. **"Could not find file 'main.bicep'"**
   - Ensure you're running the script from the `infra/azure` directory

2. **"Template validation failed"**
   - Run `./validate.sh` to identify specific issues
   - Check that all required resource providers are registered

3. **"Deployment failed"**
   - Check the Azure portal for detailed error messages
   - Verify you have sufficient permissions and quotas

## 🧹 Cleanup

To delete all resources:
```bash
az group delete --name <resource-group-name>
```

## 📚 Additional Resources

- [Azure Bicep Documentation](https://docs.microsoft.com/en-us/azure/azure-resource-manager/bicep/)
- [AKS Documentation](https://docs.microsoft.com/en-us/azure/aks/)
- [Azure Monitor managed service for Prometheus](https://docs.microsoft.com/en-us/azure/azure-monitor/essentials/prometheus-metrics-overview)
- [Microsoft Defender for Cloud](https://docs.microsoft.com/en-us/azure/defender-for-cloud/)