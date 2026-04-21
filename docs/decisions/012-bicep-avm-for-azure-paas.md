# ADR-012: Bicep + Azure Verified Modules for Azure PaaS Provisioning

**Status:** Accepted

## Context

ADR-003 chose `az` CLI commands over Terraform for Azure PaaS provisioning, on the grounds that Terraform adds state-management complexity. Bicep was not weighed at that time.

`src/spi/azure_infra.py` has since grown to ~1,012 LOC orchestrating ~60 distinct `az` command patterns. Most of the weight is mechanical resource loops: 24 CosmosDB SQL containers per partition, 14 Service Bus topics with ~16 subscriptions per partition, 13 storage containers, 8 federated credentials, 7 role assignments. Several recent bugs have been ordering and flag-shape issues that ARM would have rejected at submit time rather than failing mid-deploy (AKS mesh wait races, SSH access flag on the Automatic SKU, missing cert-auth flags).

Bicep inherits ARM's idempotency and parallel orchestration without a state file, so the reasons in ADR-003 against Terraform do not apply. Azure Verified Modules (AVM) provide Microsoft-maintained, versioned Bicep modules with best-practice defaults for the resources we use.

## Decision

Migrate Azure PaaS provisioning from imperative `az` CLI commands to Bicep templates, with a thin Python orchestrator retained for the seams Bicep does not cover.

The initial implementation uses raw Bicep resource declarations (under `infra/modules/`) rather than Azure Verified Modules. Raw Bicep was chosen for this pass because it removes an external dependency (MCR module downloads, version pinning maintenance) and eliminates compile-time surprises from AVM schema mismatches. Migration to AVM is an ongoing evaluation and can happen module-by-module; no decision is made to block on it.

**Moves to Bicep (in `infra/modules/`):**
- Managed Identity + federated credentials (`identity.bicep`)
- Key Vault (`keyvault.bicep`)
- Container Registry (`acr.bicep`)
- CosmosDB Gremlin account + database + graph (`cosmos-gremlin.bicep`)
- Per-partition CosmosDB SQL + Service Bus + Storage (`partition.bicep`)
- Common Storage account + blob containers + table service (`storage-common.bicep`)
- Scoped RBAC role assignments (`rbac.bicep`)

**Stays imperative in Python:**
- Resource group creation
- Soft-deleted Key Vault pre-check and `az keyvault recover` (ARM cannot branch on a live query)
- AKS Automatic + managed Istio setup (AVM AKS module maturity for the Automatic SKU + `az aks mesh enable-*` sequence needs validation; deferred)
- `az aks get-credentials` and `az k8s-configuration flux` (operational, not resources)
- Key Vault secret value writes (data-plane; Bicep owns the vault and RBAC, Python writes values from deployment outputs)
- Kubernetes bootstrap and Flux activation (unchanged)

AVM module versions are pinned explicitly in each Bicep file. Upgrades are manual and intentional; no floating refs.

## Consequences

- `src/spi/azure_infra.py` shrinks from ~1,012 LOC to ~200 to 300 LOC: a pre-check step, a Bicep deployment call, output parsing, and Key Vault secret value writes.
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
5. **AKS Automatic + managed Istio + Deployment Safeguards** -- deferred pending a spike. `sku.name='Automatic'`, `serviceMeshProfile`, and `safeguardsProfile` are all expressible in recent API versions (2024-09-02-preview+), but AKS Automatic silently drops properties it does not support, so a dedicated validation pass is required before migrating. If the spike confirms viability, this phase migrates in three PRs (cluster, safeguards, mesh). If not, AKS remains imperative indefinitely.

Phases 1-4 shipped together in commit `782649b`. Phase 5 is tracked separately; this ADR will be updated when a decision is reached.

A `spi up --dry-run` flag (added post-migration) runs `az deployment group what-if` against `infra/main.bicep`, giving reviewable ARM-level diffs before any resource provisioning.
