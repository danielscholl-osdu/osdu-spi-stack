// RBAC role assignments for the OSDU workload identity. Scoped per
// resource so principals get only what they need. Uses deterministic
// guid() names so a re-deploy updates the assignment rather than
// creating duplicates.

@description('Principal ID (object ID) of the managed identity.')
param principalId string

@description('Key Vault name (existing, created by keyvault.bicep).')
param keyVaultName string

@description('ACR name (existing, created by acr.bicep).')
param acrName string

@description('Common storage account name (existing).')
param commonStorageName string

@description('Per-partition storage account names (existing).')
param partitionStorageNames array

@description('Per-partition Service Bus namespace names (existing).')
param serviceBusNames array

// Well-known Azure built-in role definition IDs
var roleIds = {
  keyVaultSecretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  storageTableDataContributor: '0a9a7e1f-b9d0-4cc4-a60d-0319b160aaa3'
  serviceBusDataSender: '69a216fc-b8fb-44d8-bc22-1f3c2cd27a39'
  serviceBusDataReceiver: '4f6d3b9b-027b-4f4c-9142-0e5a2a2247e0'
  acrPull: '7f951dda-4ed3-4680-a7ca-43fe172d538d'
}

// ──────────────────────────────────────────────────────────
// Existing resource references (these are created by sibling modules
// during the same deployment; a top-level dependsOn in main.bicep
// ensures this module runs after them).
// ──────────────────────────────────────────────────────────

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource commonStorage 'Microsoft.Storage/storageAccounts@2023-01-01' existing = {
  name: commonStorageName
}

resource partitionStorageAccounts 'Microsoft.Storage/storageAccounts@2023-01-01' existing = [for storageName in partitionStorageNames: {
  name: storageName
}]

resource serviceBusNamespaces 'Microsoft.ServiceBus/namespaces@2022-10-01-preview' existing = [for sbName in serviceBusNames: {
  name: sbName
}]

// ──────────────────────────────────────────────────────────
// Shared resource assignments
// ──────────────────────────────────────────────────────────

resource keyVaultSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: keyVault
  name: guid(keyVault.id, principalId, roleIds.keyVaultSecretsUser)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.keyVaultSecretsUser)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: acr
  name: guid(acr.id, principalId, roleIds.acrPull)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.acrPull)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource commonStorageBlobAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: commonStorage
  name: guid(commonStorage.id, principalId, roleIds.storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

resource commonStorageTableAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: commonStorage
  name: guid(commonStorage.id, principalId, roleIds.storageTableDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageTableDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

// ──────────────────────────────────────────────────────────
// Per-partition assignments
// ──────────────────────────────────────────────────────────

resource partitionStorageBlobAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (storageName, i) in partitionStorageNames: {
  scope: partitionStorageAccounts[i]
  name: guid(partitionStorageAccounts[i].id, principalId, roleIds.storageBlobDataContributor)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.storageBlobDataContributor)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource serviceBusSenderAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (sbName, i) in serviceBusNames: {
  scope: serviceBusNamespaces[i]
  name: guid(serviceBusNamespaces[i].id, principalId, roleIds.serviceBusDataSender)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.serviceBusDataSender)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]

resource serviceBusReceiverAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for (sbName, i) in serviceBusNames: {
  scope: serviceBusNamespaces[i]
  name: guid(serviceBusNamespaces[i].id, principalId, roleIds.serviceBusDataReceiver)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleIds.serviceBusDataReceiver)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}]
