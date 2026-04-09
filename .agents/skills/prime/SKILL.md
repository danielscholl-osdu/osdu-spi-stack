---
name: prime
description: >-
  Build a lightweight understanding of the spi-stack codebase -- project structure,
  deployment model, architectural decisions, and available skills. Use this skill
  at the start of a session, when onboarding, when asking "what is this project?",
  "how does this work?", or "get me up to speed". Also use when context seems stale
  or you need to re-orient after a long conversation. Not for: deep code analysis,
  debugging, or implementation tasks.
triggers:
  - "what is this project"
  - "how does this work"
  - "get me up to speed"
  - "prime"
  - "orient"
  - "overview"
compatibility: Requires git. Works in any spi-stack checkout.
---

# Prime Codebase Understanding

Build a quick mental model of spi-stack so you can answer questions and navigate
the codebase confidently. The goal is orientation, not deep analysis -- stay under
20k tokens of context and produce a concise summary the user can scan in 30 seconds.

## What NOT to read

Source code (.py files), test files, individual K8s manifests, and agent/skill bodies
are off-limits during prime. Only list their existence. The reason: reading them bloats
context without adding orientation value. If deeper analysis is needed, the user will
ask for it separately.

## Phase 1: Project Overview

Read these three files (in parallel if possible). They are small and together give
the full picture of what this project is and how it works.

| File | What to extract |
|------|-----------------|
| `README.md` | Purpose, tech stack, CLI commands, deployment phases |
| `CLAUDE.md` | Project layout, conventions, key design decisions, skill table |
| `pyproject.toml` | Python version, dependencies, CLI entry point |

## Phase 2: Structure Map

Run `git ls-files` and summarize the directory tree. Present it as a compact table
showing each top-level directory, its purpose, and a file count.

Also run `git log --oneline -10` to capture recent activity. Include the last few
commit subjects in the summary so the user knows what's been changing. This is
especially useful for re-orientation after time away.

The important directories to highlight:

| Directory | Contains |
|-----------|----------|
| `src/spi/` | Python CLI (Typer + Rich + Pydantic) |
| `src/spi/providers/` | Provider module (Azure-only) |
| `software/charts/` | Local Helm chart (osdu-spi-service, Safeguards-compliant) |
| `software/components/` | In-cluster middleware K8s manifests (ES, Redis, PG, Airflow, etc.) |
| `software/stacks/osdu/` | OSDU service HelmReleases, Kustomization profiles, secrets |
| `docs/` | Architecture docs and ADRs |
| `.agents/skills/` | Portable agent skills |

Count files per directory -- do not list individual files.

## Phase 3: Architectural Decisions

List all ADR files under `docs/decisions/`. Present the full index with ADR number
and title (derived from filename) so the user knows what decisions have been made.
Do not read individual ADR files -- the index is sufficient for orientation.

Key ADRs to highlight:
- ADR-001: Azure PaaS for data services (CosmosDB, Service Bus, Storage)
- ADR-002: AKS Automatic with managed Istio and Deployment Safeguards
- ADR-003: CLI + GitOps hybrid (az CLI for infra, Flux for K8s)
- ADR-005: Workload Identity for all Azure PaaS access
- ADR-008: In-cluster only for ES, Redis, PG (Airflow metadata)

## Phase 4: Inventory

Collect these in parallel -- names only, no contents:

### Skills

```
.agents/skills/*/SKILL.md
```

List each skill name. These are the portable agent skills available in this repo.

### Agents

```
.claude/agents/*.md
```

List each agent name if any exist.

### Tests

```
tests/**/*.py
```

Report count only (e.g., "12 test files found"). If no test directory exists, say so.

### Deployment profiles

List the profile directories under `software/stacks/osdu/profiles/`. These map to
the `--profile` flag in the CLI.

## Phase 5: Summary

Present a single concise markdown summary with these sections:

- **Project** -- 1-2 sentence description
- **Tech** -- Python version, framework (Typer/Rich/Pydantic), package manager (uv), GitOps (Flux CD)
- **CLI** -- Key commands (check, up, down, status, info, reconcile)
- **Structure** -- Directory table from Phase 2
- **Decisions** -- ADR index from Phase 3
- **Profiles** -- Available deployment profiles
- **Skills** -- Available agent skills
- **Tests** -- Framework and count
- **Next steps** -- Suggest what to explore for deeper analysis (e.g., read a specific ADR, inspect a component, run `uv run spi check`)
