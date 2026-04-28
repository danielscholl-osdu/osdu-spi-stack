# ADR-005: Workload Identity for Azure PaaS Access

**Status**: Accepted

## Context

OSDU services authenticate to Cosmos DB, Service Bus, Azure Storage, and Key Vault. The alternative is to store connection strings or service-principal credentials as Kubernetes Secrets; those leak easily, require rotation, and multiply the secret inventory.

AKS Automatic enables the OIDC issuer by default, which is the precondition for Azure Workload Identity: a ServiceAccount token is federated with a user-assigned managed identity (UAMI), and the pod exchanges it for an Entra ID access token at runtime.

## Decision

Use a single UAMI (`osdu-identity`) federated with one ServiceAccount (`workload-identity-sa` in the `osdu` namespace). All OSDU services run under that ServiceAccount.

- The UAMI is declared in `infra/modules/identity.bicep` and receives RBAC role assignments via `infra/modules/rbac.bicep`: Key Vault Secrets User, Storage Blob Data Contributor, Storage Table Data Contributor, Service Bus Data Sender, Service Bus Data Receiver, AcrPull.
- The ServiceAccount carries `azure.workload.identity/client-id` and `tenant-id` annotations.
- Pods opt in with the `azure.workload.identity/use: "true"` label; the AKS webhook projects the federated token file and injects `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_FEDERATED_TOKEN_FILE`.

Ingress mode `dns` provisions a second UAMI (`external-dns-identity`) scoped `DNS Zone Contributor` on the target zone's resource group (ADR-012).

Rejected: per-service UAMIs with least-privilege scoping. The role surface (the same six roles across every service) does not differentiate enough to justify the federation and RBAC volume at the SPI Stack's current scope.

## Consequences

- Zero stored credentials for Azure PaaS access. Tokens are short-lived and refreshed automatically.
- One identity, one set of RBAC bindings. Provisioning is deterministic and re-runs are idempotent.
- All OSDU services share the same access envelope; there is no per-service blast-radius containment at the Azure layer. Containment is at the Kubernetes RBAC and mesh layer instead.
- The schema-load Job (ADR-013) and any future workloads in the `osdu` namespace reuse this ServiceAccount without any new Azure-side provisioning.

## Carve-outs

- `${partition}-sb-connection` in Key Vault stores the Service Bus namespace's primary SAS connection string, not "DISABLED". The `indexer-queue-master` image (current `core-lib-azure` 2.0.6) builds its Service Bus subscription client via `SubscriptionClientFactoryImpl`, which constructs a `ConnectionStringBuilder` regardless of `AZURE_PAAS_WORKLOADIDENTITY_ISENABLED`. Without a real connection string the subscription client throws `IllegalConnectionStringFormatException` on every retry and records-changed events never reach the indexer. The matching `osdu-developer` reference takes the same approach. The secret remains in Key Vault gated by the same UAMI's `Key Vault Secrets User` role; no SAS key is mounted into a pod env var or written to disk. Revisit when the upstream subscription client honors the WI flag.
