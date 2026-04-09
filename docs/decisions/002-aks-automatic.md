# ADR-002: AKS Automatic for Compute

**Status:** Accepted

## Context

Standard AKS requires manual configuration of node pools, networking, service mesh, monitoring, and security policies. AKS Automatic bundles these as managed features with opinionated defaults.

The trade-off is reduced flexibility in exchange for reduced operational complexity.

## Decision

Use AKS Automatic (`--sku automatic`) which provides:

- **Karpenter**: Node Auto-Provisioning; no manual node pool sizing or scaling.
- **Managed Istio**: Service mesh with mTLS and ingress gateway.
- **Deployment Safeguards**: Non-bypassable admission policies enforcing pod security.
- **Key Vault CSI Driver**: Secret rotation and mounting.
- **Cilium CNI**: eBPF networking with overlay mode.
- **Managed Prometheus**: Metrics collection out of the box.
- **Container Insights**: Log collection to Log Analytics.

## Consequences

- All workloads must comply with Deployment Safeguards (non-root, seccomp, capability drop, resource limits, probes). The local Helm chart bakes compliance in.
- No manual node pool management; Karpenter handles right-sizing.
- Istio is managed; no need to install or upgrade it independently.
- Reduced blast radius for misconfigurations; Safeguards reject non-compliant pods at admission.
- Some upstream Helm charts may require postrender patches to comply with Safeguards.
- AKS Automatic is a newer SKU; some features may lag standard AKS.
