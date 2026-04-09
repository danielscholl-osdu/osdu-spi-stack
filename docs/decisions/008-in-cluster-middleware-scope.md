# ADR-008: In-Cluster Middleware Scope

**Status:** Accepted

## Context

While Azure PaaS replaces most middleware (ADR-001), three components remain in-cluster:

1. **Elasticsearch**: Azure Cognitive Search is not a drop-in replacement for the Elasticsearch APIs that OSDU search/indexer services use. The services call Elasticsearch REST APIs directly.

2. **Redis**: Azure Cache for Redis could work, but the OSDU services require TLS with custom CA certificates and specific Redis database isolation (DB 1-6 for different services). In-cluster Redis with cert-manager self-signed certificates provides this with minimal configuration.

3. **PostgreSQL**: Required only for Airflow metadata storage. Airflow's scheduler and workers need low-latency access to the metadata database. Azure Database for PostgreSQL would add network latency and cost for a single-database use case.

## Decision

Run Elasticsearch (ECK), Redis (Bitnami), and PostgreSQL (CNPG) in the `platform` namespace. These are the only stateful workloads managed by Kubernetes operators.

Airflow itself is also in-cluster because it orchestrates data ingestion workflows and needs direct access to the OSDU API endpoints within the cluster network.

## Consequences

- Three stateful systems still require in-cluster storage (Premium SSD StorageClasses).
- ECK and CNPG operators handle failover, backup, and upgrades for their respective databases.
- Redis TLS uses self-signed certificates from cert-manager; OSDU services import the CA via init containers.
- Total in-cluster persistent storage: ~420Gi (3x128Gi ES + 3x8Gi Redis + 3x14Gi PG).
