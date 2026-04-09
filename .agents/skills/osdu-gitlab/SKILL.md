---
name: osdu-gitlab
description: >-
  OSDU platform GitLab operations -- glab CLI guardrails, cross-project MR and
  pipeline monitoring (osdu-activity), engineering contribution analysis
  (osdu-engagement), and CI/CD test reliability metrics (osdu-quality).
  Use when the user asks about: open merge requests, pipeline failures, failed
  CI jobs, GitLab issues, glab commands, contributor rankings, code review
  patterns, ADR engagement, test pass rates, flaky tests, test parity, or any
  interaction with the OSDU GitLab instance.
  Not for: OSDU API calls (use osdu-api), cloning repos (use clone), or
  tool installation (use setup).
triggers:
  - "open merge requests"
  - "pipeline failures"
  - "CI jobs"
  - "GitLab issues"
  - "contributor rankings"
  - "test pass rates"
  - "flaky tests"
  - "glab"
compatibility: >-
  Requires glab CLI for single-repo operations. Cross-project tools
  (osdu-activity, osdu-engagement, osdu-quality) installed via uv.
  Run the setup skill if any tool is missing.
---

# OSDU GitLab

Unified skill for all OSDU GitLab operations: single-repo management (glab),
cross-project monitoring (osdu-activity), contributor analysis (osdu-engagement),
and test reliability metrics (osdu-quality).

## Shared Context

### Authentication

All tools authenticate in this priority order:
1. `--token` flag (CLI tools only)
2. `GITLAB_TOKEN` environment variable
3. `glab` CLI authentication (`glab auth status` to verify)

Token needs `read_api` scope minimum. For write operations (MR create, comment), `api` scope.

### Self-Hosted Instances

**CRITICAL: Never use gitlab.com.** OSDU uses two self-hosted instances:

| Instance | Purpose |
|----------|---------|
| `community.opengroup.org` | OSDU community projects (public) |
| `gitlab.opengroup.org` | OpenGroup internal projects |

Verify with `glab auth status` and `git remote -v`.

### Output Format

For the three `osdu-*` CLI tools, **always** pass `--output markdown`:
```bash
osdu-activity mr --output markdown
osdu-engagement contribution --output markdown
osdu-quality analyze --output markdown
```
Default `tty` output includes ANSI codes that break parsing. Never omit the flag.

### Project and Provider Filtering

All three `osdu-*` tools support:
- `--project` with fuzzy matching: `--project idx` matches "indexer-service"
- Comma-separated: `--project partition,storage,search`
- Provider filter: `--provider azure|aws|gcp|ibm|cimpl|core`

---

## glab CLI

Expert guardrails for the GitLab CLI. See [full reference](references/glab-guardrails.md).

### Critical Corrections

```bash
# Comments on MRs (NOT "glab mr note create")
glab mr note <mr-number> -m "Comment text"

# View MR with comments (NOT "glab mr approve --list")
glab mr view <mr-number> --comments

# Reviewers use = sign, comma-separated, no spaces
glab mr create --title "Fix bug" --reviewer=alice,bob --label="bug,urgent"

# Draft toggle (NOT "glab mr draft")
glab mr update <mr-number> --draft
glab mr update <mr-number> --ready

# MR listing by state (NOT --state=opened)
glab mr list                    # open (default)
glab mr list --merged           # merged
glab mr list --all              # all states

# Pipeline variables (NOT --variable or --var)
glab ci run -V KEY1=value1 -V KEY2=value2

# API pagination goes in URL, NOT as CLI flag
glab api "projects/:id/jobs?per_page=100"
glab api --paginate "projects/:id/pipelines/123/jobs?per_page=100"
```

### Scripting

```bash
# JSON output for parsing
glab mr list --output=json | jq '.[] | {iid: .iid, title: .title}'

# MR API includes head_pipeline inline
glab api --paginate "projects/:id/merge_requests?state=opened&per_page=100" \
  | jq '.[] | {iid: .iid, title: .title, pipeline: .head_pipeline.status}'
```

---

## osdu-activity

Cross-project MR, pipeline, and issue monitoring across 30+ OSDU services.
See [command reference](references/activity-commands.md).

### Intent Detection

| User asks about | Command |
|-----------------|---------|
| Open MRs, pending reviews | `osdu-activity mr --output markdown` |
| Pipeline status, CI status | `osdu-activity pipeline --output markdown` |
| Failed jobs, what's failing | `osdu-activity pipeline --style list --output markdown` |
| Open issues, bugs | `osdu-activity issue --output markdown` |
| ADR issues | `osdu-activity issue --adr --output markdown` |
| Draft/WIP MRs | `osdu-activity mr --include-draft --output markdown` |
| Milestone triage | `osdu-activity mr --milestone M26 --output markdown` |
| MRs by someone | `osdu-activity mr --author johndoe --output markdown` |
| My MRs / my plate | `osdu-activity mr --user <username> --output markdown` |
| Merged MRs | `osdu-activity mr --state merged --output markdown` |

### Key Commands

