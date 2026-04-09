# OSDU SPI Stack -- Agent Context

Azure-native OSDU deployment using AKS Automatic + Azure PaaS + Flux CD GitOps.
Repository: `danielscholl-osdu/osdu-spi-stack`

## Project Layout

```
src/spi/                  Python CLI (Typer + Rich + Pydantic)
  cli.py                  Commands: check, up, down, status, info, reconcile
  config.py               Config model (Azure-only, Profile enum)
  checks.py               Tool prerequisites (az, kubectl, flux, helm)
  helpers.py              Command execution, display, kubectl helpers
  azure_infra.py          Azure PaaS provisioning via az CLI
  secrets.py              In-cluster secret generation (ES, Redis, PG)
  templates.py            YAML templates (GitRepository, Kustomization, ConfigMap)
  status.py               Deployment health dashboard
  info.py                 Endpoint discovery and credential display
  providers/azure.py      Orchestrates: infra -> bootstrap -> GitOps

software/
  charts/osdu-spi-service/ Local Helm chart (AKS Safeguards-compliant)
  components/              In-cluster middleware (Flux manifests)
    cert-manager/          TLS certificate management
    operators/eck/         Elasticsearch operator
    operators/cnpg/        PostgreSQL operator
    elasticsearch/         3-node ES cluster
    redis/                 Bitnami Redis with TLS
    postgres/              CNPG cluster (Airflow metadata)
    airflow/               Workflow orchestration
    gateway/               Istio Gateway API
  stacks/osdu/
    profiles/core/         7-layer Kustomization stack
    services/              10 core OSDU service HelmReleases
    services-reference/    3 reference service HelmReleases
    secrets/               ConfigMap placeholder docs

docs/
  architecture.md          System architecture document
  decisions/               10 ADRs
  diagrams/                Excalidraw architecture diagram
```

## CLI Reference

```bash
uv run spi check                            # Validate prerequisites
uv run spi up --env dev1                     # Deploy everything
uv run spi up --env dev1 --profile full      # Deploy with all services
uv run spi up --env dev1 --partition p1 --partition p2  # Multi-partition
uv run spi down --env dev1                   # Delete all Azure resources
uv run spi status                            # Health dashboard
uv run spi status --watch                    # Continuous refresh
uv run spi info                              # Show endpoints
uv run spi info --show-secrets               # Include credentials
uv run spi reconcile                         # Force Flux reconcile
uv run spi reconcile --suspend               # Freeze GitOps
uv run spi reconcile --resume                # Unfreeze GitOps
```

## Writing Conventions

- No em dashes; use commas, periods, or semicolons.
- Every az/kubectl command displayed transparently via Rich panels.
- Azure resource names derived from --env flag for isolation.

## Key Design Decisions

- Azure-only (no KinD/AWS/GCP); SPI services depend on Azure PaaS (ADR-001)
- AKS Automatic with managed Istio and Deployment Safeguards (ADR-002)
- CLI (az commands) for infra + Flux GitOps for K8s workloads (ADR-003)
- Local Helm chart bakes Safeguards compliance into templates (ADR-004)
- Workload Identity for all Azure PaaS access; no stored credentials (ADR-005)
- Three namespaces: foundation, platform, osdu (ADR-006)
- 7-layer Kustomization ordering with explicit dependsOn (ADR-007)
- In-cluster only for ES, Redis, PG (Airflow); everything else is Azure PaaS (ADR-008)

## OSDU Service Images

Services use Azure SPI images from the OSDU community registry:
- Pattern: `community.opengroup.org:5555/osdu/platform/.../service-azure:tag`
- Image tags are pinned to full 40-char Git SHAs in HelmRelease manifests.
- To update an image, change the tag in the corresponding service YAML under `software/stacks/osdu/services/`.

## Deployment Workflow

1. `spi check` -- verify az, kubectl, flux, helm installed
2. `spi up --env dev1` -- provisions Azure infra (~15 min), bootstraps K8s, activates GitOps
3. `spi status --watch` -- monitor Flux reconciliation progress
4. Wait for all Kustomizations and HelmReleases to become Ready
5. `spi info` -- get gateway IP and API endpoints
6. `spi down --env dev1` -- cleanup (deletes resource group)
