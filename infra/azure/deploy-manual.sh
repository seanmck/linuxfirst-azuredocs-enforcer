#!/bin/bash

# Manual deployment workaround for Azure CLI "content already consumed" issue

echo "=== Manual Deployment Instructions ==="
echo
echo "Due to an Azure CLI issue, please deploy manually using one of these methods:"
echo
echo "METHOD 1: Azure Portal Deployment"
echo "1. Go to https://portal.azure.com"
echo "2. Search for 'Deploy a custom template'"
echo "3. Click 'Build your own template in the editor'"
echo "4. Copy the contents of main.json (compiled ARM template)"
echo "5. Use these parameters:"
echo "   - Resource Group: linuxdocsrg-20250722"
echo "   - Location: westus3"
echo "   - Environment: production"
echo "   - Resource Prefix: linuxfirstdocs"
echo "   - PostgreSQL Admin Login: pgadmin"
echo "   - PostgreSQL Admin Password: xCUbR!2pG!dH6nJi"
echo "   - Create Key Vault: true"
echo "   - Create Container Registry: true"
echo
echo "METHOD 2: Azure Cloud Shell"
echo "1. Go to https://shell.azure.com"
echo "2. Upload the main.bicep and parameters.json files"
echo "3. Run: az deployment group create --resource-group linuxdocsrg-20250722 --template-file main.bicep --parameters @parameters.json"
echo
echo "METHOD 3: Different Azure CLI Version"
echo "1. Try using Azure CLI in a different environment (Docker, VM, etc.)"
echo "2. Or wait for Azure CLI to be updated to fix this bug"
echo
echo "The templates are validated and ready to deploy - this is just an Azure CLI issue."
echo
echo "Files ready for deployment:"
echo "- main.bicep (Bicep template)"
echo "- main.json (Compiled ARM template)"
echo "- parameters.json (Parameters file)"
echo
echo "Expected deployment time: 15-30 minutes"
echo "Infrastructure includes: AKS, PostgreSQL, OpenAI, Monitoring, Security policies"