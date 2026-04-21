# OSDU SPI Stack

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
![Status: Experimental](https://img.shields.io/badge/status-experimental-orange.svg)

### Azure-Native Software for OSDU

SPI Stack deploys the OSDU platform onto Azure using AKS Automatic and Azure PaaS services with a bootstrap + [Flux CD](https://fluxcd.io/) GitOps model. Infrastructure is provisioned via `az` CLI commands, then Flux continuously reconciles Kubernetes workloads from this Git repository.

This project is currently optimized for Azure dev/test environments and is still evolving.

**Who this is for:**

- Developers who want a reproducible Azure-based OSDU environment
- Platform engineers evaluating OSDU with Azure PaaS services


## Why SPI Stack

- **Azure-native**: leverages CosmosDB, Service Bus, Storage, Key Vault, and Entra ID
- **AKS Automatic**: managed Istio, Karpenter, and Deployment Safeguards out of the box
- **GitOps-driven**: Flux continuously reconciles desired state after bootstrap
- **Transparent**: every `az` and `kubectl` command is shown before execution
- **Workload Identity**: no stored credentials; all Azure access via federated identity


## Quick Start

The only tool you need to get started is [`uv`](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/danielscholl-osdu/osdu-spi-stack.git
cd osdu-spi-stack

# Check prerequisites
uv run spi check

# Deploy (provisions Azure resources + activates GitOps)
uv run spi up --env dev1
```

### After Deploy

```bash
uv run spi status              # Deployment health dashboard
uv run spi status --watch      # Continuous refresh
uv run spi info                # Endpoints and credentials

uv run spi reconcile --suspend # Freeze: stop Flux auto-reconciliation
uv run spi reconcile --resume  # Unfreeze: resume Flux auto-reconciliation

uv run spi down --env dev1     # Tear down when done
```


## Operating Model

SPI Stack is **GitOps + bootstrap**, not "pure GitOps from an empty cluster."

The CLI performs a bootstrap phase:

- Provision Azure PaaS resources (CosmosDB, Service Bus, Storage, Key Vault)
- Create an AKS Automatic cluster with Managed Identity
- Configure Workload Identity and RBAC role assignments
- Bootstrap the cluster with namespaces, secrets, ConfigMap, and ServiceAccount
- Activate the AKS native Flux extension pointing to this repo

After that handoff, **Flux owns steady-state reconciliation** and continuously converges the cluster to the desired state.

<details>
<summary>Deployment phases</summary>

1. **Core Infra**: Resource Group, AKS Automatic, Managed Identity, Key Vault, ACR
2. **Data Infra**: CosmosDB (Gremlin + SQL), Service Bus, Storage Accounts
3. **IAM**: Federated credentials, RBAC role assignments, Key Vault secrets
4. **K8s Bootstrap**: Namespaces, StorageClasses, secrets, ConfigMap, ServiceAccount
5. **GitOps**: AKS native Flux extension pointing to this repo

A full `spi up` typically takes ~15 minutes, primarily for Azure resource provisioning.

</details>

<details>
<summary>Environment isolation</summary>

Use `--env` to run multiple isolated deployments. Each environment gets its own resource group and cluster (e.g., `spi-stack-dev1`, `spi-stack-team`).

```bash
uv run spi up --env dev1
uv run spi up --env staging
```

</details>


## What It Deploys

Three namespaces, deployed in dependency order via a 7-layer Kustomization stack:

| Namespace | Layer | Deploys |
|-----------|-------|---------|
| **foundation** | Operators | ECK (Elasticsearch), CNPG (PostgreSQL), cert-manager |
| **platform** | Middleware | Elasticsearch, Redis (TLS), PostgreSQL (Airflow), Airflow, Istio Gateway |
| **osdu** | Services | partition, entitlements, legal, schema, storage, search, indexer, file, workflow + 3 reference services |

### Azure PaaS Resources

| Resource | Purpose |
|----------|---------|
| AKS Automatic | Kubernetes with managed Istio, Karpenter, Safeguards |
| CosmosDB Gremlin | Entitlements graph |
| CosmosDB SQL | OSDU operational data (per partition) |
| Service Bus | Async messaging (per partition, 14 topics) |
| Storage Accounts | Blob/table storage (common + per partition) |
| Key Vault | Centralized secret management |
| Managed Identity | Workload Identity for all OSDU services |


## Prerequisites

Everything is discovered by the CLI:

```bash
uv run spi check
```

**Required tools**: az, kubectl, flux, helm

**System requirements**: Azure subscription with permissions to create resource groups and AKS clusters.

<details>
<summary>AI-assisted setup</summary>

If you use an AI coding assistant (Claude Code, GitHub Copilot, Cursor), this project includes an [AGENTS.md](AGENTS.md) file to help it interpret `spi check` output and guide prerequisite installation. `spi check` remains the source of truth.

</details>


## CLI Reference

```
uv run spi <command> [OPTIONS]

Commands:
  check      Validate required tools are installed       
  up         Provision Azure infra and deploy the stack   --env NAME [--profile] [--partition] [--dry-run]
  status     Deployment health dashboard                  [--watch]
  down       Delete all Azure resources                   --env NAME
  info       Show endpoints and optional credentials      [--show-secrets]
  reconcile  Force Flux to re-sync from Git               [--suspend] [--resume]
```

Use `--dry-run` on `spi up` to preview the Bicep changes (`az deployment group what-if`) before any Azure resources are created beyond the resource group.


## Documentation

- [Architecture](docs/architecture.md)
- [AI Skills](docs/ai-skills.md)
- [ADRs](docs/decisions/)

## License

Licensed under the [Apache License 2.0](LICENSE).
