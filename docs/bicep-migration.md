# Bicep Migration — Status & Next Steps

Working document for the Bicep / AVM infrastructure migration. Resume here if picking up work in a new session.

Last updated: 2026-04-21

## Current state

| Phase | Status | Where it lives |
|---|---|---|
| Phase 1 — PaaS to raw Bicep + `spi up --dry-run` | ✅ Shipped | Branch `feat/bicep-dry-run`, PR #1 open against `main` (not merged) |
| Phase 2 Stage A — AKS-in-AVM spike | ✅ Complete, ✅ VIABLE | Branch `spike/aks-bicep-avm`, reference at `infra/aks.bicep` |
| Phase 2 Stage B — AKS migration to production | ⏳ Not started | 3 PRs planned (B1, B2, B3) |
| Phase 2 Stage C — other modules to AVM | 🚫 Dropped | See Stage A findings below |

## What's in each branch

- **`main`** — production. Does not yet have Bicep migration or dry-run.
- **`feat/bicep-dry-run`** — PR #1. Has the Phase 1 Bicep migration (PaaS via raw Bicep) plus `--dry-run` flag. Two commits ahead of `origin/main`.
- **`spike/aks-bicep-avm`** — one commit on top of `feat/bicep-dry-run`. Adds `infra/aks.bicep` as the working AKS-via-AVM reference. **Not intended to merge** — it's a reference artifact.

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

## Stage B — 3 PRs

Gated on PR #1 merging first. After that, these can go in order (each self-contained, revertible).

### PR B1 — cluster via AVM

- [ ] Merge PR #1 first
- [ ] Copy `infra/aks.bicep` from `spike/aks-bicep-avm` to a new branch off `main`
- [ ] Update `src/spi/azure_infra.py`:
  - [ ] Replace `create_aks_automatic` (lines 118-175) with a Bicep deploy call (`run_bicep_deployment` with the new template)
  - [ ] Add `get_aks_outputs` to read OIDC issuer URL from deployment outputs (instead of the separate `az aks show --query` call)
- [ ] Flip cluster identity from user-assigned to SAMI in the Bicep template
- [ ] Keep `identity.bicep` creating a SEPARATE user-assigned identity for workload identity federated credentials
- [ ] Update `src/spi/providers/azure.py`:
  - [ ] Orchestration becomes: RG → AKS Bicep → `get-credentials` → `enable-istio-cni` → main Bicep → post-deploy imperative
- [ ] Verify: deploy to `--env ci1`, confirm `az aks show` matches spike output, pods can be scheduled

### PR B2 — tighten Istio config

- [ ] Pin `revisions: ['asm-1-28']` in `serviceMeshProfile.istio` (currently AVM picks AKS default)
- [ ] Evaluate adding `networkDataplane: 'cilium'` — Terraform repo uses it; verify compatibility with AKS-Istio add-on (the earlier Microsoft docs noted Cilium/Istio conflicts, but Terraform repo has both working; confirm before adopting)
- [ ] Consider whether Azure Monitor profile should be declared here (Terraform repo has `azure_monitor_profile.metrics.enabled: true`)

### PR B3 — remove `_configure_safeguards`

- [ ] Delete `_configure_safeguards` function in `azure_infra.py:178-192`
- [ ] Delete the call site at `azure_infra.py:163`
- [ ] Add short comment at the call site explaining Automatic enforces safeguards
- [ ] Amend `docs/decisions/012-bicep-avm-for-azure-paas.md` Migration section:
  - Change Stage 5 description
  - Note Stage C was dropped with rationale
  - Mark full migration as shipped

## Net impact

`src/spi/azure_infra.py` AKS-related code: ~190 LOC → ~60 LOC.

Overall `azure_infra.py` after full migration: ~517 LOC → ~380 LOC.

## Resumption commands

```bash
# Find where we are
git log --oneline main ^origin/main       # unpushed local work on main (should be 2 commits)
git branch                                  # should show: main, feat/bicep-dry-run, spike/aks-bicep-avm

# Review spike work
git checkout spike/aks-bicep-avm
cat infra/aks.bicep                         # working AKS-via-AVM template

# Check PR #1 status
gh pr view 1

# Latest AVM module versions (sanity check before starting B1)
curl -s "https://mcr.microsoft.com/v2/bicep/avm/res/container-service/managed-cluster/tags/list" | jq -r '.tags | .[-5:]'

# Verify spike aks.bicep still compiles
git checkout spike/aks-bicep-avm
az bicep build --file infra/aks.bicep --stdout > /dev/null && echo "OK"

# Throwaway end-to-end test (costs ~$2)
az group create --name spi-stack-spike --location eastus2
az deployment group create -g spi-stack-spike --template-file infra/aks.bicep --parameters clusterName=spi-stack-spike
az aks mesh enable-istio-cni -g spi-stack-spike -n spi-stack-spike
az aks show -g spi-stack-spike -n spi-stack-spike --query serviceMeshProfile.istio.components.proxyRedirectionMechanism -o tsv
# expected: CNIChaining
az group delete --name spi-stack-spike --yes --no-wait
```

## References

- ADR-012 (local): `docs/decisions/012-bicep-avm-for-azure-paas.md`
- Sister repo ADR on CNI chaining: `../osdu-spi-infra/docs/decisions/0004-istio-cni-chaining-for-sidecar-injection.md`
- Sister repo AKS config (Terraform): `../osdu-spi-infra/main/infra/aks.tf`
- Sister repo post-provision (safeguards + mesh orchestration): `../osdu-spi-infra/main/scripts/post-provision.ps1`
- Claude's private planning file (not checked in): `~/.claude/plans/ahh-sorry-i-misunderstood-twinkly-bengio.md`
