// Parameters
@description('Location for all resources')
param location string

@description('Container Registry name')
param registryName string

@description('Services subnet resource ID')
param subnetId string

@description('ACR private DNS zone resource ID')
param privateDnsZoneId string

@description('Resource tags')
param tags object

@description('Log Analytics workspace resource ID for diagnostics')
param logAnalyticsWorkspaceId string = ''

@description('SKU name')
param skuName string = 'Premium'

@description('Enable admin user')
param adminUserEnabled bool = false

@description('Enable public network access')
param publicNetworkAccess string = 'Disabled'

@description('Enable zone redundancy')
param zoneRedundancy bool = false

// Variables
var privateEndpointName = '${registryName}-pe'
var networkInterfaceName = '${registryName}-pe-nic'

// Container Registry
resource containerRegistry 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: registryName
  location: location
  tags: tags
  sku: {
    name: skuName
  }
  properties: {
    adminUserEnabled: adminUserEnabled
    publicNetworkAccess: publicNetworkAccess
    zoneRedundancy: zoneRedundancy ? 'Enabled' : 'Disabled'
    
    // Network rule set (only for Premium SKU)
    networkRuleSet: skuName == 'Premium' ? {
      defaultAction: 'Deny'
    } : null
    
    // Policies
    policies: {
      quarantinePolicy: {
        status: 'Enabled'
      }
      trustPolicy: {
        type: 'Notary'
        status: 'Disabled'
      }
      retentionPolicy: {
        days: 30
        status: 'Enabled'
      }
    }
    
    // Encryption
    encryption: {
      status: 'Disabled'
    }
    
    // Data endpoint
    dataEndpointEnabled: false
  }
}

// Private Endpoint for ACR
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
          privateLinkServiceId: containerRegistry.id
          groupIds: [
            'registry'
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
        name: 'privatelink-azurecr-io'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

// Diagnostic settings for monitoring
resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (logAnalyticsWorkspaceId != '') {
  name: '${registryName}-diagnostics'
  scope: containerRegistry
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
@description('Container Registry resource ID')
output registryId string = containerRegistry.id

@description('Container Registry name')
output registryName string = containerRegistry.name

@description('Container Registry login server')
output loginServer string = containerRegistry.properties.loginServer

@description('Private endpoint resource ID')
output privateEndpointId string = privateEndpoint.id

@description('Private endpoint IP address')
output privateEndpointIp string = length(privateEndpoint.properties.customDnsConfigs) > 0 && length(privateEndpoint.properties.customDnsConfigs[0].ipAddresses) > 0 ? privateEndpoint.properties.customDnsConfigs[0].ipAddresses[0] : 'Pending'