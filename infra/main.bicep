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
// Not in scope of this template (handled imperatively by the CLI):
//   - Resource Group creation (pre-created by `az group create`)
//   - AKS Automatic cluster + managed Istio (Phase 5, still in Python)
//   - Soft-deleted Key Vault recovery (CLI pre-check)
//   - Key Vault secret VALUES (data-plane, written by CLI post-deploy)
//   - kubectl / flux bootstrap (Python provider)
//
// Naming contract: the CLI pre-derives every Azure resource name in
// src/spi/config.py and src/spi/azure_infra.py and passes them as
// parameters. This template does not re-derive names.

targetScope = 'resourceGroup'

// ──────────────────────────────────────────────────────────
// Parameters
// ──────────────────────────────────────────────────────────

// envName is passed by the CLI for readability of deployment history and
// to be available when Phase 5 adds an AKS module that references it.
@description('Environment suffix, e.g. "dev1". Empty string for base environment.')
#disable-next-line no-unused-params
param envName string = ''

@description('Azure region for all resources.')
param location string = 'eastus2'

// clusterName is not referenced until Phase 5 adds the AKS module.
@description('AKS cluster name (created imperatively by the CLI before this deploys).')
#disable-next-line no-unused-params
param clusterName string

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
  }
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
  }
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
// Outputs
// ──────────────────────────────────────────────────────────
//
// Outputs are in camelCase and flat; the CLI reshapes them into the
// legacy snake_case infra_outputs dict consumed by _create_osdu_config,
// populate_keyvault_secrets, and workload-identity ServiceAccount
// creation. Secrets (Cosmos primary keys) are NOT emitted as outputs
// so they stay out of deployment history; the CLI fetches them via
// `az cosmosdb keys list` after the deployment completes.

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
