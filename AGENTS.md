# OSDU SPI Stack -- Agent Context

Azure-native OSDU deployment using AKS Automatic + Azure PaaS + Flux CD GitOps.
Repository: `danielscholl-osdu/osdu-spi-stack`

## Project Layout

```
src/spi/                  Python CLI (Typer + Rich + Pydantic)
  cli.py                  Commands: check, up, down, status, info, reconcile
  config.py               Config model (Azure-only, Profile enum)
  checks.py               Tool prerequisites (az, bicep, kubectl, flux, helm)
  helpers.py              Command execution, Bicep deployment, kubectl helpers
  azure_infra.py          Thin orchestrator: RG + AKS imperative, PaaS via Bicep
  secrets.py              In-cluster secret generation (ES, Redis, PG)
  templates.py            YAML templates (GitRepository, Kustomization, ConfigMap)
  status.py               Deployment health dashboard
  info.py                 Endpoint discovery and credential display
  providers/azure.py      Orchestrates: infra -> bootstrap -> GitOps

infra/                    Bicep templates for Azure PaaS provisioning
  main.bicep              RG-scoped entrypoint; wires module deployments
  modules/                Per-concern modules (identity, kv, acr, cosmos-gremlin,
                          partition, storage-common, rbac)
  params/default.bicepparam  Default parameter values for manual deployment

software/
  charts/osdu-spi-service/ Local Helm chart (AKS Safeguards-compliant)
  components/              In-cluster middleware (Flux manifests)
    cert-manager/          TLS certificate management
    trust-manager/         Cross-namespace CA bundle distribution
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
uv run spi up --env dev1 --dry-run           # Preview Bicep changes (what-if)
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
- Azure PaaS provisioning declared in Bicep (`infra/`); RG + AKS + soft-delete
  recovery + post-deploy Key Vault writes remain imperative (ADR-012, supersedes
  the "use az CLI" portion of ADR-003 for PaaS resources)

## OSDU Service Provider Context

SPI Stack deploys the **Azure** provider of OSDU services. When exploring
cloned OSDU service repositories (e.g., `workspace/partition`, `workspace/indexer-service`),
each service contains multiple provider implementations under `provider/`:

```
provider/
  partition-aws/        # AWS-specific -- IGNORE
  partition-azure/      # Azure-specific -- THIS IS THE ONE SPI USES
  partition-gc/         # Google-specific -- IGNORE
  partition-ibm/        # IBM-specific -- IGNORE
```

**Only `*-azure/` provider code is relevant to this project.** Other providers
(`*-aws/`, `*-gc/`, `*-ibm/`, `*-core-plus/`) use different cloud services or
in-cluster middleware that is not part of the SPI Stack deployment model.

When investigating service behavior, configuration, or bugs:
1. Start with `*-azure/` provider directories
2. Fall back to `*-core/` (shared base logic) if the azure provider extends it
3. **Skip** `*-aws/`, `*-gc/`, `*-ibm/`, `*-core-plus/` directories entirely
4. The `<service>-core/` module contains shared interfaces and utilities
   that all providers use -- this is relevant when tracing shared behavior

This avoids wasting tokens reading non-Azure implementations that will never run
in an SPI Stack deployment.

## Agent Skills

This repo includes portable [Agent Skills](https://agentskills.io) in `.agents/skills/`.
They are auto-discovered by compatible tools (Claude Code, GitHub Copilot, Cursor, Gemini CLI,
pi, OpenCode, Goose, Junie, and 20+ others).

Skills are symlinked into `.claude/skills/` for Claude Code discovery. If the symlink is missing:
```bash
ln -sf ../.agents/skills .claude/skills
```

| Skill | Purpose |
|-------|---------|
| `prime` | Lightweight codebase overview -- structure, tech stack, and available commands |
| `setup` | Check prerequisites and install CLI tool dependencies (az, kubectl, flux, helm, uv) |
| `clone` | Clone OSDU GitLab repositories with optional worktree layout |
| `osdu-api` | OSDU platform API access via Istio gateway and Azure Entra ID |
| `osdu-gitlab` | GitLab operations -- glab guardrails, MR/pipeline monitoring, contributor analysis |
| `osdu-mr` | MR lifecycle -- code review with pipeline diagnostics, trusted branch sync |
| `osdu-test` | Run Java integration tests against a live SPI Stack environment |
| `deps` | Dependency analysis, vulnerability scanning, and risk-prioritized remediation |
| `ship` | Ship code changes to GitLab -- commit, push, and create merge requests |

For prerequisite diagnostics, tool installation, and authentication setup, use the `setup` skill.

## OSDU Service Images

Services use Azure SPI images from the OSDU community registry:
- Pattern: `community.opengroup.org:5555/osdu/platform/.../service-azure:tag`
- Image tags are pinned to full 40-char Git SHAs in HelmRelease manifests.
- To update an image, change the tag in the corresponding service YAML under `software/stacks/osdu/services/`.

## Deployment Workflow

1. `spi check` -- verify az, bicep, kubectl, flux, helm installed
2. `spi up --env dev1` -- provisions Azure infra (~15 min), bootstraps K8s, activates GitOps
   - RG + AKS via `az` CLI
   - Identity + KV + ACR + CosmosDB + Service Bus + Storage + RBAC via
     a single `az deployment group create` against `infra/main.bicep`
3. `spi status --watch` -- monitor Flux reconciliation progress
4. Wait for all Kustomizations and HelmReleases to become Ready
5. `spi info` -- get gateway IP and API endpoints
6. `spi down --env dev1` -- cleanup (deletes resource group)