```bash
osdu-activity mr [--project X] [--state opened|merged|closed|all] [--milestone M26]
                 [--user U] [--author A] [--reviewer R] [--provider P]
                 [--style table|list] [--show-jobs] [--include-draft]
                 --output markdown

osdu-activity pipeline [--project X] [--provider P] [--style table|list]
                       --output markdown

osdu-activity issue [--project X] [--adr] [--style table|list]
                    --output markdown
```

### Analysis Guidance

- **"What MRs are open?"** -- Lead with key finding (counts by project). Highlight failing pipelines. Note stale MRs (>14 days, no updates).
- **"What's failing in CI?"** -- Group failures by pattern (same stage? same provider?). Provider-clustered failures suggest environment issues, not code bugs.
- **"Release triage"** -- Show open vs merged vs closed. Flag stale MRs and blockers (failing pipelines, no reviewers).

---

## osdu-engagement

Engineering contribution and ADR engagement analysis.
See [command reference](references/engagement-commands.md).

### Intent Detection

| User asks about | Command |
|-----------------|---------|
| Contributors, who's active | `osdu-engagement contribution --output markdown` |
| Top contributors, rankings | `osdu-engagement contribution --output markdown` |
| Activity trends, monthly | `osdu-engagement contribution trend --output markdown` |
| ADR engagement, decisions | `osdu-engagement decision --output markdown` |
| Review patterns, workload | `osdu-engagement contribution --output markdown` |

### Key Commands

```bash
osdu-engagement contribution [--days 30] [--project X] [--start-date YYYY-MM-DD]
                             --output markdown

osdu-engagement contribution trend [--months 6] --output markdown

osdu-engagement decision [--days 30] [--project X] --output markdown
```

### Interpreting Results

**Healthy patterns:**
- Multiple active contributors (not single-person dominance)
- Review load distributed across team
- Consistent or growing activity trend
- ADRs getting engagement and discussion

**Warning signs:**
- Single contributor dominance (bus factor risk)
- Review bottleneck (few people doing all reviews)
- Declining trend (team shrinking or disengaging)
- ADRs with zero engagement (decisions without input)

---

## osdu-quality

CI/CD test reliability analysis across OSDU pipelines.
See [command reference](references/quality-commands.md).

### Intent Detection

| User asks about | Command |
|-----------------|---------|
| Test pass rates, reliability | `osdu-quality analyze --output markdown` |
| Flaky tests, intermittent | `osdu-quality analyze --output markdown` |
| Test status by stage | `osdu-quality status --output markdown` |
| Provider-specific tests | `osdu-quality analyze --provider azure --output markdown` |
| Actual test failures | `osdu-quality tests --project X --output markdown` |
| Test parity (CSP vs cimpl) | `osdu-quality tests --project X --output json` |

### Key Commands

```bash
osdu-quality analyze [--project X] [--provider P] [--stage unit|integration|acceptance]
                     [--pipelines 10] --output markdown

osdu-quality status [--project X] [--venus] [--no-release] --output markdown

osdu-quality tests --project X [--pipeline ID] --output markdown
```

### Pass Rate Thresholds

| Pass Rate | Health | Stage Context |
|-----------|--------|---------------|
| 95%+ | Healthy | Expected for unit tests |
| 80-95% | Needs attention | Acceptable for integration |
| <80% | Concerning | Common only in acceptance (env-dependent) |

### Flaky Test Signals

- Alternating pass/fail across runs
- High variance in pass rates
- Inconsistent results across providers (suggests environment, not code)

### Acceptance Test Parity

To compare CSP vs cimpl test coverage:
1. `osdu-quality tests --project <service> --output json`
2. Extract test classes from `stages.acceptance` by provider
3. Compute gap: classes in CSP but absent from cimpl
4. Report overlap percentage and missing test list

---

## Cross-Domain Workflows

Combine tools for comprehensive project health:

```bash
# Full health check for a service
osdu-activity mr --project partition --output markdown
osdu-activity pipeline --project partition --output markdown
osdu-quality analyze --project partition --output markdown
osdu-engagement contribution --project partition --output markdown
```

**"What's the state of indexer?"** -- Run all four, then synthesize:
- Open MRs and their pipeline status (activity)
- Test reliability and any flaky tests (quality)
- Who's actively contributing and reviewing (engagement)

**"Are we ready to release M26?"** -- Combine:
- `osdu-activity mr --milestone M26` -- open vs merged MRs
- `osdu-quality status` -- test health across services
- `osdu-engagement contribution --days 30` -- team engagement level

## Troubleshooting

See [troubleshooting guide](references/troubleshooting.md) for auth issues, missing
tools, slow responses, and common problems across all four tools.

## Installation

```bash
# glab: see setup skill for installation
# osdu-* tools:
uv tool install osdu-activity --index-url https://community.opengroup.org/api/v4/projects/1629/packages/pypi/simple
uv tool install osdu-engagement --index-url https://community.opengroup.org/api/v4/projects/1631/packages/pypi/simple
uv tool install osdu-quality --index-url https://community.opengroup.org/api/v4/projects/1630/packages/pypi/simple
```

Or run the `setup` skill to install all tools automatically.
