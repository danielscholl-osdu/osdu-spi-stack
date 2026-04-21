// User-assigned managed identity with federated credentials bound to
// the fixed set of Kubernetes namespaces that run OSDU workloads.
//
// The OIDC issuer URL must come from an existing AKS cluster; the CLI
// fetches it via `az aks show --query oidcIssuerProfile.issuerUrl`
// and passes it in. If empty, federated credentials are skipped (useful
// for CI compile checks, not for a real deploy).

@description('Managed identity name.')
param name string

@description('Azure region.')
param location string

@description('OIDC issuer URL from AKS. Empty string skips federated credential creation.')
param oidcIssuerUrl string

@description('Kubernetes namespaces that bind to this identity via workload-identity-sa.')
param federatedNamespaces array = [
  'default'
  'osdu-core'
  'airflow'
  'osdu-system'
  'osdu-auth'
  'osdu-reference'
  'osdu'
  'platform'
]

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

// ARM's Managed Identity RP rejects concurrent federated credential
// writes against the same UAMI (ConcurrentFederatedIdentityCredentials-
// WritesForSingleManagedIdentity). Bicep's default copy-loop schedules
// iterations in parallel, so @batchSize(1) is required to serialize
// the 8 credential creations; without it, all-but-one fail on a fresh
// deploy. Adds ~1-2 minutes to first-run provisioning.
@batchSize(1)
resource federatedCredentials 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = [for ns in federatedNamespaces: if (!empty(oidcIssuerUrl)) {
  parent: identity
  name: 'federated-ns-${ns}'
  properties: {
    issuer: oidcIssuerUrl
    subject: 'system:serviceaccount:${ns}:workload-identity-sa'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}]

output resourceId string = identity.id
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
