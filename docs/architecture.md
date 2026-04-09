# SPI Stack Architecture

SPI Stack deploys the OSDU platform on Azure using a hybrid model: imperative CLI commands provision Azure PaaS infrastructure, while Flux CD GitOps manages all Kubernetes workloads declaratively.

## System Overview

Three control planes collaborate to deliver the full stack:

1. **SPI CLI** (imperative, one-time): Provisions Azure resources (CosmosDB, Service Bus, Storage, Key Vault, AKS Automatic, Managed Identity) and bootstraps the cluster (namespaces, secrets, ConfigMap, ServiceAccount).

2. **Flux CD** (declarative, continuous): Reconciles all Kubernetes workloads from this Git repository. Manages operators, middleware, and OSDU services via layered Kustomizations with explicit dependency ordering.

3. **Kubernetes Operators** (declarative, lifecycle): ECK manages Elasticsearch clusters, CNPG manages PostgreSQL instances. Both handle scaling, failover, and upgrades autonomously.

```
 ┌─────────────────────────────────────────────────────────────────────┐
 │                        Git Repository                              │
 │   software/components/*    software/stacks/osdu/*                  │
 └────────────────────────────────┬────────────────────────────────────┘
                                  │ Flux polls (5 min)
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │                         Flux CD v2                                  │
 │  GitRepository ──► Kustomizations (7 layers) ──► HelmReleases      │
 └────────────────────────────────┬─────────────────────────────────────┘
                                  │ applies manifests
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │                     AKS Automatic Cluster                           │
 │                                                                     │
 │  foundation:  ECK, CNPG, cert-manager operators                     │
 │  platform:    Elasticsearch, Redis, PostgreSQL, Airflow             │
 │  osdu:        10 core + 3 reference OSDU services                   │
 └──────────────────────────────────────────────────────────────────────┘
                                  │ Workload Identity
                                  ▼
 ┌──────────────────────────────────────────────────────────────────────┐
 │                     Azure PaaS Services                             │
 │                                                                     │
 │  CosmosDB (Gremlin) ── Entitlements graph                           │
 │  CosmosDB (SQL)     ── OSDU operational data (24 containers)        │
 │  Service Bus        ── Async messaging (14 topics)                  │
 │  Storage Accounts   ── Blob/table storage                           │
 │  Key Vault          ── Centralized secrets                          │
 └──────────────────────────────────────────────────────────────────────┘
```

## Deployment Phases

The CLI orchestrates five sequential phases:

```
Phase 1: Core Infra          Phase 2: Data Infra         Phase 3: IAM
┌──────────────────┐         ┌──────────────────┐        ┌──────────────────┐
│ Resource Group   │         │ CosmosDB Gremlin │        │ Federated Creds  │
│ AKS Automatic    │         │ CosmosDB SQL     │        │ Role Assignments │
│ Managed Identity │  ──►    │ Service Bus      │  ──►   │ KV Secrets       │
│ Key Vault        │         │ Storage Accounts │        │                  │
│ ACR              │         │                  │        │                  │
└──────────────────┘         └──────────────────┘        └──────────────────┘
                                                                  │
                                                                  ▼
Phase 4: K8s Bootstrap                    Phase 5: GitOps
┌──────────────────────┐                  ┌──────────────────────┐
│ Namespaces           │                  │ AKS GitOps Extension │
│ StorageClasses       │                  │ Flux GitRepository   │
│ Secrets (ES/Redis/PG)│   ──►            │ Kustomization stack  │
│ osdu-config ConfigMap│                  │ (7 layers)           │
│ Workload Identity SA │                  │                      │
│ Gateway API CRDs     │                  │                      │
└──────────────────────┘                  └──────────────────────┘
```

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

The local `osdu-spi-service` Helm chart bakes all of these into its templates so services comply at authoring time.

## Namespace Model

Three namespaces provide clear workload isolation:

| Namespace | Owner | Contents |
|-----------|-------|----------|
| `foundation` | Flux | ECK operator, CNPG operator, cert-manager |
| `platform` | Flux + Operators | Elasticsearch (ECK), Redis, PostgreSQL (CNPG), Airflow |
| `osdu` | Flux | All OSDU microservices, osdu-config ConfigMap, workload-identity-sa |

Istio sidecar injection is enabled on `platform` and `osdu` namespaces via the `istio.io/rev` label.

## Layered Dependency Model

Flux Kustomizations enforce strict deployment ordering via `dependsOn`:

```
Layer 0: Namespaces
    │
    ├──► Layer 1a: cert-manager
    │        │
    │        └──► Layer 2b: Redis (needs TLS certs)
    │
    ├──► Layer 1b: ECK Operator
    │        │
    │        └──► Layer 2a: Elasticsearch (needs ECK CRDs)
    │
    ├──► Layer 1c: CNPG Operator
    │        │
    │        └──► Layer 2c: PostgreSQL (needs CNPG CRDs)
    │                 │
    │                 └──► Layer 3: Airflow (needs PG metadata DB)
    │
    └──► Layer 1d: Gateway

Layer 4: OSDU Configuration (ConfigMap placeholder)
    │
    └──► Layer 5: Core OSDU Services (10 services)
              │
              └──► Layer 6: Reference Services (3 services)
```

