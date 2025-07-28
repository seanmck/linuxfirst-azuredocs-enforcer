// Parameters
@description('Location for all resources')
param location string

@description('Resource prefix for naming')
param resourcePrefix string

// Security Policies
resource securityPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-security-policy'
  location: location
  properties: {
    displayName: 'Azure Security Benchmark'
    policyDefinitionId: '/providers/Microsoft.Authorization/policySetDefinitions/1f3afdf9-d0c9-4c3d-847f-89da613e70a8'
    parameters: {}
    enforcementMode: 'DoNotEnforce' // Start with audit mode
  }
  identity: {
    type: 'SystemAssigned'
  }
}

// Kubernetes Security Policy for AKS
resource aksSecurityPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-aks-security'
  location: location
  properties: {
    displayName: 'Kubernetes cluster should not allow privileged containers'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/95edb821-ddaf-4404-9732-666045e056b4'
    parameters: {
      effect: {
        value: 'Audit' // Start with audit, can change to Deny later
      }
    }
  }
}

// Pod Security Standards Policy for AKS
// NOTE: This policy requires managed identity even when Disabled
// TODO: Enable this after deployment with proper managed identity configuration
/*
resource podSecurityPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-pod-security'
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    displayName: 'Kubernetes clusters should use Pod Security Standards'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/a8eff44f-8c92-45c3-a3fb-9880802d67a7'
    parameters: {
      effect: {
        value: 'DeployIfNotExists'
      }
      excludedNamespaces: {
        value: [
          'kube-system'
          'gatekeeper-system'
          'azure-arc'
          'cluster-baseline-setting'
        ]
      }
    }
  }
}
*/

// Network Security Policy - Commented out as the policy definition ID is invalid
// TODO: Find correct policy definition for network security
/*
resource networkSecurityPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-network-security'
  location: location
  properties: {
    displayName: 'Network Security Group should not allow unrestricted access'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/e1145ab1-eb4f-42e6-9934-00c741db2ac2'
    parameters: {
      effect: {
        value: 'Audit'
      }
    }
  }
}
*/

// Data Protection Policy
resource dataProtectionPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-data-protection'
  location: location
  properties: {
    displayName: 'Storage accounts should restrict network access'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/34c877ad-507e-4c82-993e-3452a6e0ad3c'
    parameters: {
      effect: {
        value: 'Audit'
      }
    }
  }
}

// Monitoring and Logging Policy
resource loggingPolicy 'Microsoft.Authorization/policyAssignments@2024-05-01' = {
  name: '${resourcePrefix}-logging-policy'
  location: location
  properties: {
    displayName: 'Diagnostic logs should be enabled'
    policyDefinitionId: '/providers/Microsoft.Authorization/policyDefinitions/7f89b1eb-583c-429a-8828-af049802c1d9'
    parameters: {
      listOfResourceTypes: {
        value: [
          'Microsoft.ContainerService/managedClusters'
          'Microsoft.DBforPostgreSQL/flexibleServers'
          'Microsoft.KeyVault/vaults'
          'Microsoft.ContainerRegistry/registries'
          'Microsoft.CognitiveServices/accounts'
        ]
      }
    }
  }
}

// Outputs
@description('Security policy assignment ID')
output securityPolicyId string = securityPolicy.id

// @description('AKS security policy assignment ID')
// output aksSecurityPolicyId string = aksSecurityPolicy.id // Commented out with podSecurityPolicy
@description('AKS security policy assignment ID')
output aksSecurityPolicyId string = 'Not deployed - requires manual configuration'