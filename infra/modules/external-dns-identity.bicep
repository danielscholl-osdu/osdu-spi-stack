// User-assigned managed identity for the in-cluster ExternalDNS
// controller. Federated to the ``external-dns`` service account in the
// ``foundation`` namespace (created by the ExternalDNS Helm chart).
// DNS Zone Contributor role on the target zone is assigned by a
// sibling module scoped to the zone's resource group.

@description('Managed identity name.')
param name string

@description('Azure region.')
param location string

@description('OIDC issuer URL from AKS. Empty string skips federated credential creation.')
param oidcIssuerUrl string

@description('Kubernetes namespace that hosts the external-dns service account.')
param federatedNamespace string = 'foundation'

@description('Kubernetes service account name created by the ExternalDNS Helm chart.')
param serviceAccountName string = 'external-dns'

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: name
  location: location
}

resource federatedCredential 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(oidcIssuerUrl)) {
  parent: identity
  name: 'federated-external-dns'
  properties: {
    issuer: oidcIssuerUrl
    subject: 'system:serviceaccount:${federatedNamespace}:${serviceAccountName}'
    audiences: [
      'api://AzureADTokenExchange'
    ]
  }
}

output resourceId string = identity.id
output clientId string = identity.properties.clientId
output principalId string = identity.properties.principalId
