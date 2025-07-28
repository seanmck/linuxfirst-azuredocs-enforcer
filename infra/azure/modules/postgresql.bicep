// Parameters
@description('Location for all resources')
param location string

@description('PostgreSQL server name')
param serverName string

@description('Administrator login')
@secure()
param adminLogin string

@description('Administrator password')
@secure()
param adminPassword string

@description('PostgreSQL subnet resource ID')
param subnetId string

@description('PostgreSQL private DNS zone resource ID')
param privateDnsZoneId string

@description('Resource tags')
param tags object

@description('PostgreSQL version')
param postgresqlVersion string = '15'

@description('SKU name')
param skuName string = 'Standard_B2s'

@description('SKU tier')
param skuTier string = 'Burstable'

@description('Storage size in GB')
param storageSizeGB int = 32

@description('Backup retention days')
param backupRetentionDays int = 7

@description('Enable geo-redundant backup')
param geoRedundantBackup bool = false

// Variables
var databaseName = 'linuxdocsdb'

// PostgreSQL Flexible Server
resource postgresqlServer 'Microsoft.DBforPostgreSQL/flexibleServers@2023-06-01-preview' = {
  name: serverName
  location: location
  tags: tags
  sku: {
    name: skuName
    tier: skuTier
  }
  properties: {
    version: postgresqlVersion
    administratorLogin: adminLogin
    administratorLoginPassword: adminPassword
    
    // Network configuration
    network: {
      delegatedSubnetResourceId: subnetId
      privateDnsZoneArmResourceId: privateDnsZoneId
      publicNetworkAccess: 'Disabled'
    }

    // Storage configuration
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Enabled'
    }

    // Backup configuration
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }

    // High availability (disabled for burstable tier)
    highAvailability: {
      mode: 'Disabled'
    }

    // Maintenance window
    maintenanceWindow: {
      customWindow: 'Enabled'
      dayOfWeek: 0  // Sunday
      startHour: 2
      startMinute: 0
    }

    // Authentication configuration
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Enabled'
      tenantId: subscription().tenantId
    }
  }
}

// Database
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2023-06-01-preview' = {
  parent: postgresqlServer
  name: databaseName
  properties: {
    charset: 'utf8'
    collation: 'en_US.utf8'
  }
}

// PostgreSQL configuration parameters
// NOTE: These configurations may fail if server is busy during deployment
// You may need to apply these configurations after deployment completes
/*
resource postgresqlConfig 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2023-06-01-preview' = [
  for config in [
    {
      name: 'shared_preload_libraries'
      value: 'pg_stat_statements'
    }
    {
      name: 'pg_stat_statements.track'
      value: 'all'
    }
    {
      name: 'log_statement'
      value: 'all'
    }
    {
      name: 'log_min_duration_statement'
      value: '1000'
    }
  ]: {
    parent: postgresqlServer
    name: config.name
    properties: {
      value: config.value
      source: 'user-override'
    }
  }
]
*/

// Firewall rules (none needed as we're using private endpoint)
// But keeping for future reference if needed
/*
resource firewallRule 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2023-06-01-preview' = {
  parent: postgresqlServer
  name: 'AllowVNet'
  properties: {
    startIpAddress: '10.0.0.0'
    endIpAddress: '10.0.255.255'
  }
}
*/

// Outputs
@description('PostgreSQL server resource ID')
output serverId string = postgresqlServer.id

@description('PostgreSQL server name')
output serverName string = postgresqlServer.name

@description('PostgreSQL server FQDN')
output serverFqdn string = postgresqlServer.properties.fullyQualifiedDomainName

@description('Database name')
output databaseName string = database.name

@description('Connection string template (without credentials)')
output connectionStringTemplate string = 'Server=${postgresqlServer.properties.fullyQualifiedDomainName};Database=${database.name};Port=5432;User Id=<admin-login>;Password=<admin-password>;Ssl Mode=Require;'