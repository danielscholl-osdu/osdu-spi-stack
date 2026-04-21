# Bicep Migration — Status & Next Steps

Working document for the Bicep / AVM infrastructure migration. Resume here if picking up work in a new session.

Last updated: 2026-04-21

## Current state

| Phase | Status | Where it lives |
|---|---|---|
| Phase 1 — PaaS to raw Bicep + `spi up --dry-run` | ✅ Shipped | Merged via PR #1 |
| Phase 2 Stage A — AKS-in-AVM spike | ✅ Complete, ✅ VIABLE | Branch `spike/aks-bicep-avm` (reference only) |
| Phase 2 Stage B1 — cluster via AVM | ✅ Shipped + live-validated | Direct commit on `main` (solo workflow, no PR) |
| Phase 2 Stage B2 — tighten Istio config | ⏳ Partial | Revision pin ✅ shipped; Cilium/Azure Monitor dropped (see note) |
| Phase 2 Stage B3 — remove `_configure_safeguards` | ✅ Shipped + live-validated | Direct commit on `main` |
| Phase 2 Stage C — other modules to AVM | 🚫 Dropped | See Stage A findings below |
| FIC concurrency (unplanned, surfaced by live deploy) | ✅ Shipped + live-validated | `@batchSize(1)` on identity.bicep FIC loop |
| AKS Azure-RBAC grant (unplanned, surfaced by live deploy) | ✅ Shipped + live-validated | `_grant_deployer_cluster_admin` + propagation wait in azure_infra.py |

## What's in each branch

- **`main`** — production. Has Phase 1 PaaS Bicep, `--dry-run`, B1 (AKS via AVM), B2 (Istio revision pin), B3 (_configure_safeguards removal), FIC concurrency fix, and the AKS Azure-RBAC cluster-admin grant.
- **`spike/aks-bicep-avm`** — kept as a historical reference to the working AKS-via-AVM template. Not active.

## Stage A findings (2026-04-21)

Real deploy to `spi-stack-spike` RG: **8m 44s to green, 3 iterations**. Spike RG deleted.

### ✅ Viable — AVM `container-service/managed-cluster:0.13.0` works for AKS Automatic

Required overrides since AVM treats `skuName: 'Automatic'` as a pass-through, not pre-configured:

```bicep
skuName: 'Automatic'
publicNetworkAccess: 'Enabled'                        // Karpenter needs public API
outboundType: 'managedNATGateway'                     // Automatic recommendation
managedIdentities: { systemAssigned: true }            // architectural shift: was user-assigned
enableKeyvaultSecretsProvider: true
enableSecretRotation: true
webApplicationRoutingEnabled: true
primaryAgentPoolProfiles: [{
  vmSize: 'Standard_D4lds_v5'                          // 150 GiB cache > 128 GiB ephemeral OS disk
  osDiskType: 'Ephemeral'
  availabilityZones: [1, 2, 3]                          // ints, not strings
}]
```

### ❌ Gaps that remain imperative post-deploy

| Feature | AVM state | Resolution |
|---|---|---|
| CNI chaining | `proxyRedirectionMechanism` typed OUT of `IstioComponents`. What-if accepts (passthrough), RP rejects with `UnmarshalError`. | `az aks mesh enable-istio-cni` post-deploy. Verified flips cluster to `CNIChaining`. |
| Safeguards | Not exposed. On Automatic, `safeguardsProfile: null` — enforced via non-bypassable `ValidatingAdmissionPolicy`. **Cannot be relaxed.** | **Remove** `_configure_safeguards` (`azure_infra.py:178-192`). It's a no-op on Automatic. |

### ⚠️ Lessons

- **What-if is not a deploy-time guarantee.** Bicep warnings matter. The `proxyRedirectionMechanism` issue warned at compile (BCP037), passed what-if, but failed at actual deploy.
- **AVM managed-cluster is a thin passthrough, not an AKS-Automatic expert.** Treat it as ARM-grade declarations with convenience shapes.
- **Terraform sister repo (`../osdu-spi-infra`) uses AVM only for managed-cluster.** KV, ACR, Storage, Cosmos, Service Bus all use raw `azurerm_*` providers. Strong signal that AVM-everywhere is over-engineering.

### Plan amendment: Stage C dropped

Original plan: migrate all 6 raw Bicep modules (KV, ACR, Storage, Cosmos, Service Bus, Managed Identity) to AVM.

