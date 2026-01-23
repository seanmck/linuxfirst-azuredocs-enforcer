// Parameters
@description('AKS cluster resource ID')
param aksClusterId string

@description('PostgreSQL server resource ID')
param postgresqlServerId string

@description('OpenAI service resource ID')
param openaiServiceId string

@description('Key Vault resource ID (optional)')
param keyVaultId string = ''

// Variables
var aksClusterName = last(split(aksClusterId, '/'))

// Get existing AKS cluster to access its identity
resource aksCluster 'Microsoft.ContainerService/managedClusters@2024-02-01' existing = {
  name: aksClusterName
}

// Role assignment for AKS to access PostgreSQL
resource postgresqlRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(postgresqlServerId, aksClusterId, 'PostgreSQL Flexible Server Contributor')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '9b7fa17d-e63e-47b0-bb0a-1f3a24f1e82e') // Azure Database for PostgreSQL Flexible Server Contributor
    principalId: aksCluster.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for AKS to access OpenAI
resource openaiRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(openaiServiceId, aksClusterId, 'Cognitive Services OpenAI User')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd') // Cognitive Services OpenAI User
    principalId: aksCluster.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for AKS to access Key Vault (if provided)
resource keyVaultRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (keyVaultId != '') {
  name: guid(keyVaultId, aksClusterId, 'Key Vault Secrets User')
  scope: resourceGroup()
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '4633458b-17de-408a-b874-0445c86b69e6') // Key Vault Secrets User
    principalId: aksCluster.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

// Note: ACR access is already configured in the AKS module via AcrPull role

// Outputs
@description('PostgreSQL role assignment ID')
output postgresqlRoleAssignmentId string = postgresqlRoleAssignment.id

@description('OpenAI role assignment ID')
output openaiRoleAssignmentId string = openaiRoleAssignment.id

@description('Key Vault role assignment ID')
output keyVaultRoleAssignmentId string = keyVaultId != '' ? keyVaultRoleAssignment.id : ''