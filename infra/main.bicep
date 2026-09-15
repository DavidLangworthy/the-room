targetScope = 'resourceGroup'

@description('Azure region used for the resource group itself.')
param location string

@description('Azure region display name for the Static Web App resource.')
param staticWebAppLocation string = 'Central US'

@description('Short application name. Lowercase letters, numbers and hyphens only.')
param appName string = 'clock'

var appNamePrefix = take(toLower(appName), 32)
var uniqueSuffix = take(uniqueString(subscription().subscriptionId, resourceGroup().id, appNamePrefix), 6)
var staticWebAppName = '${appNamePrefix}-${uniqueSuffix}'

// A Static Web App with no linked backend and no functions: there is nowhere for a
// question, an answer or an API key to be sent, which is the product's whole claim.
resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticWebAppName
  location: staticWebAppLocation
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  tags: {
    app: appNamePrefix
    provisionedBy: 'clock-scripts'
    resourceGroupLocation: location
  }
  properties: {}
}

output staticWebAppName string = staticSite.name
output defaultHostname string = staticSite.properties.defaultHostname
output staticWebAppId string = staticSite.id
