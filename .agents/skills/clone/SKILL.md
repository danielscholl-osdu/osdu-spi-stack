---
name: clone
description: >-
  Clone OSDU GitLab repositories to the workspace. Supports single service,
  category, or all repos with bare-clone worktree or standard git clone.
  Use when the user asks to clone an OSDU repo, set up the workspace, download
  source code for a service, or clone driver libraries.
  Not for: building or testing cloned repos, or checking repo status.
triggers:
  - "clone"
  - "download repo"
  - "get source code"
  - "clone service"
  - "set up workspace"
compatibility: "Requires Python 3.11+ and uv. Optional: wt or git-wt for worktree layout."
---

# OSDU Clone

Clone OSDU platform repositories into the local workspace.

## Step 1: Resolve the clone target

Parse the user's request to determine which repos to clone.

### Valid targets

| Target | What it clones |
|--------|----------------|
| `partition` | Single repo by name |
| `os-core-common` | Single repo by name |
| `os-oqm` | Single driver repo by name |
| `core` | All repos in the core category |
| `libraries` | All repos in the libraries category |
| `drivers` | All repos in the drivers category |
| `service:partition` | Explicit single repo |
| `category:core` | Explicit category |
| `all` | Everything |

### Categories

Categories align with the SPI Stack service layers.

| Category | Repos |
|----------|-------|
| libraries | os-core-common, os-core-lib-azure |
| drivers | os-obm, os-obm-python, os-sd, os-oqm, apd |
| core | partition, entitlements, legal, schema-service, storage, file, indexer-service, search-service, ingestion-workflow |
| reference | crs-catalog-service, crs-conversion-service, unit-service |

Repo names take precedence over category names. Map common aliases:
- "common library" -> `os-core-common`
- "azure library" -> `os-core-lib-azure`
- "search" -> `search-service`
- "indexer" -> `indexer-service`
- "schema" -> `schema-service`
- "workflow" -> `ingestion-workflow`
- "unit" -> `unit-service`
- "crs-catalog" -> `crs-catalog-service`
- "crs-conversion" -> `crs-conversion-service`
- "blob manager" / "obm" -> `os-obm`
- "queue manager" / "oqm" -> `os-oqm`
- "secret driver" / "sd" -> `os-sd`

## Step 2: Construct the clone URL

Base: `https://community.opengroup.org`

### System services

| Repo | GitLab path |
|------|-------------|
| partition | `osdu/platform/system/partition` |
| schema-service | `osdu/platform/system/schema-service` |
| storage | `osdu/platform/system/storage` |
| file | `osdu/platform/system/file` |
| indexer-service | `osdu/platform/system/indexer-service` |
| search-service | `osdu/platform/system/search-service` |

### Security and compliance services

| Repo | GitLab path |
|------|-------------|
| entitlements | `osdu/platform/security-and-compliance/entitlements` |
| legal | `osdu/platform/security-and-compliance/legal` |

### Reference services

| Repo | GitLab path |
|------|-------------|
| crs-catalog-service | `osdu/platform/system/reference/crs-catalog-service` |
| crs-conversion-service | `osdu/platform/system/reference/crs-conversion-service` |
| unit-service | `osdu/platform/system/reference/unit-service` |

### Libraries

| Repo | GitLab path |
|------|-------------|
| os-core-common | `osdu/platform/system/lib/core/os-core-common` |
| os-core-lib-azure | `osdu/platform/system/lib/cloud/azure/os-core-lib-azure` |

### Driver libraries

| Repo | GitLab path |
|------|-------------|
| os-obm | `osdu/platform/system/lib/drivers/os-obm` |
| os-obm-python | `osdu/platform/system/lib/drivers/os-obm-python` |
| os-sd | `osdu/platform/system/lib/drivers/os-sd` |
| os-oqm | `osdu/platform/system/lib/drivers/os-oqm` |
| apd | `osdu/platform/system/lib/drivers/apd` |

### Data flow / ingestion

| Repo | GitLab path |
|------|-------------|
| ingestion-workflow | `osdu/platform/data-flow/ingestion/ingestion-workflow` |

Construct the full URL: `https://community.opengroup.org/{path}.git`

For categories, construct a URL for each repo in the category.

## Step 3: Run the clone script

The clone script is bundled with this skill. Run it once per repo:

```bash
uv run .agents/skills/clone/scripts/clone.py <URL> [<name>]
```

The script handles:
- Workspace resolution (`$OSDU_WORKSPACE` or `./workspace` by default)
- `wt` / `git-wt` detection (bare clone + worktree if available, standard clone otherwise)
- Clone execution with skip/fail handling
- Result reporting

## After cloning

Report to the user:
- Which repos were cloned, skipped, or failed
- The clone method used (worktree or standard)
- For worktree clones, show the layout:
  ```
  <repo>/
    .bare/       <- bare clone
    .git         <- pointer file
    <branch>/    <- worktree (ready to work in)
  ```

## OSDU service provider context

When investigating cloned repos, only `*-azure/` provider directories are relevant
to SPI Stack. Skip `*-aws/`, `*-gc/`, `*-ibm/`, and `*-core-plus/` directories.
See AGENTS.md for full provider context.

## Working in cloned repos

**With worktrunk (`wt`):**
- `wt switch --create feature/xxx --base master` -- create feature branch worktree

**Without worktrunk:**
- `git checkout -b feature/xxx` -- create feature branch
- Standard git workflow
