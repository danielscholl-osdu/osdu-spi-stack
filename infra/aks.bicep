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
// AKS Automatic cluster via AVM
// ──────────────────────────────────────────────
//
// Automatic SKU validation requires:
//   - OutboundType = managedNATGateway
//   - SAMI (system-assigned managed identity) when using managed vnet
//   - Ephemeral OS disks on the system pool
//   - webApplicationRouting and KeyvaultSecretsProvider addons enabled

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

    // SAMI on the cluster. Workload identity for pods is a separate
    // user-assigned identity created in infra/main.bicep.
    managedIdentities: {
      systemAssigned: true
    }

    // Automatic SKU recommendations.
    outboundType: 'managedNATGateway'
    enableKeyvaultSecretsProvider: true
    enableSecretRotation: true
    webApplicationRoutingEnabled: true

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
output clusterPrincipalId string = aksCluster.outputs.?systemAssignedMIPrincipalId ?? ''
