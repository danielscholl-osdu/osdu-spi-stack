# Architecture

## Overview

SPI Stack deploys the OSDU platform on Azure using a hybrid model: imperative CLI commands provision Azure PaaS infrastructure, while Flux CD GitOps manages all Kubernetes workloads declaratively. Unlike a cloud-agnostic approach where all middleware runs in-cluster, SPI Stack offloads data services to Azure PaaS (CosmosDB, Service Bus, Storage, Key Vault) and retains in-cluster components only where no managed equivalent exists.

### How the system works

SPI Stack has three control planes working together:

1. **The `spi` CLI** bootstraps the environment. It provisions Azure PaaS resources via `az` commands, creates an AKS Automatic cluster, configures Workload Identity, and hands off control to Flux.
2. **Flux CD** manages desired-state reconciliation. It watches the git repository and OCI chart registry, then continuously converges the cluster to match.
3. **Kubernetes operators** (CNPG, ECK, cert-manager) manage the lifecycle of individual middleware systems beneath the Flux layer.

The CLI does the minimum work needed to get Azure resources provisioned and Flux running. After that, Flux owns everything inside the cluster.

> **Development and test posture.** The CLI and defaults are tuned for Azure dev/test environments: generated shared credentials for in-cluster middleware, self-signed gateway certificates, and optional live credential display. This makes the stack easy to spin up and inspect, but it should not be confused with a hardened production operating model.

## System Architecture

![Architecture](diagrams/architecture.png)

The diagram above shows the full system: clients connect through the AKS Managed Istio gateway, OSDU services run in the cluster with Workload Identity, and Azure PaaS services sit outside the cluster boundary. Flux CD reconciles workloads from this Git repository.

## GitOps + Bootstrap Boundary

This project uses a **GitOps + bootstrap** model:

1. The CLI performs Azure-specific bootstrap work:
   - Provision Azure PaaS resources (CosmosDB, Service Bus, Storage, Key Vault)
   - Create an AKS Automatic cluster with Managed Identity
   - Configure Workload Identity and RBAC role assignments
   - Generate and apply development secrets for in-cluster middleware
   - Activate the AKS native Flux extension
2. Flux then takes over steady-state reconciliation for everything else.

This keeps the GitOps graph clean, while accepting that Azure infrastructure provisioning must happen imperatively before Flux can start.

## Deployment Pipeline

![Deployment Pipeline](diagrams/deployment-pipeline.png)

The deployment pipeline shows both phases: the CLI's five imperative bootstrap steps (top) and Flux's seven declarative layers (bottom). The dashed line marks the handoff point.

### CLI phases

| Phase | What | Resources |
|-------|------|-----------|
| 1. Core Infra | Foundation resources | Resource Group, AKS Automatic, Managed Identity, Key Vault, ACR |
| 2. Data Infra | Data platform | CosmosDB (Gremlin + SQL), Service Bus, Storage Accounts |
| 3. IAM | Identity and access | Federated credentials, RBAC role assignments, Key Vault secrets |
| 4. K8s Bootstrap | Cluster prep | Namespaces, StorageClasses, secrets, ConfigMap, ServiceAccount |
| 5. Activate Flux | GitOps handoff | AKS native Flux extension pointing to this repo |

A full `spi up` typically takes ~15 minutes, primarily for Azure resource provisioning.

## Runtime Architecture

### Namespace model

Resources are deployed into three namespaces:

| Namespace | Purpose | Contents |
|-----------|---------|----------|
| **foundation** | Cluster-wide operators | CNPG operator, ECK operator, cert-manager |
| **platform** | Middleware infrastructure | Elasticsearch, Redis, PostgreSQL (Airflow), Airflow, Istio Gateway |
| **osdu** | Application services | OSDU service deployments, osdu-config ConfigMap, workload-identity-sa |

This separation provides clear ownership boundaries. Operators in `foundation` are cluster infrastructure. Middleware in `platform` is stack infrastructure. Services in `osdu` are the application layer. With AKS Automatic managing Istio, the `istio-system` namespace is handled by Azure and does not appear in the Flux graph. See [ADR-006](decisions/006-three-namespace-model.md).

Istio sidecar injection is enabled on `platform` and `osdu` namespaces via the `istio.io/rev` label.

### Layered dependency model

Deployment is organized into layers. Each layer must be healthy before dependent layers begin reconciliation. Layers reconcile in order; later layers depend on earlier ones.

| Layer | Name | Depends On |
|-------|------|------------|
| 0 | Namespace scaffolding | -- |
| 1 | Operators (CNPG, ECK), cert-manager, Gateway | namespaces |
| 2 | Databases (Elasticsearch, PostgreSQL), Redis | operators |
| 3 | Airflow | PostgreSQL |
| 4 | OSDU Configuration (ConfigMap placeholder) | all middleware |
| 5 | Core OSDU services (10 services) | configuration |
| 6 | Reference services (3 services) | core services |