**Revised: drop Stage C entirely.** AVM is AKS-only. Existing raw Bicep stays.

## Stage B — 3 commits

User-directed solo workflow: each stage ships as a direct commit on `main`, no PRs.

### B1 — cluster via AVM ✅ Shipped

- [x] Copied `infra/aks.bicep` from `spike/aks-bicep-avm` to `main`.
- [x] `src/spi/azure_infra.py`: replaced `create_aks_automatic` with a `run_bicep_deployment` call against `infra/aks.bicep`.
- [x] Deleted `get_aks_oidc_issuer` and `_aks_exists`; the Bicep outputs carry `oidcIssuerUrl`, `clusterResourceId`, and `clusterPrincipalId`.
- [x] Replaced `_ensure_istio_mesh` with a minimal `_ensure_istio_cni_chaining` (the AVM module already declares the mesh + external ingress gateway; only CNI chaining remains imperative).
- [x] Removed `clusterName` from `infra/main.bicep` and both `.bicepparam` files; AKS is a separate Bicep template now, so `main.bicep` no longer threads it through.
- [x] Updated `src/spi/azure_infra.py` module docstring.
- [x] `uv run pytest tests/test_bicep_compile.py` — 10/10 green (including `aks.bicep`).
- [x] Live deploy validation against `spi-stack-ci1` (2026-04-21): `proxyRedirectionMechanism: CNIChaining` confirmed, Istio `asm-1-28` active, `networkDataplane: cilium` (Automatic default), 3 Ready nodes. RG torn down.

`src/spi/azure_infra.py` went from 563 → 495 LOC (-68) for B1 itself; B3 drops another 24 LOC; the new RBAC grant adds ~76 LOC. End state: 547 LOC.

### B2 — tighten Istio config (partially shipped)

**Shipped:**
- [x] Pinned `revisions: ['asm-1-28']` in `infra/aks.bicep` `serviceMeshProfile.istio`. Matches sister Terraform repo and current AVM default; validated live against `spi-stack-ci1` (incremental deploy succeeded in 2m53s, no cluster disruption, `az aks show` confirms pinned revision).

**Dropped:**
- `networkDataplane: 'cilium'` — AKS Automatic already defaults to `networkPlugin: azure` + `networkPluginMode: overlay` + `networkDataplane: cilium` (verified on the live cluster). Setting them explicitly in Bicep would be declarative parity with the sister Terraform repo but zero behavior change; deferred as cosmetic.
- `azureMonitorProfile` + Log Analytics workspace — real new resources, materially out of scope for a "tighten Istio" PR. Track in a dedicated observability effort.

**Original checklist:**

- [ ] Pin `revisions: ['asm-1-28']` in `serviceMeshProfile.istio` (currently AVM picks AKS default)
- [ ] Evaluate adding `networkDataplane: 'cilium'` — Terraform repo uses it; verify compatibility with AKS-Istio add-on (the earlier Microsoft docs noted Cilium/Istio conflicts, but Terraform repo has both working; confirm before adopting)
- [ ] Consider whether Azure Monitor profile should be declared here (Terraform repo has `azure_monitor_profile.metrics.enabled: true`)

### B3 — remove `_configure_safeguards` ✅ Shipped

- [x] Deleted `_configure_safeguards` function and its call site in `azure_infra.py` (file 471 LOC after this step, down from 495).
- [x] Added a short comment at the old call site explaining Automatic enforces safeguards via a non-bypassable ValidatingAdmissionPolicy and that the local Helm chart is written to satisfy the policy.
- [x] Amended `docs/decisions/012-bicep-avm-for-azure-paas.md`:
  - Stage 5 description updated to reflect AVM-based AKS shipped
  - Added Deployment Safeguards rationale note
  - Added AVM adoption scope note (Stage C drop)
  - Updated "Stays imperative" and Consequences LOC numbers

## Unplanned fixes surfaced during live validation

The first `spi up --env ci1` run after B1/B3 exposed two issues the Bicep spike and compile tests could not catch.

### Federated credential concurrency (commit `d964329`)

ARM's Managed Identity RP rejects concurrent writes of federated credentials under the same UAMI (`ConcurrentFederatedIdentityCredentialsWritesForSingleManagedIdentity`). Bicep's default copy-loop schedules iterations in parallel, so most of the 8 FICs in `identity.bicep` failed on a fresh deploy.

