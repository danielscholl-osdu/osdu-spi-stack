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


## Install

The only tool you need is [`uv`](https://docs.astral.sh/uv/). Install the
latest released `spi` binary directly from a GitHub Release:

```bash
uv tool install https://github.com/danielscholl-osdu/osdu-spi-stack/releases/latest/download/spi-latest-py3-none-any.whl
spi --version
```

Pin to a specific version (recommended for reproducibility) by replacing
`latest` with `vX.Y.Z` and the wheel name accordingly:

```bash
uv tool install https://github.com/danielscholl-osdu/osdu-spi-stack/releases/download/v0.1.1/spi-0.1.1-py3-none-any.whl
```

After install the `spi` binary is on PATH; no `uv run` prefix.

To upgrade in place to the newest release:

```bash
spi update           # check for a newer version and install it
spi update --check   # check only; do not install
spi update --force   # reinstall even if already on the latest version
```

> **Note:** `uv tool install git+https://github.com/...@vX.Y.Z` also works,
> but the wheel-URL form above is preferred because it preserves the
> tag-derived version in `spi --version` reliably.

## Quick Start

Once installed:

```bash
# Check prerequisites
spi check

# Deploy (provisions Azure resources + activates GitOps)
spi up --env dev1

# Multi-partition deploy (one CosmosDB + Service Bus + storage per partition)
spi up --env dev1 --partition opendes --partition tenant1

# Pick an ingress mode (default: azure)
spi up --env dev1 --ingress-mode dns --dns-zone example.com
spi up --env dev1 --ingress-mode ip       # debug / smoke
```

### After Deploy

```bash
spi status              # Deployment health dashboard
spi status --watch      # Continuous refresh
spi info                # Endpoints and credentials

spi reconcile --suspend # Freeze: stop Flux auto-reconciliation
spi reconcile --resume  # Unfreeze: resume Flux auto-reconciliation

spi down --env dev1     # Tear down when done
```

## Development Setup

To work on `spi` itself rather than install it:

```bash
git clone https://github.com/danielscholl-osdu/osdu-spi-stack.git
cd osdu-spi-stack
uv sync
uv run spi --help
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for the full developer workflow,
including pre-commit setup, conventional commits, and the release process.


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

A full `spi up` typically takes ~45-50 minutes in `centralus`, dominated by AKS Automatic provisioning (~30 min). Other regions may vary.

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


## CLI Reference

```
uv run spi <command> [OPTIONS]

Commands:
  check      Validate required tools are installed
  up         Provision Azure infra and deploy the stack   --env NAME [--profile] [--partition] [--ingress-mode] [--dns-zone] [--dry-run]
  status     Deployment health dashboard                  [--watch]
  down       Delete all Azure resources                   --env NAME
  info       Show endpoints and optional credentials      [--show-secrets]
  reconcile  Force Flux to re-sync from Git               [--suspend] [--resume] [--refresh-images]
```

Use `--dry-run` on `spi up` to preview the Bicep changes (`az deployment group what-if`) before any Azure resources are created beyond the resource group. `--ingress-mode` defaults to `azure`; the other supported modes are `dns` (per-service hostnames on an owned Azure DNS zone) and `ip` (bare IP, debug only). `--refresh-images` re-resolves the OSDU community image tags and reconciles the service Kustomizations.


## Documentation

- [Architecture](docs/architecture.md)  -- 30,000-ft overview of the system
- [Design docs](docs/design/)  -- how subsystems actually work (deployment lifecycle, Bicep, Flux, Workload Identity, ingress, secrets)
- [ADRs](docs/decisions/)  -- decision records with alternatives considered

## License

Licensed under the [Apache License 2.0](LICENSE).
