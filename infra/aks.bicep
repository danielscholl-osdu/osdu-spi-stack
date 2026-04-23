// Copyright 2026, Microsoft
// Licensed under the Apache License, Version 2.0.
//
// AKS Automatic cluster + managed Istio via Azure Verified Modules.
//
// Scope: only the AKS cluster. The cluster uses a system-assigned
// managed identity (required by Automatic when the managed vnet path is
// used). Workload identity for pods is a SEPARATE user-assigned identity
// created in infra/main.bicep after this template outputs the OIDC
// issuer URL for federated credentials.
//
// Known AVM gaps (v0.13.0) that remain imperative post-deploy:
//   1. safeguardsProfile is not exposed. On the Automatic SKU, safeguards
//      are enforced via a non-bypassable ValidatingAdmissionPolicy and
//      cannot be relaxed; the CLI's `az aks update --safeguards-level
//      Warning` is retained only for parity with the pre-migration path.
//   2. serviceMeshProfile.istio.components.proxyRedirectionMechanism is
//      typed-out of the IstioComponents schema (what-if accepts it, the
//      RP rejects at deploy). Use `az aks mesh enable-istio-cni` post-
//      deploy to flip to CNIChaining.

targetScope = 'resourceGroup'

// ──────────────────────────────────────────────
// Parameters
// ──────────────────────────────────────────────

@description('AKS cluster name.')
param clusterName string

@description('Azure region.')
param location string = resourceGroup().location

@description('Kubernetes version for the cluster.')
param kubernetesVersion string = '1.34'

@description('VM size for the system pool. D4lds_v5 has a 150 GiB cache that fits the 128 GiB default ephemeral OS disk.')
param systemPoolVmSize string = 'Standard_D4lds_v5'

// ──────────────────────────────────────────────
// Private network (BYO VNet)
// ──────────────────────────────────────────────
//
// AKS Automatic's managed-VNet path is blocked on Microsoft corporate
// tenants by the "Subnets should be private" Azure Policy, which
// requires ``defaultOutboundAccess: false`` on every subnet. The
// managed VNet does not set that flag, so we pre-create a VNet and
// subnet here and pass the subnet ID into the cluster.

module vnetModule 'modules/vnet.bicep' = {
  name: 'spi-aks-vnet'
  params: {
    vnetName: '${clusterName}-vnet'
    natGatewayName: '${clusterName}-natgw'
    publicIpName: '${clusterName}-natgw-pip'
    location: location
  }
}

// ──────────────────────────────────────────────
// Cluster control-plane identity (UAMI)
// ──────────────────────────────────────────────
//
// AKS Automatic + BYO VNet rejects SAMI with
// ``OnlySupportedOnUserAssignedMSICluster``. This is a DIFFERENT
// identity from the OSDU workload identity in infra/main.bicep; this
// one is consumed only by the cluster control plane to reconcile
// network resources in the pre-existing VNet.
//
// The UAMI needs ``Network Contributor`` on the VNet so the cluster
// can attach NICs, manage the NAT gateway association, and reconcile
// the API server subnet delegation. We scope to the VNet rather than
// each subnet individually: AKS Automatic uses a node subnet AND a
// delegated API server subnet (VNet integration), and VNet-level
// scoping keeps the assignment set minimal.

var clusterIdentityName = '${clusterName}-ctl-id'
var networkContributorRoleId = '4d97b98b-1d4f-4787-a291-c67834d212e7'

resource clusterIdentity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: clusterIdentityName
  location: location
}

resource aksVnet 'Microsoft.Network/virtualNetworks@2024-01-01' existing = {
  name: '${clusterName}-vnet'
}

resource clusterIdentityNetworkContributor 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: aksVnet
  name: guid(aksVnet.id, clusterIdentity.id, networkContributorRoleId)
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributorRoleId)
    principalId: clusterIdentity.properties.principalId
    principalType: 'ServicePrincipal'
  }
  dependsOn: [
    vnetModule
  ]
}

