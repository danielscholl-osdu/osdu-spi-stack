# ADR-011: Move Runtime Bootstrap into Flux-Managed Resources

**Status:** Proposed

## Context

After Flux takes over GitOps, four imperative steps must run before OSDU services
can start successfully. These are currently implemented in `src/spi/runtime_bootstrap.py`
and invoked from `providers/azure.py` as "Phase 6" of `spi up`. They mirror the
`null_resource + local-exec` blocks in the reference Terraform at
`osdu-spi-infra/main/software/spi-stack/osdu-common.tf`.

The four steps are:

1. **Redis CA cert copy.** Read `platform/redis-tls-secret`, write `osdu/redis-ca-cert`
   so the `osdu-spi-service` chart's `import-ca-certs` init container can add it to
   the Java truststore.
2. **Elasticsearch CA cert copy.** Read `platform/elasticsearch-es-http-certs-public`,
   write `osdu/elastic-ca-cert` for search and indexer truststores.
3. **Redis Istio DestinationRule.** Apply a static manifest that disables Istio mTLS
   for traffic to `redis-master.platform.svc.cluster.local`. Lettuce already speaks
   TLS to Redis end-to-end, and Istio's PERMISSIVE mTLS would otherwise wrap the
   connection in TLS-in-TLS, which the client cannot unwind.
4. **Key Vault bootstrap secrets.** Write six keys to Key Vault that OSDU services
   read at startup via `KeyVaultFacade`: `tbl-storage-endpoint`, `redis-hostname`,
   `redis-password`, `{partition}-elastic-endpoint`, `{partition}-elastic-username`,
   `{partition}-elastic-password`. The partition service hands the per-partition
   ES credentials to search and indexer at runtime.

### Why these exist at all

The unifying rationale is **make in-cluster middleware indistinguishable from
Azure PaaS to unmodified OSDU service code.** The Azure provider modules of OSDU
services were written assuming Azure Cache for Redis, Elastic Cloud, and Azure
Storage Tables, all reachable via Workload Identity and Key Vault. The SPI Stack
swaps the implementation (in-cluster Bitnami Redis, ECK Elasticsearch) but keeps
the interface (KV lookup) so the upstream service code is unmodified. Every
runtime-bootstrap step forges something the original Azure PaaS would have
provided for free: a trusted TLS chain, a clean transport, connection metadata
in the expected lookup path, and per-partition credential records that match the
partition-service contract.

### Why the current implementation is suboptimal

The Python implementation works, but it has structural problems:

- **Client-side state.** The CLI must stay open for the full duration of the
  post-handoff phase, currently up to 20 minutes of polling. If the user's
  laptop sleeps mid-deploy, the cluster ends up half-bootstrapped with no
  automatic recovery.
- **Not idempotent on middleware recreation.** If Redis or Elasticsearch get
  rebuilt later (operator update, PVC loss, manual delete), the CA secrets in
  the `osdu` namespace become stale. Nothing re-runs the copy.
- **Disaster recovery requires the CLI.** A fresh checkout plus `flux bootstrap`
  cannot reconstruct a working cluster. The Python CLI is a hidden dependency
  that lives outside the GitOps source of truth.
- **Polling loops instead of dependency ordering.** Flux already knows when
  middleware is Ready via `dependsOn` and Kustomization health checks. The
  Python code reimplements that as `for attempt in range(60)` with a 10-minute
  ceiling. Brittle and slow.
- **Observability split.** Failures appear in CLI scrollback rather than in
  `flux get kustomizations`, so they are invisible to the dashboard the rest
  of the stack uses.

The reference Terraform did it this way because `null_resource + local-exec`
is the path of least resistance in a Terraform world. The Python rewrite
inherited the shape rather than rethinking it.

## Decision

Move the runtime-bootstrap responsibilities from the CLI into Flux-managed
resources, in two phases that can ship independently.

### Pass 1: Static manifest moves into a Kustomization (cheap)

The Redis DestinationRule has zero runtime dependencies. It is a plain YAML
manifest and belongs in the GitOps tree.

- Add the DestinationRule manifest to `software/stacks/osdu/` (likely under
  `software/stacks/osdu/profiles/core/` so it sits with the other osdu-namespace
  resources).
- Wire it into the existing 7-layer Kustomization stack so it applies after the
  `osdu` namespace exists and before the OSDU service HelmReleases.
- Delete `apply_redis_destination_rule()` from `runtime_bootstrap.py` and the
  call site in `providers/azure.py`.

This shrinks the imperative tail with no new identity, no new image, and no
new RBAC. It is a free win and should land first.

### Pass 2: Cert copies and Key Vault writes move into a Flux-managed Job

The remaining three steps need a small Job that runs after middleware is Ready,
with credentials to read kube secrets and write to Key Vault.

#### New cluster resources

- **A bootstrap UAMI.** Provisioned by `azure_infra.py` alongside the existing
  OSDU workload identity. Granted `Key Vault Secrets Officer` on the deployment's
  Key Vault and nothing else.
- **A federated credential** binding the UAMI to a `bootstrap-sa` ServiceAccount
  in the `osdu` namespace.
