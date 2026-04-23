// Copyright 2026, Microsoft
// Licensed under the Apache License, Version 2.0.
//
// Azure infrastructure entrypoint for the OSDU SPI Stack.
//
// Provisions all Azure PaaS resources required by OSDU services:
// Managed Identity + federated credentials, Key Vault, ACR, CosmosDB
// (Gremlin for entitlements + SQL per partition), Service Bus per
// partition, common and per-partition Storage, and the scoped RBAC
// role assignments that bind the identity to the above.
//
// Key Vault secret VALUES are also declared here: static metadata plus
// ``listKeys()`` on Cosmos accounts is resolved at deploy time, so the CLI
// no longer has to run ``az cosmosdb keys list`` + ``az keyvault secret set``
// post-deploy.
//
// Not in scope of this template:
//   - AKS Automatic cluster + managed Istio -- declared separately in
//     infra/aks.bicep (deployed first; this template consumes its
//     oidcIssuerUrl output for federated-credential wiring).
//   - Resource Group creation (pre-created by `az group create`)
//   - Soft-deleted Key Vault recovery (CLI pre-check)
//   - Flux extension + GitOps config -- infra/flux.bicep, deployed after
//     the K8s bootstrap phase.
//   - Runtime-only secrets that depend on in-cluster seed passwords
//     (tbl-storage-endpoint, redis-*, {partition}-elastic-*) -- written
//     by the CLI in the post-handoff bootstrap.
//   - Istio CNI chaining + kubectl bootstrap (Python provider).
//
// Naming contract: the CLI pre-derives every Azure resource name in
// src/spi/config.py and src/spi/azure_infra.py and passes them as
// parameters. This template does not re-derive names.

targetScope = 'resourceGroup'

// ──────────────────────────────────────────────────────────
// Parameters
// ──────────────────────────────────────────────────────────

// envName is passed by the CLI for readability of deployment history.
@description('Environment suffix, e.g. "dev1". Empty string for base environment.')
#disable-next-line no-unused-params
param envName string = ''

@description('Azure region for all resources.')
param location string = 'eastus2'

@description('User-assigned managed identity name.')
param identityName string

@description('Key Vault name.')
param keyVaultName string

@description('Azure Container Registry name.')
param acrName string

@description('Data partition names.')
param dataPartitions array = [
  'opendes'
]

@description('Primary data partition (first of dataPartitions, hosts the system DB).')
param primaryPartition string

@description('CosmosDB Gremlin account name (for Entitlements graph).')
param gremlinAccountName string

@description('Common storage account name (shared across partitions).')
param commonStorageName string

@description('Per-partition Cosmos SQL account names. Must align by index with dataPartitions.')
param cosmosSqlNames array

@description('Per-partition Service Bus namespace names. Must align by index with dataPartitions.')
param serviceBusNames array

@description('Per-partition storage account names. Must align by index with dataPartitions.')
param partitionStorageNames array

@description('OIDC issuer URL from the AKS cluster. Empty string skips federated credential creation.')
param oidcIssuerUrl string = ''

// ──────────────────────────────────────────────────────────
// Modules (shared resources, parallel)
// ──────────────────────────────────────────────────────────

module keyvaultModule 'modules/keyvault.bicep' = {
  name: 'spi-keyvault'
  params: {
    name: keyVaultName
    location: location
  }
}

module acrModule 'modules/acr.bicep' = {
  name: 'spi-acr'
  params: {
    name: acrName
    location: location
  }
}

module identityModule 'modules/identity.bicep' = {
  name: 'spi-identity'
  params: {
    name: identityName
    location: location
    oidcIssuerUrl: oidcIssuerUrl
  }
}

module gremlinModule 'modules/cosmos-gremlin.bicep' = {
  name: 'spi-gremlin'
  params: {
    name: gremlinAccountName
    location: location
    keyVaultName: keyVaultName
  }
  dependsOn: [
    keyvaultModule
  ]
}

module storageCommonModule 'modules/storage-common.bicep' = {
  name: 'spi-storage-common'
  params: {
    name: commonStorageName
    location: location
  }
}

// ──────────────────────────────────────────────────────────
// Modules (per-partition, parallel across partitions)
// ──────────────────────────────────────────────────────────

module partitionModules 'modules/partition.bicep' = [for (p, i) in dataPartitions: {
  name: 'spi-partition-${p}'
  params: {
    partition: p
    location: location
    cosmosSqlName: cosmosSqlNames[i]
    serviceBusName: serviceBusNames[i]
    storageAccountName: partitionStorageNames[i]
    isPrimaryPartition: p == primaryPartition
    keyVaultName: keyVaultName
  }
  dependsOn: [
    keyvaultModule
  ]
}]

// ──────────────────────────────────────────────────────────
// RBAC (runs after all resources above)
// ──────────────────────────────────────────────────────────

module rbacModule 'modules/rbac.bicep' = {
  name: 'spi-rbac'
  params: {
    principalId: identityModule.outputs.principalId
    keyVaultName: keyVaultName
    acrName: acrName
    commonStorageName: commonStorageName
    partitionStorageNames: partitionStorageNames
    serviceBusNames: serviceBusNames
  }
  dependsOn: [
    keyvaultModule
    acrModule
    storageCommonModule
    partitionModules
  ]
}

// ──────────────────────────────────────────────────────────
// Key Vault secret values (declarative; replaces post-deploy CLI writes)
// ──────────────────────────────────────────────────────────
//
// ``existing`` references let us call ``listKeys()`` on Cosmos accounts
// provisioned inside sub-modules and write the result directly as a KV
// secret. Splitting the declarations by "pattern" (static vs per-partition
// cosmos/storage/sb) keeps Bicep's array-loop semantics simple and makes
// the deployment history self-describing without a ``flatten()`` dance.
//
// All secret values stay out of the deployment outputs -- they are set
// only on the child resource and never surface in the deployment record.

