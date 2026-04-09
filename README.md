# OSDU SPI Stack

Azure-native OSDU deployment using AKS Automatic + Azure PaaS services + Flux CD GitOps.

## Architecture

**Hybrid approach**: Python CLI provisions Azure infrastructure via `az` commands, then Flux CD manages Kubernetes workloads via GitOps.

### Azure PaaS Resources (provisioned by CLI)

| Resource | Purpose |
|----------|---------|
| AKS Automatic | Kubernetes with managed Istio, Karpenter, Safeguards |
| CosmosDB Gremlin | Entitlements graph |
| CosmosDB SQL | OSDU operational data (per partition) |
| Service Bus | Async messaging (per partition, 14 topics) |
| Storage Accounts | Blob/table storage (common + per partition) |
| Key Vault | Centralized secret management |
| Managed Identity | Workload Identity for all OSDU services |

### In-Cluster Middleware (managed by Flux GitOps)

| Component | Purpose |
|-----------|---------|
| Elasticsearch (ECK) | Full-text search and indexing |
| Redis (Bitnami) | Caching with TLS |
| PostgreSQL (CNPG) | Airflow metadata only |
| Apache Airflow | Workflow orchestration |
| cert-manager | Internal TLS certificates |

### OSDU Services (managed by Flux GitOps)

10 core services + 3 reference services deployed via a local Helm chart (`osdu-spi-service`) with AKS Automatic Deployment Safeguards compliance baked in.

## Quick Start

```bash
# 1. Check prerequisites
uv run spi check

# 2. Deploy (creates all Azure resources + deploys via GitOps)
uv run spi up --env dev1

# 3. Monitor deployment
uv run spi status --watch

# 4. View endpoints
uv run spi info

# 5. Cleanup
uv run spi down --env dev1
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `spi check` | Validate required CLI tools (az, kubectl, flux, helm) |
| `spi up --env NAME` | Provision Azure infra + deploy OSDU stack |
| `spi down --env NAME` | Delete all Azure resources |
| `spi status [-w]` | Show deployment health dashboard |
| `spi info [--show-secrets]` | Show endpoints and credentials |
| `spi reconcile` | Force Flux to reconcile |

## Project Structure

```
osdu-spi-stack/
├── src/spi/                      # Python CLI
│   ├── cli.py                    # Main commands (check, up, down, status, info, reconcile)
│   ├── config.py                 # Configuration model
│   ├── azure_infra.py            # Azure PaaS provisioning (az CLI commands)
│   ├── secrets.py                # In-cluster secret generation (ES, Redis, PG)
│   ├── templates.py              # Kubernetes YAML templates
│   ├── status.py                 # Deployment dashboard
│   ├── info.py                   # Endpoint display
│   └── providers/azure.py        # Orchestrates infra + bootstrap + GitOps
│
├── software/
│   ├── charts/osdu-spi-service/  # Local Helm chart (Safeguards-compliant)
│   ├── components/               # In-cluster middleware (Flux manifests)
│   │   ├── cert-manager/
│   │   ├── operators/eck/
│   │   ├── operators/cnpg/
│   │   ├── elasticsearch/
│   │   ├── redis/
│   │   ├── postgres/
│   │   ├── airflow/
│   │   └── gateway/
│   └── stacks/osdu/
│       ├── profiles/core/        # Layered Kustomization stack (7 layers)
│       ├── services/             # 10 core OSDU service HelmReleases
│       └── services-reference/   # 3 reference service HelmReleases
│
└── pyproject.toml
```

## Deployment Phases

1. **Core Infra**: Resource Group, AKS Automatic, Managed Identity, Key Vault, ACR
2. **Data Infra**: CosmosDB (Gremlin + SQL), Service Bus, Storage Accounts
3. **IAM**: Federated credentials, RBAC role assignments, Key Vault secrets
4. **K8s Bootstrap**: Namespaces, StorageClasses, secrets, ConfigMap, ServiceAccount
5. **GitOps**: AKS native Flux extension pointing to this repo

## Key Differences from CIMPL Stack

| Aspect | CIMPL Stack | SPI Stack |
|--------|------------|-----------|
| Provider | Multi-cloud (KinD, Azure, AWS, GCP) | Azure-only |
| AKS | Standard AKS | AKS Automatic |
| Database | In-cluster PostgreSQL (CNPG) | Azure CosmosDB |
| Messaging | In-cluster RabbitMQ | Azure Service Bus |
| Object Storage | In-cluster MinIO | Azure Storage |
| Secrets | In-cluster (K8s secrets) | Azure Key Vault |
| Auth | In-cluster Keycloak | Azure Entra ID |
| Identity | Static credentials | Workload Identity |
| Service Mesh | Self-managed Istio | AKS Managed Istio |
