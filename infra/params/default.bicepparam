// Default parameters for infra/main.bicep -- BASE environment (envName = '').
//
// The CLI (src/spi/azure_infra.py) synthesizes an ARM parameters JSON from
// the Config object at deploy time, so this file is only used by humans
// running `az deployment group create` manually. For a realistic named
// environment, see dev1.bicepparam alongside this file.
//
// The double-dash names (osdu--graph, osdu--opendes-cosmos, osdu--opendes-bus)
// are intentional: they come from templates like f"osdu-{env}-graph" when
// envName is empty. They match what Config.from_env('') produces and are
// valid Azure resource names.
//
// oidcIssuerUrl is empty here; leave it empty to run Bicep without the AKS
// cluster present (federated credentials are skipped). A real deploy through
// the CLI fills this in after `az aks show` returns the OIDC issuer URL.

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