// Cosmos primary-key secrets (graph-db-primary-key and
// {partition}-cosmos-primary-key) are written INSIDE the gremlinModule
// and partitionModules respectively. ``listKeys()`` on an ``existing``
// reference at this scope fails with ResourceNotFound because Bicep's
// dependency analyzer does not chain through the module that creates
// the account.

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

// Static/metadata secrets are declared individually because Bicep's for-
// expression cannot iterate over an array that references module outputs
// (BCP178: iterable must be resolvable at deployment start). Per-partition
// loops below iterate over ``dataPartitions`` (a parameter) which is fine.

resource secretTenantId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'tenant-id'
  parent: keyVault
  properties: { value: tenant().tenantId }
  dependsOn: [ keyvaultModule ]
}

resource secretSubscriptionId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'subscription-id'
  parent: keyVault
  properties: { value: subscription().subscriptionId }
  dependsOn: [ keyvaultModule ]
}

resource secretIdentityId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'osdu-identity-id'
  parent: keyVault
  properties: { value: identityModule.outputs.clientId }
  dependsOn: [ keyvaultModule ]
}

resource secretKeyvaultUri 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'keyvault-uri'
  parent: keyVault
  properties: { value: keyvaultModule.outputs.uri }
}

resource secretSystemStorage 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'system-storage'
  parent: keyVault
  properties: { value: commonStorageName }
  dependsOn: [ keyvaultModule ]
}

resource secretAppDevSpUsername 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'app-dev-sp-username'
  parent: keyVault
  properties: { value: identityModule.outputs.clientId }
  dependsOn: [ keyvaultModule ]
}

resource secretAppDevSpPassword 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'app-dev-sp-password'
  parent: keyVault
  properties: { value: 'DISABLED' }
  dependsOn: [ keyvaultModule ]
}

resource secretAppDevSpTenantId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'app-dev-sp-tenant-id'
  parent: keyVault
  properties: { value: tenant().tenantId }
  dependsOn: [ keyvaultModule ]
}

resource secretAppDevSpId 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'app-dev-sp-id'
  parent: keyVault
  properties: { value: identityModule.outputs.clientId }
  dependsOn: [ keyvaultModule ]
}

resource secretGraphEndpoint 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  name: 'graph-db-endpoint'
  parent: keyVault
  properties: { value: gremlinModule.outputs.documentEndpoint }
  dependsOn: [ keyvaultModule ]
}

// graph-db-primary-key is written inside gremlinModule; see note above.

resource partitionStorageSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [for (p, i) in dataPartitions: {
  name: '${p}-storage'
  parent: keyVault
  properties: {
    value: partitionStorageNames[i]
  }
  dependsOn: [
    keyvaultModule
  ]
}]

resource partitionCosmosEndpointSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [for (p, i) in dataPartitions: {
  name: '${p}-cosmos-endpoint'
  parent: keyVault
  properties: {
    value: partitionModules[i].outputs.cosmosEndpoint
  }
  dependsOn: [
    keyvaultModule
  ]
}]

// {partition}-cosmos-primary-key is written inside each partitionModule.

resource partitionServiceBusSecrets 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = [for (p, i) in dataPartitions: {
  name: '${p}-sb-namespace'
  parent: keyVault
  properties: {
    value: serviceBusNames[i]
  }
  dependsOn: [
    keyvaultModule
  ]
}]

// ──────────────────────────────────────────────────────────
// Outputs
// ──────────────────────────────────────────────────────────
//
// Outputs are in camelCase and flat; the CLI reshapes them into the
// legacy snake_case infra_outputs dict consumed by _create_osdu_config
// and workload-identity ServiceAccount creation. Secret values are
// NEVER emitted as outputs; they stay inside the KV secret resources.

output tenantId string = tenant().tenantId
output subscriptionId string = subscription().subscriptionId
output resourceGroupName string = resourceGroup().name

output identityClientId string = identityModule.outputs.clientId
output identityPrincipalId string = identityModule.outputs.principalId
output identityResourceId string = identityModule.outputs.resourceId

output keyvaultUri string = keyvaultModule.outputs.uri
output keyvaultId string = keyvaultModule.outputs.resourceId

output acrId string = acrModule.outputs.resourceId
output acrLoginServer string = acrModule.outputs.loginServer

output graphEndpoint string = gremlinModule.outputs.documentEndpoint
output graphAccountId string = gremlinModule.outputs.resourceId

output commonStorageName string = commonStorageName
output commonStorageId string = storageCommonModule.outputs.resourceId

// Per-partition arrays, indexed by dataPartitions order. The CLI zips
// these with dataPartitions to build the per-partition keys in
// infra_outputs (e.g., "{partition}_cosmos_endpoint").
output partitionNames array = dataPartitions
output partitionCosmosEndpoints array = [for i in range(0, length(dataPartitions)): partitionModules[i].outputs.cosmosEndpoint]
output partitionCosmosAccountIds array = [for i in range(0, length(dataPartitions)): partitionModules[i].outputs.cosmosAccountId]
output partitionServiceBusIds array = [for i in range(0, length(dataPartitions)): partitionModules[i].outputs.serviceBusId]
output partitionServiceBusNames array = serviceBusNames
output partitionStorageIds array = [for i in range(0, length(dataPartitions)): partitionModules[i].outputs.storageId]
output partitionStorageNamesOut array = partitionStorageNames
