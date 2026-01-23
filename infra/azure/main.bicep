// Parameters
@description('Location for all resources')
param location string = resourceGroup().location

@description('Environment name (dev, staging, prod)')
param environment string = 'dev'

@description('Prefix for resource naming')
param resourcePrefix string = 'linuxfirstdocs'

@description('Virtual network address space')
param vnetAddressSpace string = '10.0.0.0/16'

@description('AKS subnet address space')
param aksSubnetAddressSpace string = '10.0.1.0/24'

@description('PostgreSQL subnet address space')
param postgresqlSubnetAddressSpace string = '10.0.2.0/24'

@description('Services subnet address space')
param servicesSubnetAddressSpace string = '10.0.3.0/24'

@description('Whether to create Azure Key Vault')
param createKeyVault bool = true

@description('Whether to create Azure Container Registry')
param createContainerRegistry bool = true

@description('AKS cluster name')
param aksClusterName string = '${resourcePrefix}-aks'

@description('PostgreSQL server name')
param postgresqlServerName string = '${resourcePrefix}-pgsql'

@description('OpenAI service name')
param openaiServiceName string = '${resourcePrefix}-aoai'

@description('Key Vault name')
param keyVaultName string = '${resourcePrefix}-akv'

@description('Container Registry name')
param containerRegistryName string = replace('${resourcePrefix}acr', '-', '')

@description('PostgreSQL administrator login')
@secure()
param postgresqlAdminLogin string

@description('PostgreSQL administrator password')
@secure()
param postgresqlAdminPassword string

// Variables
var tags = {
  Environment: environment
  Project: 'linux-first-docs-enforcer'
  ManagedBy: 'bicep'
}

// Virtual Network Module
module vnet 'modules/vnet.bicep' = {
  name: 'vnet-deployment'
  params: {
    location: location
    vnetName: '${resourcePrefix}-vnet'
    vnetAddressSpace: vnetAddressSpace
    aksSubnetAddressSpace: aksSubnetAddressSpace
    postgresqlSubnetAddressSpace: postgresqlSubnetAddressSpace
    servicesSubnetAddressSpace: servicesSubnetAddressSpace
    tags: tags
  }
}

// Monitoring Module (Deploy first as other services depend on it)
module monitoring 'modules/monitoring.bicep' = {
  name: 'monitoring-deployment'
  params: {
    location: location
    resourcePrefix: resourcePrefix
    environment: environment
    tags: tags
  }
}

// PostgreSQL Module
module postgresql 'modules/postgresql.bicep' = {
  name: 'postgresql-deployment'
  params: {
    location: location
    serverName: postgresqlServerName
    adminLogin: postgresqlAdminLogin
    adminPassword: postgresqlAdminPassword
    subnetId: vnet.outputs.postgresqlSubnetId
    privateDnsZoneId: vnet.outputs.postgresqlPrivateDnsZoneId
    tags: tags
  }
}

// OpenAI Module
module openai 'modules/openai.bicep' = {
  name: 'openai-deployment'
  params: {
    location: location
    serviceName: openaiServiceName
    subnetId: vnet.outputs.servicesSubnetId
    privateDnsZoneId: vnet.outputs.openaiPrivateDnsZoneId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    tags: tags
  }
}

// Key Vault Module (Optional)
module keyVault 'modules/keyvault.bicep' = if (createKeyVault) {
  name: 'keyvault-deployment'
  params: {
    location: location
    keyVaultName: keyVaultName
    subnetId: vnet.outputs.servicesSubnetId
    privateDnsZoneId: vnet.outputs.keyVaultPrivateDnsZoneId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    tags: tags
  }
}

// Container Registry Module (Optional)
module containerRegistry 'modules/acr.bicep' = if (createContainerRegistry) {
  name: 'acr-deployment'
  params: {
    location: location
    registryName: containerRegistryName
    subnetId: vnet.outputs.servicesSubnetId
    privateDnsZoneId: vnet.outputs.acrPrivateDnsZoneId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    tags: tags
  }
}

// AKS Module
module aks 'modules/aks.bicep' = {
  name: 'aks-deployment'
  params: {
    location: location
    clusterName: aksClusterName
    subnetId: vnet.outputs.aksSubnetId
    logAnalyticsWorkspaceId: monitoring.outputs.logAnalyticsWorkspaceId
    azureMonitorWorkspaceId: monitoring.outputs.azureMonitorWorkspaceId
    keyVaultId: createKeyVault ? keyVault!.outputs.keyVaultId : ''
    tags: tags
  }
}

// Role assignment for AKS identity to manage the subnet
resource aksNetworkContributorRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, aksClusterName, 'Network Contributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4d97b98b-1d4f-4787-a291-c67834d212e7') // Network Contributor
    principalId: aks.outputs.clusterIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for AKS identity to pull from ACR (if provided)
resource aksAcrPullRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (createContainerRegistry) {
  name: guid(resourceGroup().id, aksClusterName, containerRegistryName, 'AcrPull')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d') // AcrPull
    principalId: aks.outputs.clusterIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for AKS identity to access monitoring
resource aksMonitoringMetricsPublisherRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, aksClusterName, 'Monitoring Metrics Publisher')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '3913510d-42f4-4e42-8a64-420c390055eb') // Monitoring Metrics Publisher
    principalId: aks.outputs.clusterIdentityPrincipalId
    principalType: 'ServicePrincipal'
  }
}

// Security Module
module security 'modules/security.bicep' = {
  name: 'security-deployment'
  params: {
    location: location
    resourcePrefix: resourcePrefix
  }
}

// Service Connector Module (Role assignments for AKS managed identity)
module serviceConnector 'modules/serviceconnector.bicep' = {
  name: 'serviceconnector-deployment'
  params: {
    aksClusterId: aks.outputs.clusterId
    postgresqlServerId: postgresql.outputs.serverId
    openaiServiceId: openai.outputs.serviceId
    keyVaultId: createKeyVault ? keyVault!.outputs.keyVaultId : ''
  }
  dependsOn: [
    aksNetworkContributorRole
    aksMonitoringMetricsPublisherRole
  ]
}

// Outputs
@description('AKS cluster name')
output aksClusterName string = aks.outputs.clusterName

@description('AKS cluster resource ID')
output aksClusterId string = aks.outputs.clusterId

@description('AKS cluster FQDN')
output aksClusterFqdn string = aks.outputs.clusterFqdn

@description('PostgreSQL server name')
output postgresqlServerName string = postgresql.outputs.serverName

@description('PostgreSQL server FQDN')
output postgresqlServerFqdn string = postgresql.outputs.serverFqdn

@description('OpenAI service name')
output openaiServiceName string = openai.outputs.serviceName

@description('OpenAI service endpoint')
output openaiServiceEndpoint string = openai.outputs.serviceEndpoint

@description('Key Vault name')
output keyVaultName string = createKeyVault ? keyVault!.outputs.keyVaultName : ''

@description('Container Registry name')
output containerRegistryName string = createContainerRegistry ? containerRegistry!.outputs.registryName : ''

@description('Container Registry login server')
output containerRegistryLoginServer string = createContainerRegistry ? containerRegistry!.outputs.loginServer : ''

@description('Log Analytics workspace ID')
output logAnalyticsWorkspaceId string = monitoring.outputs.logAnalyticsWorkspaceId

@description('Azure Monitor workspace ID')
output azureMonitorWorkspaceId string = monitoring.outputs.azureMonitorWorkspaceId

@description('Managed Grafana endpoint')
output managedGrafanaEndpoint string = monitoring.outputs.managedGrafanaEndpoint