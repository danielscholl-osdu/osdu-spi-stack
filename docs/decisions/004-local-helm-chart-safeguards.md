# ADR-004: Local Helm Chart for Safeguards Compliance

**Status:** Accepted

## Context

AKS Automatic enforces Deployment Safeguards via non-bypassable `ValidatingAdmissionPolicy`. Every pod must meet strict security requirements:

- `runAsNonRoot: true`
- `seccompProfile.type: RuntimeDefault`
- `capabilities.drop: [ALL]`
- `allowPrivilegeEscalation: false`
- Resource requests and limits defined
- Liveness and readiness probes defined

The OSDU community Helm charts (OCI registry) do not include these security contexts. Patching them at deploy time with kustomize postrender is fragile and error-prone.

## Decision

Maintain a single local Helm chart (`software/charts/osdu-spi-service/`) that bakes Safeguards compliance into its templates. All OSDU services use this chart via Flux HelmRelease with per-service values overrides.

The chart template includes:
- Pod-level: `runAsNonRoot`, `seccompProfile`, topology spread constraints
- Container-level: `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`, `runAsUser: 1000`
- Init containers for TLS CA import (Elasticsearch, Redis) with same security context
- Configurable probes, resources, env vars, volumes

## Consequences

- Compliance is guaranteed at authoring time; no runtime patching needed.
- One chart for all services; per-service differences are in HelmRelease values.
- Chart updates affect all services simultaneously (manageable, since the chart is simple).
- Init containers (CA cert import) also comply with Safeguards.
- Upstream OSDU chart changes do not affect deployments; only image tags change.
