// Parameters
@description('Location for all resources')
param location string

@description('OpenAI service name')
param serviceName string

@description('Services subnet resource ID')
param subnetId string

@description('OpenAI private DNS zone resource ID')
param privateDnsZoneId string

@description('Resource tags')
param tags object

@description('Log Analytics workspace resource ID for diagnostics')
param logAnalyticsWorkspaceId string = ''

@description('SKU name')
param skuName string = 'S0'

@description('Public network access')
param publicNetworkAccess string = 'Disabled'

@description('GPT-4 model deployment name')
param gpt4DeploymentName string = 'gpt-4'

@description('GPT-4 model name')
param gpt4ModelName string = 'gpt-4'

@description('GPT-4 model version')
param gpt4ModelVersion string = 'turbo-2024-04-09'

@description('GPT-4 deployment capacity (TPM)')
param gpt4Capacity int = 10

// Variables
var privateEndpointName = '${serviceName}-pe'
var networkInterfaceName = '${serviceName}-pe-nic'

// Azure OpenAI Service
resource openaiService 'Microsoft.CognitiveServices/accounts@2023-10-01-preview' = {
  name: serviceName
  location: location
  tags: tags
  kind: 'OpenAI'
  sku: {
    name: skuName
  }
  properties: {
    customSubDomainName: serviceName
    publicNetworkAccess: publicNetworkAccess
    networkAcls: {
      defaultAction: 'Deny'
      virtualNetworkRules: []
      ipRules: []
    }
    restrictOutboundNetworkAccess: false
  }
}

// GPT-4 Model Deployment
resource gpt4Deployment 'Microsoft.CognitiveServices/accounts/deployments@2023-10-01-preview' = {
  parent: openaiService
  name: gpt4DeploymentName
  properties: {
    model: {
      format: 'OpenAI'
      name: gpt4ModelName
      version: gpt4ModelVersion
    }
    raiPolicyName: 'Microsoft.Default'
  }
  sku: {
    name: 'Standard'
    capacity: gpt4Capacity
  }
}

// Private Endpoint for OpenAI
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
          privateLinkServiceId: openaiService.id
          groupIds: [
            'account'
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
        name: 'privatelink-openai-azure-com'
        properties: {
          privateDnsZoneId: privateDnsZoneId
        }
      }
    ]
  }
}

// Diagnostic settings for monitoring
resource diagnosticSettings 'Microsoft.Insights/diagnosticSettings@2021-05-01-preview' = if (logAnalyticsWorkspaceId != '') {
  name: '${serviceName}-diagnostics'
  scope: openaiService
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
@description('OpenAI service resource ID')
output serviceId string = openaiService.id

@description('OpenAI service name')
output serviceName string = openaiService.name

@description('OpenAI service endpoint')
output serviceEndpoint string = openaiService.properties.endpoint

// Note: Service key is available via managed identity - no need to expose in outputs

@description('GPT-4 deployment name')
output gpt4DeploymentName string = gpt4Deployment.name

@description('Private endpoint resource ID')
output privateEndpointId string = privateEndpoint.id

@description('Private endpoint IP address')
output privateEndpointIp string = length(privateEndpoint.properties.customDnsConfigs) > 0 && length(privateEndpoint.properties.customDnsConfigs[0].ipAddresses) > 0 ? privateEndpoint.properties.customDnsConfigs[0].ipAddresses[0] : 'Pending'