The key design insight is that Airflow deploys in Layer 3 *after* the PostgreSQL cluster is healthy in Layer 2, avoiding startup failures from missing metadata databases. See [ADR-007](decisions/007-layered-kustomization-ordering.md).

## AKS Automatic

SPI Stack uses AKS Automatic, which provides several capabilities out of the box:

| Feature | What It Does |
|---------|-------------|
| **Karpenter** | Node Auto-Provisioning; no manual node pools to manage |
| **Managed Istio** | Service mesh with mTLS, sidecar injection, ingress gateway |
| **Deployment Safeguards** | Non-bypassable admission policies (seccomp, non-root, capabilities) |
| **Key Vault CSI** | Secrets Provider driver with automatic rotation |
| **Cilium CNI** | eBPF-based networking with overlay mode |
| **Managed Prometheus** | Metrics collection to Azure Monitor |
| **Container Insights** | Log collection to Log Analytics |

Because Safeguards are non-bypassable, every pod in the cluster must comply:
- `securityContext.runAsNonRoot: true`
- `securityContext.seccompProfile.type: RuntimeDefault`
- `securityContext.capabilities.drop: [ALL]`
- `securityContext.allowPrivilegeEscalation: false`
- Resource requests and limits defined
- Liveness and readiness probes defined

The local `osdu-spi-service` Helm chart bakes all of these into its templates so services comply at authoring time. See [ADR-002](decisions/002-aks-automatic.md) and [ADR-004](decisions/004-local-helm-chart-safeguards.md).

## Service Catalog

![Service Dependencies](diagrams/service-dependencies.png)

The diagram above shows simplified service-to-service dependencies for core OSDU APIs. Shared middleware dependencies (Elasticsearch, Redis) are omitted for clarity.

### Core services (Layer 5)

10 services forming the essential OSDU platform:

| Service | Azure PaaS Dependencies | In-Cluster Dependencies |
|---------|------------------------|------------------------|
| partition | Redis | -- |
| entitlements | CosmosDB Gremlin, Redis | -- |
| legal | CosmosDB SQL, Service Bus, Storage | Redis |
| schema | CosmosDB SQL, Service Bus, Storage | -- |
| storage | CosmosDB SQL, Service Bus, Storage | Redis |
| search | CosmosDB SQL | Elasticsearch, Redis |
| indexer | CosmosDB SQL, Service Bus | Elasticsearch, Redis |
| indexer-queue | Service Bus | -- |
| file | CosmosDB SQL, Storage | Redis |
| workflow | CosmosDB SQL, Storage | Airflow |

### Reference services (Layer 6)

3 services providing coordinate and unit reference data:

| Service | Notes |
|---------|-------|
| unit | Unit conversion; standalone, no PaaS deps |
| crs-conversion | CRS transformation; downloads SIS data via init container |
| crs-catalog | CRS reference catalog; standalone |

All services use OCI Helm charts from the OSDU community registry with the `azure` provider variant.

## Data Flow Architecture

```
                         Azure Entra ID
                              |
                         JWT Token
                              |
                              v
Client --> Istio Gateway --> OSDU Service --+--> CosmosDB (read/write records)
                                           +--> Service Bus (publish events)
                                           +--> Azure Storage (blob operations)
                                           +--> Key Vault (fetch secrets)
                                           +--> Elasticsearch (search/index)
                                           +--> Redis (cache)
                                                      |
                              +-----------------------+
                              v
              indexer-queue (Service Bus consumer)
                              |
                              v
                    indexer (Elasticsearch writer)
```

## Identity and Access Model

A single User-Assigned Managed Identity is shared by all OSDU services. Federated credentials are created for Kubernetes ServiceAccounts, allowing any pod with the `workload-identity-sa` ServiceAccount to authenticate to Azure PaaS without stored secrets.

| Component | Detail |
|-----------|--------|
| Identity | User-Assigned Managed Identity (`osdu-identity`) |
| ServiceAccount | `workload-identity-sa` in `osdu` namespace |
| Token path | `/var/run/secrets/azure/tokens/token` |
| Exchange | Azure AD token exchange (OIDC) |

### RBAC roles assigned

| Role | Purpose |
|------|---------|
| Key Vault Secrets User | Read secrets from Key Vault |
| Storage Blob Data Contributor | Blob operations on Storage Accounts |
| Storage Table Data Contributor | Table operations on Storage Accounts |
| Service Bus Data Sender | Publish messages to Service Bus topics |
| Service Bus Data Receiver | Consume messages from Service Bus subscriptions |
| AcrPull | Pull container images from ACR |

