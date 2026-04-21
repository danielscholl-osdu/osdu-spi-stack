// Azure Container Registry, Basic SKU.

@description('Container Registry name (globally unique, 5-50 alphanumeric).')
param name string

@description('Azure region.')
param location string

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: {
    name: 'Basic'
  }
  properties: {
    adminUserEnabled: false
  }
}

output resourceId string = acr.id
output loginServer string = acr.properties.loginServer
