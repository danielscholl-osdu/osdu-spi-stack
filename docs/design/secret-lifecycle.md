# Secret Lifecycle

**What this explains.** The three classes of credentials in SPI Stack, which store owns each one, who writes them and when, and how trust-manager mirrors the in-cluster CA material from `platform` into `osdu`.

**Why it matters.** Three stores sound like complexity but they exist because three sets of credentials have three different threat models. Mixing them is how PaaS connection strings end up as Kubernetes Secrets, which defeats the point of Workload Identity. This doc maps each credential to its store so you can answer "where does this live, who wrote it, and when can I rotate it."

> **Companion docs.** [Workload Identity](workload-identity.md) covers how PaaS credentials become bearer tokens at runtime. [Bicep architecture](bicep-architecture.md) covers the modules that declare KV secrets.

## Three credential classes, three stores

| Class | Examples | Store | Access path |
|---|---|---|---|
| Azure PaaS credentials | Cosmos DB, Service Bus, Storage, Key Vault | Entra ID (token broker) | Workload Identity; no stored material |
| PaaS metadata + secret values | Cosmos endpoints, Storage account names, Service Bus namespace, tenant ID | Azure Key Vault | SDK reads via Workload Identity (or CSI) |
| In-cluster middleware passwords | Redis, Elasticsearch, PostgreSQL (Airflow) | Kubernetes Secrets in `platform` / `osdu` | Operator-issued, fanned out per service |

This split is the decision in [ADR-010](../decisions/010-keyvault-secret-management.md). The next sections walk each class.

## Class 1: Azure PaaS credentials (Workload Identity)

There are no Class 1 secrets. The OSDU services authenticate to Cosmos, Service Bus, Storage, and Key Vault using AAD bearer tokens minted via Workload Identity (see [workload-identity](workload-identity.md)). Tokens are short-lived, refreshed automatically by the Azure SDK, and never written to disk.

The one carve-out is `{partition}-sb-connection` for indexer-queue, which holds a real Service Bus SAS connection string because the current `core-lib-azure` `SubscriptionClientFactoryImpl` does not honor the Workload Identity flag. The value lives in Key Vault and is gated by the same UAMI's `Key Vault Secrets User` role; it never lands in a pod env var. See [ADR-005](../decisions/005-workload-identity.md) Consequences for the full rationale.

## Class 2: Key Vault secrets

Two writers contribute to Key Vault:

### Writer A: Bicep (deploy time)

Most KV secrets are declared in Bicep modules, where the source value is Azure itself. `infra/modules/keyvault.bicep` and `infra/modules/partition.bicep` write the bulk of them at `az deployment group create` time.

| Secret pattern | Source | Module |
|---|---|---|
| `entra-tenant-id`, `subscription-id` | Bicep parameter | `keyvault.bicep` |
| `gremlin-endpoint`, `gremlin-primary-key` | `listKeys()` on Cosmos | `cosmos-gremlin.bicep` |
| `{p}-cosmos-endpoint`, `{p}-storage-account-blob-endpoint` | Resource `.properties` | `partition.bicep` |
| `{p}-cosmos-connection`, `{p}-storage-account-key`, `{p}-sb-connection` | `"DISABLED"` placeholder by default, or real SAS for indexer-queue carve-out | `partition.bicep` |
| `acr-endpoint`, `keyvault-uri` | Resource `.properties` | `keyvault.bicep` |

Bicep writes are atomic with the rest of the deploy: the KV secret either lands with the resource or the whole deploy fails. ARM is idempotent on secret writes (a re-deploy with the same value is a no-op).

### Writer B: the CLI (post-handoff)

A small set of values originates in-cluster and is only knowable after Flux brings middleware to `Ready`:

| Secret | Source | Why post-handoff |
|---|---|---|
| `{p}-elastic-endpoint`, `{p}-elastic-username`, `{p}-elastic-password` | ECK-issued credentials in `platform`-namespace Secrets | ECK generates these when the Elasticsearch CR reaches Ready |
| `redis-hostname`, `redis-password` | Bitnami chart-generated | Helm renders the password during install |
| `tbl-storage-endpoint` | Derived from the common Storage account | Easier to compose in Python than in Bicep template syntax |

The CLI waits up to a few minutes for the relevant K8s Secrets to appear, reads them with `kubectl get secret -o jsonpath`, and writes their values to KV with `az keyvault secret set`. This is Phase 1 step 11 in [deployment-lifecycle](deployment-lifecycle.md).

Re-running `spi up` against a live cluster re-runs the post-handoff writes idempotently; KV is fine with rewrites of the same value.

### Reader: the services

Services read their KV secrets via the Azure SDK using Workload Identity. The OSDU `partition-azure` provider auto-prefixes the partition id onto every `sensitive: true` value at read time, so the partition record's `partition.json` template holds **bare** suffixes (`cosmos-endpoint`, not `opendes-cosmos-endpoint`). The ADR-015 amendment that originally got this wrong is now folded into the ADR body; the chart template uses bare values.

## Class 3: In-cluster middleware passwords

Three middleware systems, each with its own credential mechanism:

- **Elasticsearch.** ECK issues per-user credentials. The CLI never generates these. ECK exposes them as Secrets in `platform`; the CLI mirrors them into Key Vault (Writer B above) so services that need ES credentials read them through the same Workload Identity path as everything else.
- **Redis.** The Bitnami Helm chart generates the master password during install. The chart exposes it as `redis-master-password` Secret in `platform`; the CLI mirrors `redis-password` and `redis-hostname` into Key Vault.
- **PostgreSQL (Airflow).** CNPG generates per-cluster credentials and exposes them as Secrets in `platform`. Airflow reads them directly via the CNPG-issued ServiceAccount; no Key Vault round-trip.

The CLI does not generate these passwords. The operators do, deterministically per environment.

## CA distribution via trust-manager

A separate concern. Redis and Elasticsearch terminate TLS with self-signed CAs:

- Redis: cert-manager-issued, CA Secret in `platform`.
- Elasticsearch: ECK-managed CA, Secret in `platform`.

OSDU services need both CAs in `osdu` so the local Helm chart's `import-ca-certs` init container can fold them into the Java truststore. Kubernetes Secrets do not cross namespaces.

The SPI Stack runs **trust-manager** in `foundation`. `software/stacks/osdu/bootstrap/ca-bundles.yaml` declares two `Bundle` CRs that source from the platform-namespace CA Secrets and target Secret outputs in the `osdu` namespace (`redis-ca-cert`, `elastic-ca-cert`). trust-manager watches the sources and re-syncs the targets continuously, so a cert-manager renewal or an ECK CA rotation refreshes the truststore-input Secrets without any imperative step. See [ADR-011](../decisions/011-trust-manager-ca-distribution.md).

trust-manager is locked down: `secretTargets.authorizedSecrets` is pinned to the two names above and its default-CAs package is disabled.

The same Kustomization (`spi-bootstrap`, Layer 4b) also applies a static Istio `DestinationRule` (`redis-disable-mtls`) that turns off Istio mTLS to the in-cluster Redis master. Lettuce already speaks TLS directly to Redis, and Istio's automatic mTLS wraps that connection in a second TLS layer Lettuce cannot unwind.

## Worked example: rotating the Redis master password

The Redis password is Bitnami chart-generated and mirrored into Key Vault. Rotating it has two ends to keep in sync.

1. **Delete the existing Secret** so the chart re-renders it on next reconcile.
   ```bash
   kubectl delete secret redis-master-password -n platform
   flux reconcile helmrelease redis -n platform
   ```
   The HelmRelease re-renders the Secret with a new password. Redis restarts to pick up the new password.
2. **Re-run the CLI's runtime KV writes** so KV picks up the new value.
   ```bash
   uv run spi reconcile --refresh-images   # closest existing command; also re-runs runtime secrets
   ```
   (or invoke just the relevant function directly if you prefer)
3. **Roll the consumers.** `kubectl rollout restart deploy -n osdu`. Each service re-reads its credentials from KV at start.

Three steps, atomic per system. The same shape works for Elasticsearch credentials.

## Worked example: trace where `cosmos-endpoint` for partition `opendes` lives

```bash
# In Bicep (declared):
$ grep -r 'cosmos-endpoint' infra/modules/partition.bicep

# In Key Vault (the actual secret, prefixed by partition-azure):
$ az keyvault secret show --vault-name <kv> --name opendes-cosmos-endpoint --query value -o tsv

# In the partition record (bare suffix, partition-azure prefixes at read time):
$ kubectl exec -n osdu deploy/partition -- \
    curl -s -H "Authorization: Bearer <token>" \
    -H "data-partition-id: opendes" \
    http://localhost:8080/api/partition/v1/partitions/opendes | jq '.properties["cosmos-endpoint"]'
{
  "value": "cosmos-endpoint",
  "sensitive": true
}

# What the service actually resolves at runtime (after partition-azure prefixes):
# → KV secret name "opendes-cosmos-endpoint", value resolved via Workload Identity.
```

The fact that the partition record value is the bare suffix and the KV secret name is the prefixed form is the bare-vs-prefixed nuance from ADR-015.

## Related ADRs

- [ADR-005](../decisions/005-workload-identity.md) -- Workload Identity for Azure PaaS Access
- [ADR-010](../decisions/010-keyvault-secret-management.md) -- Key Vault + ConfigMap Secret Model
- [ADR-011](../decisions/011-trust-manager-ca-distribution.md) -- Cross-Namespace CA Distribution via trust-manager
- [ADR-015](../decisions/015-partition-entitlements-bootstrap.md) -- Partition + Entitlements Bootstrap (bare KV suffix in partition records)

## Source files

- `infra/modules/keyvault.bicep` -- KV resource + static secrets
- `infra/modules/partition.bicep` -- per-partition secrets
- `src/spi/secrets.py` -- post-handoff KV writes
- `src/spi/bootstrap.py` -- `osdu-config` and ServiceAccount bootstrap
- `software/stacks/osdu/bootstrap/ca-bundles.yaml` -- trust-manager Bundles + Redis DestinationRule
- `software/charts/osdu-spi-service/templates/init-containers.yaml` -- `import-ca-certs` init container
- `software/charts/osdu-spi-init/templates/partition-record.yaml` -- the bare-suffix template