// ──────────────────────────────────────────────
// AKS Automatic cluster via AVM
// ──────────────────────────────────────────────
//
// Automatic SKU validation requires:
//   - UAMI (user-assigned managed identity) when using BYO VNet.
//     Managed-VNet Automatic clusters require SAMI; BYO-VNet requires
//     UAMI; these are mutually exclusive.
//   - Ephemeral OS disks on the system pool
//   - webApplicationRouting and KeyvaultSecretsProvider addons enabled
//
// With BYO VNet, outboundType switches from managedNATGateway to
// userAssignedNATGateway (the NAT we pre-created in vnet.bicep).

module aksCluster 'br/public:avm/res/container-service/managed-cluster:0.13.0' = {
  name: 'spi-aks-automatic'
  params: {
    name: clusterName
    location: location
    skuName: 'Automatic'
    kubernetesVersion: kubernetesVersion

    // Automatic requires public API server for Karpenter.
    publicNetworkAccess: 'Enabled'

    // OIDC issuer URL is output and consumed by infra/main.bicep to
    // wire federated credentials to the workload-identity SAs.
    enableOidcIssuerProfile: true

    // UAMI on the cluster (required for BYO VNet; see block above).
    // Workload identity for pods is a separate UAMI in infra/main.bicep.
    managedIdentities: {
      userAssignedResourceIds: [
        clusterIdentity.id
      ]
    }

    // BYO VNet: outbound goes through the user-assigned NAT Gateway
    // attached to the subnet in vnet.bicep.
    outboundType: 'userAssignedNATGateway'
    networkPlugin: 'azure'
    serviceCidr: '192.168.0.0/16'
    dnsServiceIP: '192.168.0.10'

    // API server VNet integration is always-on for AKS Automatic with
    // BYO VNet and requires a dedicated delegated subnet distinct from
    // the node subnet (see vnet.bicep).
    apiServerAccessProfile: {
      subnetId: vnetModule.outputs.apiServerSubnetId
    }

    enableKeyvaultSecretsProvider: true
    enableSecretRotation: true
    webApplicationRoutingEnabled: true

    // Explicitly enable the CSI disk/file/blob drivers and snapshot
    // controller. AKS Automatic installs these by default, but AVM
    // v0.13.0 passes through null for unset flags; declaring them
    // matches the sister Terraform repo
    // (../osdu-spi-infra/main/infra/aks.tf:82-87) and removes the
    // ambiguity that appears to leave PVCs stuck in ExternalProvisioning
    // on fresh clusters. AVM exposes these as four scalar booleans
    // rather than a nested storageProfile block.
    enableStorageProfileDiskCSIDriver: true
    enableStorageProfileFileCSIDriver: true
    enableStorageProfileBlobCSIDriver: true
    enableStorageProfileSnapshotController: true

    // System pool. AVM requires primaryAgentPoolProfiles even though
    // Automatic uses Karpenter for user workloads; this pool carries
    // system addons only.
    primaryAgentPoolProfiles: [
      {
        name: 'systempool'
        mode: 'System'
        vmSize: systemPoolVmSize
        osDiskType: 'Ephemeral'
        availabilityZones: [
          1
          2
          3
        ]
        vnetSubnetResourceId: vnetModule.outputs.subnetId
      }
    ]

    // Managed Istio with External ingress gateway. CNI chaining is
    // applied imperatively post-deploy (see top-of-file note).
    //
    // revisions is pinned to prevent AKS from silently upgrading the
    // mesh under us. `asm-1-28` matches the sister Terraform repo
    // (../osdu-spi-infra/main/infra/aks.tf) and is the current AVM
    // default; validated with 1.34 on KubernetesOfficial and LTS.
    serviceMeshProfile: {
      mode: 'Istio'
      istio: {
        revisions: [
          'asm-1-28'
        ]
        components: {
          ingressGateways: [
            {
              enabled: true
              mode: 'External'
            }
          ]
        }
      }
    }
  }
}

// ──────────────────────────────────────────────
// Outputs (consumed by downstream Bicep + CLI imperative steps)
// ──────────────────────────────────────────────

output clusterName string = clusterName
output clusterResourceId string = aksCluster.outputs.resourceId
output oidcIssuerUrl string = aksCluster.outputs.?oidcIssuerUrl ?? ''
output clusterPrincipalId string = clusterIdentity.properties.principalId