See [ADR-005](decisions/005-workload-identity.md).

## Reconciliation Lifecycle

SPI Stack has two reconciliation loops that keep the cluster converged to the desired state. Infrastructure changes flow from Git; service version changes flow from OCI artifact revisions.

### Infrastructure loop

Changes to this repository (middleware manifests, profile definitions, secrets configuration) flow through the Flux **GitRepository** source. Flux polls the git remote, detects new commits, and reconciles all **Kustomizations** in dependency order. This is how infrastructure changes (adding a component, changing resource limits) reach the cluster.

### Service update loop

When an OSDU service merges to master, its GitLab CI pipeline builds a new container image and republishes the Helm chart to the OCI registry. All OSDU service HelmReleases use `reconcileStrategy: Revision`, which tells Flux to track the OCI chart digest, not just the version string. When Flux detects a new digest, it pulls the updated chart and performs a rolling update automatically.

### Suspend and resume

The `--suspend` and `--resume` flags on `spi reconcile` control whether Flux auto-reconciles:

```bash
uv run spi reconcile --suspend   # Freeze: Flux stops polling for changes
uv run spi reconcile --resume    # Unfreeze: Flux resumes auto-reconciliation
```

When suspended, Flux stops fetching new revisions. The cluster state is frozen at the last-applied revision. A one-shot reconcile (`uv run spi reconcile`) still works while suspended. The `spi status` and `spi info` commands display a warning when reconciliation is suspended.

## Configuration and Secret Model

### osdu-config ConfigMap

Created by the CLI during bootstrap (Phase 4), this ConfigMap contains Azure PaaS endpoints injected from infrastructure provisioning outputs:

| Key | Source |
|-----|--------|
| `DOMAIN` | Ingress gateway IP/hostname |
| `DATA_PARTITION` | Primary partition name |
| `AZURE_TENANT_ID` | Azure AD tenant |
| `AAD_CLIENT_ID` | Managed identity client ID |
| `KEYVAULT_URI` | Key Vault URI |
| `COSMOSDB_ENDPOINT` | CosmosDB SQL endpoint |
| `STORAGE_ACCOUNT_NAME` | Common storage account |
| `SERVICEBUS_NAMESPACE` | Service Bus namespace |
| `REDIS_HOSTNAME` | In-cluster Redis FQDN |
| `ELASTICSEARCH_HOST` | In-cluster Elasticsearch FQDN |

All OSDU services mount this ConfigMap via `envFrom`, ensuring consistent PaaS endpoint configuration across all services.

### Secret model

| Secret Scope | Method | What |
|-------------|--------|------|
| Azure PaaS | Workload Identity | No stored secrets; token exchange at runtime |
| Azure PaaS metadata | Key Vault | Connection strings, keys, tenant info |
| Elasticsearch | K8s Secret (CLI-generated) | elastic user password |
| Redis | K8s Secret (CLI-generated) | default user password |
| PostgreSQL | K8s Secret (CLI-generated) | superuser + airflow user passwords |

The CLI generates six cryptographically random passwords at deploy time and stores them in a seed secret (`spi-secrets` in `flux-system`) for idempotent re-creation. See [ADR-010](decisions/010-keyvault-secret-management.md).

### TLS and certificates

cert-manager runs in the `foundation` namespace and provisions a self-signed root CA. The Gateway uses this CA to terminate TLS for all OSDU routes.

## Azure PaaS Resource Summary

### Per-environment (shared)

| Resource | Purpose | Sizing |
|----------|---------|--------|
| AKS Automatic | Compute | Karpenter auto-scales |
| CosmosDB Gremlin | Entitlements graph | 4000 RU/s autoscale |
| Key Vault | Secret management | Standard, RBAC-enabled |
| ACR | Container images | Basic SKU |
| Managed Identity | Workload Identity | Single, shared |

### Per-partition

| Resource | Purpose | Sizing |
|----------|---------|--------|
| CosmosDB SQL | Operational data | 4000 RU/s autoscale, 24 containers |
| Service Bus | Async messaging | Standard SKU, 14 topics |
| Storage Account | Blob/table storage | Standard LRS, 5 containers |

### In-cluster (per environment)

| Component | Instances | Storage | Purpose |
|-----------|-----------|---------|---------|
| Elasticsearch | 3 nodes | 128Gi each | Search and indexing |
| Redis | 1 master + 2 replicas | 8Gi each | Caching (TLS) |
| PostgreSQL | 3 instances (CNPG) | 10Gi + 4Gi WAL | Airflow metadata only |
| Airflow | Webserver + Scheduler + Triggerer | -- | Workflow orchestration |
