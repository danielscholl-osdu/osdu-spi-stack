# ADR-007: Layered Kustomization Ordering

**Status:** Accepted

## Context

Kubernetes workloads have hard dependencies on CRDs, operators, and other services. Deploying everything simultaneously causes failures: Elasticsearch CRDs do not exist until ECK is installed, Redis needs cert-manager TLS certificates, Airflow needs its PostgreSQL metadata database.

## Decision

Define seven Kustomization layers with explicit `dependsOn` relationships:

```
Layer 0: Namespaces
Layer 1: Operators + cert-manager + Gateway (4 parallel Kustomizations)
Layer 2: Middleware -- Elasticsearch, Redis, PostgreSQL (3 parallel, each depends on its operator)
Layer 3: Airflow (depends on PostgreSQL)
Layer 4: OSDU configuration (depends on Namespaces)
Layer 5: Core OSDU services (depends on Elasticsearch + Redis + config)
Layer 6: Reference services (depends on core services)
```

Layers within the same tier run in parallel when they have no mutual dependencies (e.g., ECK and CNPG operators install concurrently).

## Consequences

- Flux enforces correct ordering; Layer 5 will not start until Layer 2 middleware is healthy.
- CRD availability is guaranteed before custom resources are applied.
- Parallel deployment within tiers reduces total deployment time.
- Adding new middleware requires inserting a new Kustomization at the correct layer.
- `wait: true` on middleware layers ensures health before proceeding; this can slow deployment if a component is slow to initialize.
