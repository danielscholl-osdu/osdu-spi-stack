# ADR-006: Three-Namespace Model

**Status:** Accepted

## Context

Workloads need isolation boundaries for security, resource management, and Istio sidecar injection configuration. A four-namespace model (foundation, istio-system, platform, osdu) is common, but with AKS Automatic managing Istio, the istio-system namespace is handled by Azure.

## Decision

Use three application namespaces:

| Namespace | Purpose | Istio Injection | Contents |
|-----------|---------|-----------------|----------|
| `foundation` | Cluster operators | No | ECK, CNPG, cert-manager |
| `platform` | Stateful middleware | Yes | Elasticsearch, Redis, PostgreSQL, Airflow |
| `osdu` | OSDU microservices | Yes | All OSDU services, osdu-config, workload-identity-sa |

The `flux-system` namespace is managed by the AKS GitOps extension and hosts all Flux resources (GitRepository, Kustomizations, HelmReleases).

The `aks-istio-ingress` namespace is managed by AKS and hosts the Istio ingress gateway.

## Consequences

- Clear ownership boundaries; operators never share a namespace with the workloads they manage.
- Istio injection is namespace-scoped; only `platform` and `osdu` get sidecars.
- Foundation pods (operators) run without sidecars, avoiding chicken-and-egg problems during operator startup.
- Resource quotas and network policies can be applied per namespace.
- Cross-namespace service access requires FQDN (e.g., `redis-master.platform.svc.cluster.local`).
