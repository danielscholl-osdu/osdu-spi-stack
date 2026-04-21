// Key Vault with RBAC authorization. Soft-delete recovery is handled
// by the CLI pre-check before this template runs; no recovery logic here.

@description('Key Vault name (globally unique, 3-24 alphanumeric).')
param name string

@description('Azure region.')
param location string

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  properties: {
    sku: {
      family: 'A'
      name: 'standard'
    }
    tenantId: tenant().tenantId
    enableRbacAuthorization: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    enabledForDeployment: false
    enabledForDiskEncryption: false
    enabledForTemplateDeployment: false
    publicNetworkAccess: 'Enabled'
  }
}

output resourceId string = keyVault.id
output uri string = keyVault.properties.vaultUri
