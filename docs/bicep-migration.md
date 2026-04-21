# Bicep Migration — Status & Next Steps

Working document for the Bicep / AVM infrastructure migration. Resume here if picking up work in a new session.

Last updated: 2026-04-21

## Current state

| Phase | Status | Where it lives |
|---|---|---|
| Phase 1 — PaaS to raw Bicep + `spi up --dry-run` | ✅ Shipped | Merged via PR #1 |
| Phase 2 Stage A — AKS-in-AVM spike | ✅ Complete, ✅ VIABLE | Branch `spike/aks-bicep-avm` (reference only) |
| Phase 2 Stage B1 — cluster via AVM | ✅ Shipped | Direct commit on `main` (solo workflow, no PR) |
| Phase 2 Stage B2 — tighten Istio config | ⏳ Not started | Revision pin + Cilium + Azure Monitor evaluation |
| Phase 2 Stage B3 — remove `_configure_safeguards` | ⏳ Not started | Delete function + amend ADR-012 |
| Phase 2 Stage C — other modules to AVM | 🚫 Dropped | See Stage A findings below |

## What's in each branch

- **`main`** — production. Has Phase 1 PaaS Bicep, `--dry-run`, and B1 (AKS via AVM).
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
- [ ] Live deploy validation: `uv run spi up --env ci1` and confirm `az aks show -g spi-stack-ci1 -n spi-stack-ci1 --query serviceMeshProfile.istio.components.proxyRedirectionMechanism -o tsv` returns `CNIChaining`. **Deferred to next session.**

`src/spi/azure_infra.py` went from 563 → 495 LOC (-68); the remaining reduction is in B3.

### B2 — tighten Istio config

- [ ] Pin `revisions: ['asm-1-28']` in `serviceMeshProfile.istio` (currently AVM picks AKS default)
- [ ] Evaluate adding `networkDataplane: 'cilium'` — Terraform repo uses it; verify compatibility with AKS-Istio add-on (the earlier Microsoft docs noted Cilium/Istio conflicts, but Terraform repo has both working; confirm before adopting)
- [ ] Consider whether Azure Monitor profile should be declared here (Terraform repo has `azure_monitor_profile.metrics.enabled: true`)

### B3 — remove `_configure_safeguards`

- [ ] Delete `_configure_safeguards` function and its call site in `azure_infra.py`.
- [ ] Add a short comment at the old call site explaining Automatic enforces safeguards via a non-bypassable ValidatingAdmissionPolicy.
- [ ] Amend `docs/decisions/012-bicep-avm-for-azure-paas.md` Migration section:
  - Change Stage 5 description to reflect B1 shipped
  - Note Stage C was dropped with rationale
  - Mark full migration as shipped

## Net impact

`src/spi/azure_infra.py` AKS-related code: ~190 LOC → ~60 LOC after B3 lands.

Overall `azure_infra.py` progression:
- Before Phase 1 (pure imperative): ~1,012 LOC
- After Phase 1 (PaaS to Bicep): 563 LOC
- After B1 (AKS to AVM): 495 LOC
- After B3 (drop `_configure_safeguards`): ~470 LOC (projected)

## Resumption commands

```bash
# Confirm B1 is on main
git log --oneline -5
uv run pytest tests/test_bicep_compile.py

# Live deploy validation (when ready to burn ~$5)
uv run spi up --env ci1
az aks show -g spi-stack-ci1 -n spi-stack-ci1 \
  --query serviceMeshProfile.istio.components.proxyRedirectionMechanism -o tsv
# expected: CNIChaining
uv run spi down --env ci1

# Latest AVM module versions (before any future AVM bump)
curl -s "https://mcr.microsoft.com/v2/bicep/avm/res/container-service/managed-cluster/tags/list" \
  | python3 -c "import json,sys; print('\n'.join(sorted(json.load(sys.stdin)['tags'], key=lambda s: [int(p) for p in s.split('.')])))"
```

## References

- ADR-012 (local): `docs/decisions/012-bicep-avm-for-azure-paas.md`
- Sister repo ADR on CNI chaining: `../osdu-spi-infra/docs/decisions/0004-istio-cni-chaining-for-sidecar-injection.md`
- Sister repo AKS config (Terraform): `../osdu-spi-infra/main/infra/aks.tf`
- Sister repo post-provision (safeguards + mesh orchestration): `../osdu-spi-infra/main/scripts/post-provision.ps1`
- Claude's private planning file (not checked in): `~/.claude/plans/ahh-sorry-i-misunderstood-twinkly-bengio.md`
