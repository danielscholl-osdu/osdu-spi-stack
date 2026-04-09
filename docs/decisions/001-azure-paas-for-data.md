# ADR-001: Azure PaaS for Data Services

**Status:** Accepted

## Context

OSDU services require persistent storage, messaging, and secret management. The CIMPL stack runs all middleware in-cluster (PostgreSQL, RabbitMQ, MinIO, Keycloak) for cloud-agnostic portability. The SPI stack targets Azure exclusively and can leverage managed services.

Running stateful middleware in-cluster requires significant operational overhead: backup strategies, upgrade paths, monitoring, and capacity planning. Azure PaaS services handle these concerns with SLAs.

## Decision

Use Azure PaaS for all data services that have managed equivalents:

| Data Need | In-Cluster (CIMPL) | Azure PaaS (SPI) |
|-----------|-------------------|-------------------|
| Document store | PostgreSQL | CosmosDB SQL |
| Graph store | PostgreSQL | CosmosDB Gremlin |
| Messaging | RabbitMQ | Service Bus |
| Object storage | MinIO | Azure Storage |
| Secrets | Kubernetes Secrets | Azure Key Vault |
| Authentication | Keycloak | Azure Entra ID |

Retain in-cluster components only where no managed equivalent exists or where latency requirements demand co-location: Elasticsearch (search/indexing), Redis (caching), PostgreSQL (Airflow metadata only).

## Consequences

- Eliminates operational burden for five stateful systems.
- Reduces in-cluster resource consumption; Karpenter provisions fewer nodes.
- Locks the stack to Azure; no multi-cloud portability.
- Requires Workload Identity and RBAC configuration for each PaaS resource.
- CLI must provision Azure resources before Kubernetes workloads can start.
