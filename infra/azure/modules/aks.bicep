// Parameters
@description('Location for all resources')
param location string

@description('AKS cluster name')
param clusterName string

@description('AKS subnet resource ID')
param subnetId string

@description('Log Analytics workspace resource ID')
param logAnalyticsWorkspaceId string

@description('Azure Monitor workspace resource ID')
param azureMonitorWorkspaceId string

@description('Key Vault resource ID (optional)')
param keyVaultId string = ''

@description('Resource tags')
param tags object

@description('Kubernetes version')
param kubernetesVersion string = '1.30'

@description('Node pool VM size')
param nodeVmSize string = 'Standard_D2s_v3'

@description('Initial node count')
param initialNodeCount int = 2

@description('Minimum node count for autoscaling')
param minNodeCount int = 1

@description('Maximum node count for autoscaling')
param maxNodeCount int = 10

// Variables
var dnsPrefix = '${clusterName}-dns'

// User Assigned Managed Identity for AKS
resource aksIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${clusterName}-identity'
  location: location
  tags: tags
}

// Role assignments moved to main.bicep to avoid circular dependencies

// AKS Cluster
resource aksCluster 'Microsoft.ContainerService/managedClusters@2024-02-01' = {
  name: clusterName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${aksIdentity.id}': {}
    }
  }
  properties: {
    kubernetesVersion: kubernetesVersion
    dnsPrefix: dnsPrefix
    enableRBAC: true
    
    // Node pool configuration with auto-provisioning
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        vmSize: nodeVmSize
        count: initialNodeCount
        minCount: minNodeCount
        maxCount: maxNodeCount
        enableAutoScaling: true
        enableNodePublicIP: false
        vnetSubnetID: subnetId
        type: 'VirtualMachineScaleSets'
        osType: 'Linux'
        osSKU: 'Ubuntu'
        nodeTaints: [
          'CriticalAddonsOnly=true:NoSchedule'
        ]
      }
      {
        name: 'user'
        mode: 'User'
        vmSize: nodeVmSize
        count: initialNodeCount
        minCount: minNodeCount
        maxCount: maxNodeCount
        enableAutoScaling: true
        enableNodePublicIP: false
        vnetSubnetID: subnetId
        type: 'VirtualMachineScaleSets'
        osType: 'Linux'
        osSKU: 'Ubuntu'
      }
    ]

    // Network configuration
    networkProfile: {
      networkPlugin: 'azure'
      networkPolicy: 'azure'
      serviceCidr: '10.10.0.0/16'
      dnsServiceIP: '10.10.0.10'
      loadBalancerSku: 'Standard'
      outboundType: 'loadBalancer'
    }

    // API server configuration
    apiServerAccessProfile: {
      enablePrivateCluster: false
      enablePrivateClusterPublicFQDN: true
    }

    // Auto-upgrade configuration
    autoUpgradeProfile: {
      upgradeChannel: 'stable'
      nodeOSUpgradeChannel: 'NodeImage'
    }

    // Workload identity
    oidcIssuerProfile: {
      enabled: true
    }
    securityProfile: {
      workloadIdentity: {
        enabled: true
      }
      defender: {
        logAnalyticsWorkspaceResourceId: logAnalyticsWorkspaceId
        securityMonitoring: {
          enabled: true
        }
      }
    }

    // Workload autoscaler configuration (KEDA)
    workloadAutoScalerProfile: {
      keda: {
        enabled: true
      }
    }

    // Azure Monitor metrics configuration
    azureMonitorProfile: {
      metrics: {
        enabled: true
        kubeStateMetrics: {
          metricLabelsAllowlist: ''
          metricAnnotationsAllowList: ''
        }
      }
    }

    // Add-ons configuration
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: keyVaultId != ''
        config: keyVaultId != '' ? {
          enableSecretRotation: 'true'
          rotationPollInterval: '2m'
        } : null
      }
      // HTTP Application Routing is deprecated and webAppRouting is not recognized
      // TODO: Enable application routing after deployment if needed
      azurepolicy: {
        enabled: true
      }
      ingressApplicationGateway: {
        enabled: false
      }
      omsAgent: {
        enabled: true
        config: {
          logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId
        }
      }
    }

    // Service mesh (optional)
    serviceMeshProfile: null

    // Node provisioning
    nodeResourceGroup: '${clusterName}-nodes-rg'
  }

  // Dependencies removed - role assignments moved to main.bicep
}

// KEDA is now configured in the workloadAutoScalerProfile section

// Prometheus metrics are configured via azureMonitorProfile in the cluster properties
// The extension approach is no longer used for Azure Monitor metrics

// Flux (GitOps) extension
resource fluxExtension 'Microsoft.KubernetesConfiguration/extensions@2023-05-01' = {
  name: 'flux'
  scope: aksCluster
  properties: {
    extensionType: 'microsoft.flux'
    autoUpgradeMinorVersion: true
    releaseTrain: 'Stable'
  }
}

// Outputs
@description('AKS cluster resource ID')
output clusterId string = aksCluster.id

@description('AKS cluster name')
output clusterName string = aksCluster.name

@description('AKS cluster FQDN')
output clusterFqdn string = aksCluster.properties.fqdn

@description('AKS cluster identity resource ID')
output clusterIdentityId string = aksIdentity.id

@description('AKS cluster identity principal ID')
output clusterIdentityPrincipalId string = aksIdentity.properties.principalId

@description('AKS cluster OIDC issuer URL')
output oidcIssuerUrl string = aksCluster.properties.oidcIssuerProfile.issuerURL

@description('AKS cluster node resource group')
output nodeResourceGroup string = aksCluster.properties.nodeResourceGroup