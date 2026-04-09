# AI Skills

SPI Stack ships portable **AI Skills**: domain expertise that AI coding assistants
discover automatically. Ask a question in natural language and the right skill activates
with the context needed to help.

9 skills across onboarding, GitLab operations, platform access, and the full ship-and-test
development cycle.

## How It Works

```
Ask a question  →  AI matches a skill  →  Skill injects domain context  →  Informed response
```

Skills are markdown files with structured metadata in `.agents/skills/`. The AI reads the
`description` field to decide which skill is relevant to your question. No slash commands
or manual activation required.

## Who Is It For

**Platform engineers** deploying and operating SPI Stack environments: prerequisite checks,
cluster health, API verification, infrastructure debugging.

**Service developers** working on OSDU services: cloning repos, running tests, scanning
dependencies, shipping code through merge requests.

## What's Inside

### Onboard

Get oriented and set up your environment.

| Skill | What it does |
|-------|-------------|
| **prime** | Builds a lightweight mental model of the codebase: project structure, deployment phases, ADRs, and available commands. Use at the start of a session or when returning after time away. |
| **setup** | Checks prerequisites (az, kubectl, flux, helm) and installs development tools (glab, uv). Guides Azure CLI authentication. Tells you exactly what's missing and offers to fix it. |

### Observe

Monitor GitLab activity and query live OSDU environments.

| Skill | What it does |
|-------|-------------|
| **osdu-gitlab** | GitLab operations across 30+ OSDU repositories. Includes glab CLI guardrails, cross-project MR and pipeline monitoring (osdu-activity), engineering contribution analysis (osdu-engagement), and CI/CD test reliability metrics (osdu-quality). |
| **osdu-api** | Live OSDU platform API access for SPI Stack deployments. Routes requests through the Istio gateway, handles Azure Entra ID authentication. Query records, search data, list schemas, check entitlements, manage legal tags. |

### Ship

Move code from local changes to merged MR.

| Skill | What it does |
|-------|-------------|
| **clone** | Clone OSDU GitLab repositories into the local workspace. Supports single service, category, or all repos. Handles bare-clone worktree layout or standard git clone. |
| **ship** | Ship code changes to GitLab: quality checks, conventional commits, push, and MR creation. Handles both shipping your own branch and contributing to someone else's existing MR. |
| **osdu-mr** | Manage existing merge requests through their lifecycle. Three modes: **Review** (code analysis + pipeline diagnostics with a verdict), **Allow** (trusted branch sync to trigger full CI), and **FOSSA** (fix NOTICE files from failed pipeline artifacts). |

### Test & Secure

Validate code and manage dependencies.

| Skill | What it does |
|-------|-------------|
| **osdu-test** | Run Java integration tests against a live SPI Stack environment. Uses Azure Entra ID auth, prefers Azure provider tests (`testing/*-test-azure/`), resolves environment from the running cluster, and parses Surefire results. |
| **deps** | Dependency analysis and remediation for OSDU Java services. Full lifecycle: Trivy vulnerability scan, Maven Central version check, risk scoring, tiered remediation with build validation, and commit generation. |

## Supported Platforms

Skills follow the [Agent Skills Standard](https://agentskills.io). Most AI coding assistants
discover skills directly from `.agents/skills/`, including GitHub Copilot, Codex, Cursor,
Gemini CLI, Goose, Junie, and others. Claude Code does not read `.agents/skills/` natively,
so skills are symlinked into `.claude/skills/` for discovery.

### Claude Code Setup

```bash
ln -sf ../.agents/skills .claude/skills
```

## Skill Anatomy

Each skill lives in its own directory:

```
.agents/skills/
  my-skill/
    SKILL.md              # Skill definition (frontmatter + instructions)
    scripts/              # Optional: Python scripts for data gathering
    references/           # Optional: detailed reference docs
```

**Guidance skills** (prime, setup, ship, osdu-gitlab, osdu-mr) provide workflow knowledge.
The AI uses its existing tools (Bash, Read, Grep) guided by the skill's instructions.

**Script-backed skills** (clone, osdu-api, osdu-test, deps) include Python scripts that
handle data collection. Scripts gather data; the AI provides analysis. Run with `uv run`.

### SKILL.md Format

```yaml
---
name: my-skill
description: >-
  What this skill does and when to use it. The AI reads this field
  to decide relevance. Include trigger phrases and anti-patterns.
compatibility: Runtime requirements and dependencies.
---

# My Skill

Instructions, workflow steps, examples...
```

The `description` field is the discovery mechanism. State purpose first, add trigger phrases
("Use when the user asks about..."), and note anti-patterns ("Not for: X, use Y instead").

## Creating a New Skill

1. Create `.agents/skills/my-skill/SKILL.md` with frontmatter and content
2. Add `scripts/` or `references/` subdirectories if needed
3. The `.claude/skills` symlink auto-discovers new skills
4. Add the skill to the table in `AGENTS.md`
5. Test in a fresh AI session. Verify it activates on expected queries
