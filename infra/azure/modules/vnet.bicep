// Parameters
@description('Location for all resources')
param location string

@description('Virtual network name')
param vnetName string

@description('Virtual network address space')
param vnetAddressSpace string

@description('AKS subnet address space')
param aksSubnetAddressSpace string

@description('PostgreSQL subnet address space')
param postgresqlSubnetAddressSpace string

@description('Services subnet address space')
param servicesSubnetAddressSpace string

@description('Resource tags')
param tags object

// Variables
var aksSubnetName = 'aks-subnet'
var postgresqlSubnetName = 'postgresql-subnet'
var servicesSubnetName = 'services-subnet'

// Network Security Groups
resource aksNsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${vnetName}-aks-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowAKSApiServer'
        properties: {
          description: 'Allow AKS API Server access'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: 'Internet'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
      {
        name: 'AllowLoadBalancer'
        properties: {
          description: 'Allow Azure Load Balancer'
          protocol: '*'
          sourcePortRange: '*'
          destinationPortRange: '*'
          sourceAddressPrefix: 'AzureLoadBalancer'
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1010
          direction: 'Inbound'
        }
      }
    ]
  }
}

resource postgresqlNsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${vnetName}-postgresql-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowPostgreSQLFromAKS'
        properties: {
          description: 'Allow PostgreSQL access from AKS subnet'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '5432'
          sourceAddressPrefix: aksSubnetAddressSpace
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
    ]
  }
}

resource servicesNsg 'Microsoft.Network/networkSecurityGroups@2023-11-01' = {
  name: '${vnetName}-services-nsg'
  location: location
  tags: tags
  properties: {
    securityRules: [
      {
        name: 'AllowHTTPSFromAKS'
        properties: {
          description: 'Allow HTTPS access from AKS subnet'
          protocol: 'Tcp'
          sourcePortRange: '*'
          destinationPortRange: '443'
          sourceAddressPrefix: aksSubnetAddressSpace
          destinationAddressPrefix: '*'
          access: 'Allow'
          priority: 1000
          direction: 'Inbound'
        }
      }
    ]
  }
}

// Virtual Network
resource vnet 'Microsoft.Network/virtualNetworks@2023-11-01' = {
  name: vnetName
  location: location
  tags: tags
  properties: {
    addressSpace: {
      addressPrefixes: [
        vnetAddressSpace
      ]
    }
    subnets: [
      {
        name: aksSubnetName
        properties: {
          addressPrefix: aksSubnetAddressSpace
          networkSecurityGroup: {
            id: aksNsg.id
          }
        }
      }
      {
        name: postgresqlSubnetName
        properties: {
          addressPrefix: postgresqlSubnetAddressSpace
          networkSecurityGroup: {
            id: postgresqlNsg.id
          }
          delegations: [
            {
              name: 'Microsoft.DBforPostgreSQL.flexibleServers'
              properties: {
                serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers'
              }
            }
          ]
        }
      }
      {
        name: servicesSubnetName
        properties: {
          addressPrefix: servicesSubnetAddressSpace
          networkSecurityGroup: {
            id: servicesNsg.id
          }
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
    ]
  }
}

// Private DNS Zones
resource postgresqlPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.postgres.database.azure.com'
  location: 'global'
  tags: tags
}

resource keyVaultPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.vaultcore.azure.net'
  location: 'global'
  tags: tags
}

resource openaiPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.openai.azure.com'
  location: 'global'
  tags: tags
}

resource acrPrivateDnsZone 'Microsoft.Network/privateDnsZones@2020-06-01' = {
  name: 'privatelink.azurecr.io'
  location: 'global'
  tags: tags
}

// Private DNS Zone Virtual Network Links
resource postgresqlPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: postgresqlPrivateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource keyVaultPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: keyVaultPrivateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource openaiPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: openaiPrivateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

resource acrPrivateDnsZoneVnetLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2020-06-01' = {
  parent: acrPrivateDnsZone
  name: '${vnetName}-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: {
      id: vnet.id
    }
  }
}

// Outputs
@description('Virtual network resource ID')
output vnetId string = vnet.id

@description('Virtual network name')
output vnetName string = vnet.name

@description('AKS subnet resource ID')
output aksSubnetId string = vnet.properties.subnets[0].id

@description('PostgreSQL subnet resource ID')
output postgresqlSubnetId string = vnet.properties.subnets[1].id

@description('Services subnet resource ID')
output servicesSubnetId string = vnet.properties.subnets[2].id

@description('PostgreSQL private DNS zone resource ID')
output postgresqlPrivateDnsZoneId string = postgresqlPrivateDnsZone.id

@description('Key Vault private DNS zone resource ID')
output keyVaultPrivateDnsZoneId string = keyVaultPrivateDnsZone.id

@description('OpenAI private DNS zone resource ID')
output openaiPrivateDnsZoneId string = openaiPrivateDnsZone.id

@description('ACR private DNS zone resource ID')
output acrPrivateDnsZoneId string = acrPrivateDnsZone.id