Each layer only begins reconciliation after its dependencies report healthy. This prevents startup failures from missing CRDs, databases, or operator controllers.

## Service Catalog

### Core Services (Layer 5)

| Service | Azure PaaS Dependencies | In-Cluster Dependencies |
|---------|------------------------|------------------------|
| partition | Redis | - |
| entitlements | CosmosDB Gremlin, Redis | - |
| legal | CosmosDB SQL, Service Bus, Storage | Redis |
| schema | CosmosDB SQL, Service Bus, Storage | - |
| storage | CosmosDB SQL, Service Bus, Storage | Redis |
| search | CosmosDB SQL | Elasticsearch, Redis |
| indexer | CosmosDB SQL, Service Bus | Elasticsearch, Redis |
| indexer-queue | Service Bus | - |
| file | CosmosDB SQL, Storage | Redis |
| workflow | CosmosDB SQL, Storage | Airflow |

### Reference Services (Layer 6)

| Service | Notes |
|---------|-------|
| unit | Unit conversion; standalone, no PaaS deps |
| crs-conversion | CRS transformation; downloads SIS data via init container |
| crs-catalog | CRS reference catalog; standalone |

## Data Flow Architecture

```
                         Azure Entra ID
                              │
                         JWT Token
                              │
                              ▼
Client ──► Istio Gateway ──► OSDU Service ──┬──► CosmosDB (read/write records)
                                            ├──► Service Bus (publish events)
                                            ├──► Azure Storage (blob operations)
                                            ├──► Key Vault (fetch secrets)
                                            ├──► Elasticsearch (search/index)
                                            └──► Redis (cache)
                                                      │
                              ┌────────────────────────┘
                              ▼
              indexer-queue (Service Bus consumer)
                              │
                              ▼
                    indexer (Elasticsearch writer)
```

## Identity and Access Model

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Workload Identity Flow                            │
│                                                                      │
│  Pod (osdu namespace)                                                │
│    │                                                                 │
│    ├── ServiceAccount: workload-identity-sa                          │
│    │     annotations:                                                │
│    │       azure.workload.identity/client-id: <identity-client-id>   │
│    │       azure.workload.identity/tenant-id: <tenant-id>            │
│    │                                                                 │
│    └── Projects token to /var/run/secrets/azure/tokens/token         │
│                          │                                           │
│                          ▼                                           │
│              Azure AD Token Exchange                                 │
│                          │                                           │
│                          ▼                                           │
│              User-Assigned Managed Identity                          │
│                (osdu-identity)                                       │
│                          │                                           │
│              ┌───────────┴───────────┐                               │
│              ▼                       ▼                               │
│     Azure RBAC Roles          Federated Credentials                  │
│     ├─ KV Secrets User        (8 namespaces)                         │
│     ├─ Storage Blob Contributor                                      │
│     ├─ Storage Table Contributor                                     │
│     ├─ Service Bus Data Sender                                       │
│     ├─ Service Bus Data Receiver                                     │
│     └─ AcrPull                                                       │
└──────────────────────────────────────────────────────────────────────┘
```

A single managed identity is shared by all OSDU services. Federated credentials are created for eight Kubernetes namespaces, allowing any pod with the `workload-identity-sa` ServiceAccount to authenticate to Azure PaaS without stored secrets.

## Configuration Model

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

### Secret Model

| Secret Scope | Method | What |
|-------------|--------|------|
| Azure PaaS | Workload Identity | No stored secrets; token exchange at runtime |
| Azure PaaS metadata | Key Vault | Connection strings, keys, tenant info |
| Elasticsearch | K8s Secret (CLI-generated) | elastic user password |
| Redis | K8s Secret (CLI-generated) | default user password |
| PostgreSQL | K8s Secret (CLI-generated) | superuser + airflow user passwords |

The CLI generates six cryptographically random passwords at deploy time and stores them in a seed secret (`spi-secrets` in `flux-system`) for idempotent re-creation.

## Azure PaaS Resource Summary

### Per-Environment (shared)

| Resource | Purpose | Sizing |
|----------|---------|--------|
| AKS Automatic | Compute | Karpenter auto-scales |
| CosmosDB Gremlin | Entitlements graph | 4000 RU/s autoscale |
| Key Vault | Secret management | Standard, RBAC-enabled |
| ACR | Container images | Basic SKU |
| Managed Identity | Workload Identity | Single, shared |

### Per-Partition

| Resource | Purpose | Sizing |
|----------|---------|--------|
| CosmosDB SQL | Operational data | 4000 RU/s autoscale, 24 containers |
| Service Bus | Async messaging | Standard SKU, 14 topics |
| Storage Account | Blob/table storage | Standard LRS, 5 containers |

### In-Cluster (per environment)

| Component | Instances | Storage | Purpose |
|-----------|-----------|---------|---------|
| Elasticsearch | 3 nodes | 128Gi each | Search and indexing |
| Redis | 1 master + 2 replicas | 8Gi each | Caching (TLS) |
| PostgreSQL | 3 instances (CNPG) | 10Gi + 4Gi WAL | Airflow metadata only |
| Airflow | Webserver + Scheduler + Triggerer | - | Workflow orchestration |
