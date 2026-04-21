// Default parameters for infra/main.bicep.
//
// Matches the base environment (envName = '') produced by Config.from_env('').
// Override values by passing --parameters key=value on the command line or by
// copying this file and editing per environment.
//
// The CLI (src/spi/azure_infra.py) generates a synthesized ARM parameters
// JSON file at deploy time from the Config object; this file is primarily
// for humans running az deployment group create manually.

using '../main.bicep'

param envName = ''
param location = 'eastus2'

// Names derived by Config.from_env('') and the _*_name helpers in azure_infra.py
param clusterName = 'spi-stack'
param identityName = 'spi-stack-osdu-identity'
param keyVaultName = 'osduspistack'
param acrName = 'osduspistack'

param dataPartitions = [
  'opendes'
]
param primaryPartition = 'opendes'

param gremlinAccountName = 'osdu--graph'
param commonStorageName = 'osducommon'

param cosmosSqlNames = [
  'osdu--opendes-cosmos'
]
param serviceBusNames = [
  'osdu--opendes-bus'
]
param partitionStorageNames = [
  'osduopendes'
]

param oidcIssuerUrl = ''