- **A ConfigMap** (written once during the infra phase) carrying the values the
  job needs from infra: `KEYVAULT_NAME`, `STORAGE_ACCOUNT_NAME`, `DATA_PARTITION`,
  `ELASTIC_HOST`, `REDIS_HOST`. This replaces the Python variables that flow
  from `infra_outputs` today.

#### The job itself

A `Kustomization` under `software/stacks/osdu/` (probably a new
`software/stacks/osdu/bootstrap/` layer) containing:

- `ServiceAccount` with the workload-identity annotations
- `Role` and `RoleBinding` granting `get` on secrets in `platform` and
  `create/patch` on secrets in `osdu`
- A `Job` (or `CronJob` set to manual) that uses `mcr.microsoft.com/azure-cli`
  as its image and runs a small inline script:
  1. `kubectl get secret redis-tls-secret -n platform` and recreate it as
     `osdu/redis-ca-cert`
  2. `kubectl get secret elasticsearch-es-http-certs-public -n platform` and
     recreate it as `osdu/elastic-ca-cert`
  3. `kubectl get secret spi-secrets -n platform` to read the seed passwords
  4. `az keyvault secret set` for the six bootstrap keys
- The Kustomization declares `dependsOn: [redis, elasticsearch]` (the existing
  Flux Kustomizations for those middleware layers) and uses `healthChecks`
  pointing at the Redis StatefulSet and the Elasticsearch CR so it only runs
  once both are actually serving.

This deletes the polling loops entirely. Flux waits on real readiness signals
and runs the job exactly once per generation.

#### CLI changes

- Remove `runtime_bootstrap.py` and the Phase 6 call from `providers/azure.py`.
- The CLI's responsibility ends at "infra provisioned, Flux bootstrapped."
- `spi status` should learn to surface the bootstrap Job's state alongside the
  other Kustomizations so users still get a clear "what is happening" view.

## Consequences

### Wins

- Cluster state becomes fully reconstructable from the GitOps source. Fresh
  checkout plus `flux bootstrap` rebuilds a working cluster with no hidden CLI
  dependency.
- The CLI exits much sooner. No more 20-minute polling tails.
- Idempotent on middleware recreation. If ECK rotates the ES CA or Bitnami
  Redis is rebuilt, the Job re-runs automatically (or can be re-run with
  `flux reconcile`).
- All bootstrap state visible through `flux get kustomizations` and
  `kubectl get jobs -n osdu`. Same observability surface as the rest of the
  stack.
- Polling loops replaced by real readiness signals.

### Costs

- **More Azure infra coupling.** A new UAMI, federated credential, and KV role
  assignment must land during the infra phase. The Python `azure_infra.py`
  module grows.
- **A new image dependency.** `mcr.microsoft.com/azure-cli` (~600MB) becomes
  pinned, scanned, and updated as part of the stack. Small but real.
- **Templated infra-to-cluster handoff.** Values that are Python variables
  today must be templated into a ConfigMap during the infra phase, which is
  a new artifact and a new place where infra and cluster manifests touch.
- **Debugging shifts.** Failures land in `kubectl logs job/...` rather than
  in CLI scrollback. For experienced operators this is a wash; for first-time
  users the CLI's Rich panels gave more immediate context. The CLI should
  optionally watch the Job and surface its logs to soften this.
- **Two-phase secret problem partly remains.** The seed Redis password still
  originates in `secrets.py` before Flux runs and lands in `platform/spi-secrets`.
  The Job must read it from there, which means the Job's RBAC needs `get
  secrets` in `platform`.

### Out of scope

- Replacing the `KeyVaultFacade` lookups in OSDU service code with a
  ConfigMap-based lookup. That would let us eliminate the KV writes entirely
  but requires changes upstream in the OSDU services and is not on the table.
- A Reflector or kubernetes-replicator controller for the cert copies. That
  would also work, and arguably is the most idiomatic answer, but it adds a
  cluster-wide controller and a new operator to the stack just to handle two
  secrets. The Job approach is simpler for the current scope.
- Migrating to ExternalSecrets with a custom store provider for the KV writes.
  Same trade-off: more controllers, less imperative code. Worth revisiting if
  we ever add a fourth or fifth thing that needs to land in Key Vault at
  runtime.

## Implementation order

1. **Pass 1** (one PR): move the Redis DestinationRule into the Kustomization
   tree. Delete `apply_redis_destination_rule()`. Verify a fresh `spi up`
   produces the same end state.
2. **Pass 2a** (one PR): provision the bootstrap UAMI, federated credential,
   and KV role assignment in `azure_infra.py`. Write the infra-output
   ConfigMap. Do not yet remove the Python bootstrap; both paths coexist
   briefly so we can validate the new identity works.
3. **Pass 2b** (one PR): add the bootstrap Job Kustomization to
   `software/stacks/osdu/bootstrap/`. Verify the Job runs to completion on a
   fresh cluster and that the resulting cluster is functionally identical to
   the Python-bootstrapped version.
4. **Pass 2c** (one PR): delete `src/spi/runtime_bootstrap.py` and the Phase 6
   call from `providers/azure.py`. Update `spi status` to surface the
   bootstrap Job. Update `docs/architecture.md` and any references in the
   project README.

Each step is independently shippable and individually reversible.
