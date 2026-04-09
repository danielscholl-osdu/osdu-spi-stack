# ADR-005: Workload Identity for Azure PaaS Access

**Status:** Accepted

## Context

OSDU services need to authenticate to Azure PaaS resources (CosmosDB, Service Bus, Storage, Key Vault). Traditional approaches use connection strings or service principal credentials stored as Kubernetes secrets. These require rotation, risk exposure, and complicate secret management.

Azure Workload Identity enables pods to authenticate using projected service account tokens exchanged for Azure AD tokens, eliminating stored secrets entirely.

## Decision

Use a single user-assigned managed identity (`osdu-identity`) shared by all OSDU services, with:

1. **Federated credentials** linking eight Kubernetes namespace service accounts to the identity.
2. **Azure RBAC** role assignments granting the identity access to each PaaS resource.
3. **ServiceAccount annotations** (`azure.workload.identity/client-id`, `tenant-id`) on `workload-identity-sa` in each namespace.
4. **Pod labels** (`azure.workload.identity/use: "true"`) enabling token projection.

No service principal passwords, no connection strings in secrets, no rotation needed.

## Consequences

- Zero stored credentials for Azure PaaS access; tokens are short-lived and auto-refreshed.
- Single identity simplifies RBAC management (one set of role assignments).
- All services share the same access level; no per-service least-privilege boundaries.
- Federated credentials must be created for each namespace that runs OSDU services.
- Requires AKS OIDC issuer (enabled by default on AKS Automatic).
