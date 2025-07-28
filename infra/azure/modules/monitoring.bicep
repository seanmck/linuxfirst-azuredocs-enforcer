// Parameters
@description('Location for all resources')
param location string

@description('Resource prefix for naming')
param resourcePrefix string

@description('Environment name')
param environment string

@description('Resource tags')
param tags object

// Variables
var logAnalyticsWorkspaceName = '${resourcePrefix}-logs-${environment}'
var azureMonitorWorkspaceName = '${resourcePrefix}-monitor-${environment}'
// Shorten the grafana name to stay under 23 character limit (not 30!)
var managedGrafanaName = environment == 'production' ? '${resourcePrefix}-graf' : '${resourcePrefix}-graf-${toLower(substring(environment, 0, min(length(environment), 3)))}'
var applicationInsightsName = '${resourcePrefix}-appinsights-${environment}'

// Log Analytics Workspace (for logs and basic monitoring)
resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: tags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    features: {
      enableLogAccessUsingOnlyResourcePermissions: true
    }
    workspaceCapping: {
      dailyQuotaGb: 10
    }
  }
}

// Azure Monitor Workspace (for Prometheus metrics)
resource azureMonitorWorkspace 'Microsoft.Monitor/accounts@2023-04-03' = {
  name: azureMonitorWorkspaceName
  location: location
  tags: tags
  properties: {}
}

// Application Insights
resource applicationInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: applicationInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalyticsWorkspace.id
    IngestionMode: 'LogAnalytics'
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

// Azure Managed Grafana
resource managedGrafana 'Microsoft.Dashboard/grafana@2023-09-01' = {
  name: managedGrafanaName
  location: location
  tags: tags
  sku: {
    name: 'Standard'
  }
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    zoneRedundancy: 'Disabled'
    publicNetworkAccess: 'Enabled'
    grafanaIntegrations: {
      azureMonitorWorkspaceIntegrations: [
        {
          azureMonitorWorkspaceResourceId: azureMonitorWorkspace.id
        }
      ]
    }
  }
}

// Role assignment for Grafana to read from Azure Monitor Workspace
resource grafanaMonitoringReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(azureMonitorWorkspace.id, managedGrafana.id, 'Monitoring Reader')
  scope: azureMonitorWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '43d0d8ad-25c7-4714-9337-8ba259a9fe05') // Monitoring Reader
    principalId: managedGrafana.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Role assignment for Grafana to read from Log Analytics
resource grafanaLogAnalyticsReaderRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(logAnalyticsWorkspace.id, managedGrafana.id, 'Log Analytics Reader')
  scope: logAnalyticsWorkspace
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '73c42c96-874c-492b-b04d-ab87d138a893') // Log Analytics Reader
    principalId: managedGrafana.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Alert Action Group
resource actionGroup 'Microsoft.Insights/actionGroups@2023-01-01' = {
  name: '${resourcePrefix}-alerts-${environment}'
  location: 'global'
  tags: tags
  properties: {
    groupShortName: 'alerts'
    enabled: true
    emailReceivers: []
    smsReceivers: []
    webhookReceivers: []
    armRoleReceivers: []
    azureFunctionReceivers: []
    logicAppReceivers: []
  }
}

// Basic metric alerts for AKS monitoring
// NOTE: AKS-specific alerts should be created after AKS deployment
// since they require the AKS cluster resource ID in the scope
// TODO: Move these alerts to main.bicep or a separate alerts module
/*
resource aksNodeMemoryAlert 'Microsoft.Insights/metricAlerts@2018-03-01' = {
  name: '${resourcePrefix}-aks-node-memory-alert'
  location: 'global'
  tags: tags
  properties: {
    description: 'Alert when AKS node memory usage is high'
    severity: 2
    enabled: true
    scopes: [] // This needs AKS cluster ID which is not available here
    evaluationFrequency: 'PT5M'
    windowSize: 'PT5M'
    criteria: {
      'odata.type': 'Microsoft.Azure.Monitor.MultipleResourceMultipleMetricCriteria'
      allOf: [
        {
          name: 'NodeMemoryUsage'
          metricName: 'node_memory_working_set_bytes'
          operator: 'GreaterThan'
          threshold: 85
          timeAggregation: 'Average'
          criterionType: 'StaticThresholdCriterion'
        }
      ]
    }
    actions: [
      {
        actionGroupId: actionGroup.id
      }
    ]
  }
}
*/

// Outputs
@description('Log Analytics workspace resource ID')
output logAnalyticsWorkspaceId string = logAnalyticsWorkspace.id

@description('Log Analytics workspace name')
output logAnalyticsWorkspaceName string = logAnalyticsWorkspace.name

@description('Azure Monitor workspace resource ID')
output azureMonitorWorkspaceId string = azureMonitorWorkspace.id

@description('Azure Monitor workspace name')
output azureMonitorWorkspaceName string = azureMonitorWorkspace.name

@description('Managed Grafana resource ID')
output managedGrafanaId string = managedGrafana.id

@description('Managed Grafana name')
output managedGrafanaName string = managedGrafana.name

@description('Managed Grafana endpoint')
output managedGrafanaEndpoint string = managedGrafana.properties.endpoint

@description('Application Insights resource ID')
output applicationInsightsId string = applicationInsights.id

@description('Application Insights name')
output applicationInsightsName string = applicationInsights.name

@description('Application Insights instrumentation key')
output applicationInsightsInstrumentationKey string = applicationInsights.properties.InstrumentationKey

@description('Application Insights connection string')
output applicationInsightsConnectionString string = applicationInsights.properties.ConnectionString

@description('Action group resource ID')
output actionGroupId string = actionGroup.id