# ADR-003: CLI + GitOps Hybrid Deployment

**Status:** Accepted. Superseded in part by ADR-012 (Bicep + AVM for Azure PaaS provisioning): the "Phase 1-3 via `az` CLI" portion of the decision below is replaced by a single Bicep deployment for all PaaS resources. Resource Group, AKS Automatic, soft-delete Key Vault recovery, and Key Vault secret value writes remain imperative in the CLI.

## Context

A pure CLI + GitOps model creates a Kubernetes cluster and installs Flux, then Flux manages everything inside the cluster. This works when there are no external infrastructure dependencies.

SPI Stack requires Azure PaaS resources (CosmosDB, Service Bus, Storage, Key Vault) that must exist before OSDU services can start. These resources cannot be managed by Flux because they live outside the cluster.

Alternatives considered:
- **Terraform for everything**: Mature but introduces state management complexity. The osdu-spi-infra project uses this approach.
- **Azure Developer CLI (azd)**: Good for prototyping but couples to azd lifecycle hooks.
- **az CLI commands**: Simple, transparent, no state files, easy to debug.

## Decision

Use a hybrid model:

1. **az CLI** (imperative, Phase 1-3): Provision all Azure PaaS resources using direct `az` commands. No Terraform state files, no plan/apply cycle. Commands are displayed transparently via Rich panels.

2. **kubectl** (imperative, Phase 4): Bootstrap the cluster with namespaces, secrets, ConfigMap, and ServiceAccount. These must exist before Flux starts reconciling.

3. **Flux CD** (declarative, Phase 5+): Manage all Kubernetes workloads via GitOps. Operators, middleware, and OSDU services are defined as Kustomizations and HelmReleases in this repository.

## Consequences

- No Terraform state to manage; idempotent `az` commands can be re-run safely.
- Full command transparency; every `az` command is displayed before execution.
- Longer initial deployment (~15 min for Azure resource provisioning).
- Azure resource cleanup is a single `az group delete` (resource group scoping).
- The CLI is the single entry point; no separate infrastructure repository needed.
