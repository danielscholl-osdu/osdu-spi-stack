---
status: "proposed"
contact: "Daniel Scholl"
date: "2026-04-23"
deciders: "Daniel Scholl"
---

# ADR-013: Load OSDU Schemas via a Flux-Managed Kubernetes Job

## Context and Problem Statement

After Flux reconciles the core OSDU services, the schema-service Pod is
healthy but its CosmosDB container holds zero schema definitions. Any
downstream call that binds a record to a `kind` fails with
`schema not found`. The platform needs an automated step that POSTs the
~1,386 shared schemas published by the OSDU community so the cluster is
usable out of the box.

## Decision Drivers

- ADR-011 established that runtime bootstrap belongs inside Flux, not in
  a CLI imperative tail. Schema loading is the natural next step.
- The existing `osdu-spi-service` Helm chart is service-only and
  Safeguards-compliant (ADR-004). It must not grow init jobs.
- The cluster already federates `spi-stack-test-osdu-identity` with
  `system:serviceaccount:osdu:workload-identity-sa` (see
  `infra/modules/identity.bicep`). Reusing that identity avoids a new
  Bicep deployment.
- Schemas drift across releases. The loader must be upgradable the same
  way service images are, by re-running
  `scripts/resolve-image-tags.py --update`.

## Considered Options

- **Flux-managed Job with the OSDU community `schema-service-schema-load`
  image** (adapted from the osdu-developer project).
- **A long-running Deployment that sleeps after loading** (the
  cimpl-stack pattern with `core-plus-schema-deploy`).
- **A Terraform `null_resource + local-exec` that applies a synthesized
  Job** (the osdu-spi-infra pattern).
- **A home-grown Python loader that globs schemas from a Git archive at
  runtime.**

## Decision Outcome

Chosen option: **Flux-managed Job with the community loader image**,
because it matches the ADR-011 philosophy (GitOps-first, no CLI tail),
reuses the existing `workload-identity-sa`, and piggybacks on the
community CI that already ships a `schema-service-schema-load-master`
image at the same SHA as `schema-service-master`. The loader performs
pure POST of JSON schemas over the public schema-service API, so pairing
it with the current service tag is low risk.

### Shape

- New Kustomization `spi-osdu-schema-load` at `software/stacks/osdu/schema-load/`,
  inserted between Layer 5 (`spi-osdu-services`) and Layer 6
  (`spi-osdu-reference`) in `software/stacks/osdu/profiles/core/stack.yaml`.
- A single `Job` in the `osdu` namespace, reusing `workload-identity-sa`.
- A `ConfigMap` that mounts `Token.py` and `bootstrap.sh` into the
  loader image at the paths its default entrypoint expects
  (`/home/osdu/deployments/scripts/azure/`).
- The Flux Kustomization declares `dependsOn: spi-osdu-services` and a
  `healthChecks` entry so the Job's Complete condition is the readiness
  signal surfaced by `spi status`.

### Image pin

- Repository: `community.opengroup.org:5555/osdu/platform/system/schema-service/schema-service-schema-load-master`
- Tag: the same SHA that `software/stacks/osdu/services/schema.yaml`
  pins for the service. The community build pipeline publishes both
  tags from the same commit, so the resolver advances them together.
- `scripts/resolve-image-tags.py` gains a `schema-load` entry under
  project id 26 (same as `schema`) and writes the tag into
  `software/stacks/osdu/schema-load/job.yaml` on `--update` runs.

### Auth

The MSAL token exchange uses scope `https://management.azure.com/.default`,
verbatim from the osdu-developer `Token.py`. Live-cluster verification on
`spi-stack-test` confirmed that:

1. The federated token at `$AZURE_FEDERATED_TOKEN_FILE` exchanges
   successfully against AAD for an access token whose `appid` matches
   the OSDU UAMI's client_id.
2. The schema-service accepts that token on `GET /schema` (auth passes;
   401 becomes 500 on the cosmos backend, unrelated to auth).
3. There is no Istio sidecar in the `osdu` namespace and no
   `PeerAuthentication` CR, so the bearer token does not need to clear
   any mesh-level filter.

Using `api://${AAD_CLIENT_ID}/.default` was considered but rejected:
UAMI client_ids are not registered as API resources, so `az account
get-access-token --resource <uami-client-id>` fails. The management.azure.com
scope is always resolvable and the service validates by `appid`, not
audience.

### Idempotency

The community `DeploySharedSchemas.py` script internally tries POST and
falls back to PUT for development-stage schemas. PUBLISHED-stage schemas
on conflict are logged and skipped. `bootstrap.sh` post-processes the
script's exit code: if the only failures are "already exists" entries,
exit 0 so Flux marks the Job Ready.

Manual re-run lever:

```
kubectl delete job schema-load -n osdu
flux reconcile kustomization spi-osdu-schema-load --with-source
```

### Consequences

- Good, because a fresh checkout plus `flux bootstrap` reproduces a
  fully populated schema-service with no CLI post-steps.
- Good, because the loader upgrades in lockstep with the service via
  `scripts/resolve-image-tags.py --update`.
- Good, because no new Azure identity, federated credential, RBAC role
  assignment, or Bicep change is required.
- Good, because the Job is idempotent against re-runs and surfaces its
  state through the same Flux Kustomization table as every other layer.
- Bad, because the pinned loader tag depends on OSDU community GitLab
  registry retention. A follow-on PR should mirror the image to our own
  ACR (already provisioned at `infra/modules/acr.bicep`) to remove that
  external dependency.
- Bad, because schema loading covers only the schema-service. Reference
  data (units, CRS, legal tags, master data) and entitlements root
  groups remain manual or follow-on work.