Fix: `@batchSize(1)` on the `federatedCredentials` resource in `infra/modules/identity.bicep`. Adds ~1-2 minutes to first-run provisioning; re-deploys are no-ops.

### AKS Azure RBAC cluster-admin grant (commit `092a308`)

AKS Automatic enforces Azure RBAC for Kubernetes and disables local accounts. Before B1 this was the same, but the imperative `az aks create` path appears to have had an implicit grant (or the tenant auto-assigned a role) that the Bicep/SAMI path does not. Result: after the B1 deploy, the signed-in principal could not `kubectl create namespace`, failing K8s bootstrap.

Fix: new `_grant_deployer_cluster_admin` and `_wait_for_cluster_rbac` in `src/spi/azure_infra.py`. After `az aks get-credentials`, assign the signed-in principal `Azure Kubernetes Service RBAC Cluster Admin` on the cluster resource, then poll `kubectl auth can-i create namespace` until propagation lands (typically 2-3 minutes; capped at 5).

## Known issue (not introduced by this migration)

On `spi-stack-ci1`, Flux's platform layer stalled in reconciliation because Redis and PostgreSQL PVCs sat in `ExternalProvisioning` indefinitely, waiting for `disk.csi.azure.com` to provision disks. Pods stayed Pending. The cluster's CSI Azure Disk driver is installed but not creating volumes.

This is orthogonal to the Bicep migration -- the CSI driver, storage classes, and Flux workloads are all untouched by this work. Worth a separate investigation (likely storage-class / CSI workload-identity RBAC).

## Net impact

Overall `azure_infra.py` progression:
- Before Phase 1 (pure imperative): ~1,012 LOC
- After Phase 1 (PaaS to Bicep): 563 LOC
- After B1 (AKS to AVM): 495 LOC
- After B3 (drop `_configure_safeguards`): 471 LOC
- After RBAC cluster-admin grant (post-B1 fix): 547 LOC ✅

## Resumption commands

```bash
# Confirm migration state on main (expects B1/B2/B3 + FIC + RBAC grant commits)
git log --oneline -7
uv run pytest tests/test_bicep_compile.py

# Re-validate end-to-end after any AKS/Bicep change
uv run spi up --env ci1
az aks show -g spi-stack-ci1 -n spi-stack-ci1 \
  --query serviceMeshProfile.istio.components.proxyRedirectionMechanism -o tsv
# expected: CNIChaining
az aks show -g spi-stack-ci1 -n spi-stack-ci1 \
  --query "serviceMeshProfile.istio.revisions" -o tsv
# expected: asm-1-28
uv run spi down --env ci1

# Latest AVM module versions (before any future AVM bump)
curl -s "https://mcr.microsoft.com/v2/bicep/avm/res/container-service/managed-cluster/tags/list" \
  | python3 -c "import json,sys; print('\n'.join(sorted(json.load(sys.stdin)['tags'], key=lambda s: [int(p) for p in s.split('.')])))"
```

## Next up

- **CSI disk provisioning** — diagnose why `disk.csi.azure.com` leaves PVCs in `ExternalProvisioning`. Check storage class parameters, CSI driver pod logs, workload identity / RBAC for the CSI driver SA. Likely surfaces on any fresh cluster; not a Bicep migration concern, but blocks platform-layer reconciliation.
- **B2 follow-ups (optional)** — if cosmetic parity with sister Terraform repo is wanted later: add `networkDataplane: 'cilium'` + `networkPluginMode: 'overlay'` + `networkPlugin: 'azure'` explicitly in aks.bicep (zero behavior change, declarative intent only).
- **Observability** — separate effort to add Azure Monitor profile + Log Analytics workspace for Container Insights and managed Prometheus, modelled after `../osdu-spi-infra/main/infra/monitoring.tf`.

## References

- ADR-012 (local): `docs/decisions/012-bicep-avm-for-azure-paas.md`
- Sister repo ADR on CNI chaining: `../osdu-spi-infra/docs/decisions/0004-istio-cni-chaining-for-sidecar-injection.md`
- Sister repo AKS config (Terraform): `../osdu-spi-infra/main/infra/aks.tf`
- Sister repo post-provision (safeguards + mesh orchestration): `../osdu-spi-infra/main/scripts/post-provision.ps1`
- Claude's private planning file (not checked in): `~/.claude/plans/ahh-sorry-i-misunderstood-twinkly-bengio.md`
