// GitOps activation: AKS-native Flux extension plus the cluster-scoped
// GitRepository + Kustomization that Flux will reconcile against.
//
// Deployed AFTER ``infra/aks.bicep`` and ``infra/main.bicep`` and AFTER
// the CLI's imperative K8s bootstrap phase. The Bicep declaration replaces
// the previous ``az k8s-configuration flux create`` call; re-deploys drift-
// reconcile the Kustomization config (sync interval, repo branch, profile
// path) without the CLI having to branch on create-vs-update.

targetScope = 'resourceGroup'

@description('AKS cluster name; Flux is installed as a cluster-scoped extension.')
param clusterName string

@description('Git repository URL (GitHub-style HTTPS).')
param repoUrl string

@description('Branch Flux should track.')
param repoBranch string = 'main'

@description('Profile path segment under software/stacks/osdu/profiles (e.g., "core").')
param profile string = 'core'

@description('Name of the fluxConfigurations resource on the cluster.')
param configurationName string = 'osdu-spi-stack-system'

resource aks 'Microsoft.ContainerService/managedClusters@2024-10-01' existing = {
  name: clusterName
}

resource fluxExtension 'Microsoft.KubernetesConfiguration/extensions@2024-11-01' = {
  name: 'flux'
  scope: aks
  properties: {
    extensionType: 'microsoft.flux'
    autoUpgradeMinorVersion: true
    releaseTrain: 'Stable'
    scope: {
      cluster: {
        releaseNamespace: 'flux-system'
      }
    }
  }
}

resource gitopsConfig 'Microsoft.KubernetesConfiguration/fluxConfigurations@2024-11-01' = {
  name: configurationName
  scope: aks
  properties: {
    scope: 'cluster'
    namespace: 'flux-system'
    sourceKind: 'GitRepository'
    gitRepository: {
      url: repoUrl
      repositoryRef: {
        branch: repoBranch
      }
      syncIntervalInSeconds: 600
      timeoutInSeconds: 600
    }
    kustomizations: {
      stack: {
        path: './software/stacks/osdu/profiles/${profile}'
        prune: true
        syncIntervalInSeconds: 600
        timeoutInSeconds: 1800
      }
    }
  }
  dependsOn: [
    fluxExtension
  ]
}

output configurationName string = gitopsConfig.name
output extensionName string = fluxExtension.name
