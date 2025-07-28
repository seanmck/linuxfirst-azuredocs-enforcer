// Parameters
@description('Location for all resources')
param location string

@description('Key Vault name')
param keyVaultName string

@description('Services subnet resource ID')
param subnetId string

@description('Key Vault private DNS zone resource ID')
param privateDnsZoneId string

@description('Resource tags')
param tags object

@description('Log Analytics workspace resource ID for diagnostics')
param logAnalyticsWorkspaceId string = ''

@description('SKU name')
param skuName string = 'standard'

@description('Enable soft delete')
param enableSoftDelete bool = true

@description('Soft delete retention days')
param softDeleteRetentionInDays int = 90

@description('Enable purge protection')
param enablePurgeProtection bool = true

@description('Enable RBAC authorization')
param enableRbacAuthorization bool = true

// Variables
var privateEndpointName = '${keyVaultName}-pe'
var networkInterfaceName = '${keyVaultName}-pe-nic'

// Key Vault
resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: skuName
    }
    
    // Access policies (empty when using RBAC)
    accessPolicies: []
    
    // Security settings
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: true
    enableSoftDelete: enableSoftDelete
    softDeleteRetentionInDays: softDeleteRetentionInDays
    enablePurgeProtection: enablePurgeProtection
    enableRbacAuthorization: enableRbacAuthorization
    
    // Network settings
    publicNetworkAccess: 'Disabled'
    networkAcls: {
      defaultAction: 'Deny'
      bypass: 'AzureServices'
      virtualNetworkRules: []
      ipRules: []
    }
  }
}

// Private Endpoint for Key Vault
resource privateEndpoint 'Microsoft.Network/privateEndpoints@2023-11-01' = {
  name: privateEndpointName
  location: location
  tags: tags
  properties: {
    subnet: {
      id: subnetId
    }
    privateLinkServiceConnections: [
      {
        name: privateEndpointName
        properties: {
          privateLinkServiceId: keyVault.id
          groupIds: [
            'vault'
          ]
        }
      }
    ]
    customNetworkInterfaceName: networkInterfaceName
  }
}

// Private DNS Zone Group
resource privateDnsZoneGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2023-11-01' = {
  parent: privateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'privatelink-vaultcore-azure-net'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

// Sample secrets for the application (these would typically be set by the application deployment)
resource databaseConnectionSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'database-connection-string'
  properties: {
    value: 'placeholder-for-database-connection-string'
    attributes: {
      enabled: true
    }
  }
}

resource openaiApiKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVault
  name: 'openai-api-key'
  properties: {
    value: 'placeholder-for-openai-api-key'
    attributes: {
      enabled: true
    }
  }
}

// Diagnostic settings for monitoring
resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (logAnalyticsWorkspaceId != '') {
  name: '${keyVaultName}-diagnostics'
  scope: keyVault
  properties: {
    logs: [
      {
        categoryGroup: 'allLogs'
        enabled: true
      }
    ]
    metrics: [
      {
        category: 'AllMetrics'
        enabled: true
      }
    ]
    workspaceId: logAnalyticsWorkspaceId != '' ? logAnalyticsWorkspaceId : null
  }
}

// Outputs
@description('Key Vault resource ID')
output keyVaultId string = keyVault.id

@description('Key Vault name')
output keyVaultName string = keyVault.name

@description('Key Vault URI')
output keyVaultUri string = keyVault.properties.vaultUri

@description('Private endpoint resource ID')
output privateEndpointId string = privateEndpoint.id

@description('Private endpoint IP address')
output privateEndpointIp string = length(privateEndpoint.properties.customDnsConfigs) > 0 && length(privateEndpoint.properties.customDnsConfigs[0].ipAddresses) > 0 ? privateEndpoint.properties.customDnsConfigs[0].ipAddresses[0] : 'Pending'