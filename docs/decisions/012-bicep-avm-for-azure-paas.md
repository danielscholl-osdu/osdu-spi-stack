# ADR-012: Bicep + Azure Verified Modules for Azure PaaS Provisioning

**Status:** Accepted

## Context

ADR-003 chose `az` CLI commands over Terraform for Azure PaaS provisioning, on the grounds that Terraform adds state-management complexity. Bicep was not weighed at that time.

`src/spi/azure_infra.py` has since grown to ~1,012 LOC orchestrating ~60 distinct `az` command patterns. Most of the weight is mechanical resource loops: 24 CosmosDB SQL containers per partition, 14 Service Bus topics with ~16 subscriptions per partition, 13 storage containers, 8 federated credentials, 7 role assignments. Several recent bugs have been ordering and flag-shape issues that ARM would have rejected at submit time rather than failing mid-deploy (AKS mesh wait races, SSH access flag on the Automatic SKU, missing cert-auth flags).

Bicep inherits ARM's idempotency and parallel orchestration without a state file, so the reasons in ADR-003 against Terraform do not apply. Azure Verified Modules (AVM) provide Microsoft-maintained, versioned Bicep modules with best-practice defaults for the resources we use.

## Decision

Migrate Azure PaaS provisioning from imperative `az` CLI commands to Bicep templates, with a thin Python orchestrator retained for the seams Bicep does not cover.

PaaS resources use raw Bicep resource declarations under `infra/modules/`. Raw Bicep removes an external dependency (MCR module downloads, version pinning maintenance) and eliminates compile-time surprises from AVM schema mismatches. A follow-up spike evaluated moving those modules to AVM and concluded the gain was not worth the cost (see the Migration section).

AKS Automatic is the exception: `infra/aks.bicep` uses the AVM `container-service/managed-cluster` module because Automatic's required configuration (SAMI, Karpenter, managed NAT gateway, Ephemeral OS disks, addons) is non-trivial to replicate correctly in hand-written Bicep, and AVM bundles expert defaults for it.

**Moves to Bicep:**
- Managed Identity + federated credentials (`infra/modules/identity.bicep`)
- Key Vault (`infra/modules/keyvault.bicep`)
- Container Registry (`infra/modules/acr.bicep`)
- CosmosDB Gremlin account + database + graph (`infra/modules/cosmos-gremlin.bicep`)
- Per-partition CosmosDB SQL + Service Bus + Storage (`infra/modules/partition.bicep`)
- Common Storage account + blob containers + table service (`infra/modules/storage-common.bicep`)
- Scoped RBAC role assignments (`infra/modules/rbac.bicep`)
- AKS Automatic cluster + managed Istio (`infra/aks.bicep`, via AVM `container-service/managed-cluster`)

**Stays imperative in Python:**
- Resource group creation
- Soft-deleted Key Vault pre-check and `az keyvault recover` (ARM cannot branch on a live query)
- `az aks get-credentials` (kubeconfig merge; not a resource)
- `az aks mesh enable-istio-cni` (AVM v0.13.0 types `proxyRedirectionMechanism` out of IstioComponents; what-if accepts it, the RP rejects at deploy time)
- `az k8s-configuration flux` (operational, not a resource)
- Key Vault secret value writes (data-plane; Bicep owns the vault and RBAC, Python writes values from deployment outputs)
- Kubernetes bootstrap and Flux activation (unchanged)

AVM module versions are pinned explicitly in each Bicep file. Upgrades are manual and intentional; no floating refs.

## Consequences

- `src/spi/azure_infra.py` shrinks from ~1,012 LOC to ~470 LOC: a pre-check step, the AKS Bicep deploy, post-deploy CNI chaining, the main Bicep deploy, output parsing, and Key Vault secret value writes.
- Imperative ordering workarounds (federated-credential throttling, mesh-update waits, soft-delete recovery dance, per-container parallel loops via `ThreadPoolExecutor`) go away or shrink dramatically.
- The CLI gains a `--dry-run` capability via `az deployment group what-if`, which has no equivalent in the current imperative code.
- Debugging shifts from per-command stderr panels to ARM deployment operation logs. Mitigated by streaming deployment operations in verbose mode.
- Bicep is bundled with recent `az` CLI versions; no new tool install for most users. `uv run spi check` verifies `az bicep version`.
- ADR-003 remains the authoritative decision for the CLI + GitOps hybrid model overall. This ADR supersedes only the "use `az` CLI commands" portion of ADR-003, for Azure PaaS provisioning.
- ADR-011's new UAMI, federated credential, and Key Vault role assignment for the bootstrap Job are added cheaply as new entries in the Bicep modules, validating that the migration makes future additions easier rather than harder.

## Migration

The migration is staged in five phases, each independently shippable:

1. **Identity + federated credentials** -- `infra/modules/identity.bicep` replaces the federated-credential loop.
2. **Shared resources** -- Key Vault, ACR, Gremlin account, common Storage.
3. **Per-partition resources** -- Cosmos SQL (+ system DB on the primary partition), Service Bus with topics and subscriptions, partition Storage with containers.
4. **RBAC** -- `infra/modules/rbac.bicep` with deterministic `guid()` names so re-deploys update rather than duplicate.
5. **AKS Automatic + managed Istio** -- declared in `infra/aks.bicep` via the AVM `container-service/managed-cluster` module (v0.13.0). The module uses a system-assigned managed identity, `outboundType='managedNATGateway'`, Ephemeral OS disks on the system pool, and a `serviceMeshProfile` that turns on Istio with an External ingress gateway. Two AVM gaps remain imperative: `az aks get-credentials` (kubeconfig merge, not a resource) and `az aks mesh enable-istio-cni` (the AVM v0.13.0 IstioComponents schema types out `proxyRedirectionMechanism`).

Phases 1-4 shipped together in commit `782649b`. Phase 5 shipped in two follow-up commits: cluster migration to AVM, then removal of the now-redundant `_configure_safeguards` step.

**Deployment Safeguards** were not migrated as a distinct Bicep concern. On the AKS Automatic SKU, safeguards are enforced via a non-bypassable `ValidatingAdmissionPolicy` -- they cannot be relaxed from the cluster side. The local Helm chart at `software/charts/osdu-spi-service` is written to satisfy the policy directly, so the prior `az aks update --safeguards-level Warning` workaround is no longer needed.

**AVM adoption scope** -- an initial spike evaluated migrating the PaaS modules (Key Vault, ACR, Storage, Cosmos, Service Bus, Managed Identity) to AVM as well. The conclusion was that the cost outweighed the benefit: AVM for those resource types is a thin passthrough without materially different defaults, and the sister Terraform repo (`../osdu-spi-infra`) uses AVM only for the managed cluster for the same reason. The PaaS modules stay as hand-written Bicep; AVM is used only where it meaningfully encapsulates expert configuration (AKS).

A `spi up --dry-run` flag (added post-migration) runs `az deployment group what-if` against both `infra/aks.bicep` and `infra/main.bicep`, giving reviewable ARM-level diffs before any resource provisioning.
