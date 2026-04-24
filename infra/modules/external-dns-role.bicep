// DNS Zone Contributor role assignment for ExternalDNS. Deploys into
// the DNS zone's resource group so ``existing`` resolves the zone and
// the role assignment's scope can bind to it. Assumes the zone lives
// in the same subscription as the AKS cluster (callers invoke this
// module with ``scope: resourceGroup(dnsZoneResourceGroup)``).

targetScope = 'resourceGroup'

@description('DNS zone name (e.g. example.com).')
param dnsZoneName string

@description('Principal ID (object ID) of the external-dns managed identity.')
param principalId string

// Built-in role: DNS Zone Contributor
var dnsZoneContributorRoleId = 'befefa01-2a29-4197-83a8-272ff33ce314'

resource zone 'Microsoft.Network/dnsZones@2018-05-01' existing = {
  name: dnsZoneName
}

resource roleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: zone
  name: guid(zone.id, principalId, dnsZoneContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', dnsZoneContributorRoleId)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}
