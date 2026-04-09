---
name: deps
description: >
  Dependency analysis, vulnerability scanning, and risk-prioritized remediation for OSDU
  Java services. Covers the full lifecycle: Trivy scan, Maven Central version check, risk
  scoring, tiered remediation with build validation, and commit generation.
triggers:
  - "scan dependencies"
  - "check deps"
  - "vulnerability scan"
  - "CVE"
  - "remediate"
  - "fix dependencies"
  - "dependency report"
  - "update dependencies"
  - "trivy"
  - "POM analysis"
compatibility: Requires trivy, java 17+, mvn, and uv.
---

# deps -- Dependency Analysis & Remediation

Scan OSDU Java service dependencies for vulnerabilities and outdated versions, then
remediate them with risk-tiered commit strategies and build validation.

## Prerequisites

| Tool | Required For | Install |
|------|-------------|---------|
| `trivy` | Vulnerability scanning | `brew install trivy` |
| `java` + `mvn` | Build validation | JDK 17+ |
| `uv` | Script execution | `brew install uv` |

If tools are missing, delegate to the `setup` skill.

## Scripts

All scripts are self-contained `uv run` scripts in `scripts/`:

| Script | Purpose | Key Commands |
|--------|---------|-------------|
| `check.py` | Maven Central version lookup | `check`, `batch`, `list`, `pom` |
| `scan.py` | Trivy vulnerability scanner | `scan`, `analyze` |
| `report.py` | Risk-scored report generator | default command |
| `javatest.py` | Build/test runner | `--validate`, `--test`, `--compile` |

All script paths are relative to the project root:

```
.agents/skills/deps/scripts/<script>.py
```

## Workflow 1: Scan (Analysis Only)

Use when: user asks to scan, check, analyze, or report on dependencies.

### Step 1: Locate the Project

Find the OSDU service repo in the workspace. Convention:

```
$OSDU_WORKSPACE/<service-name>/          # flat clone
$OSDU_WORKSPACE/<service-name>/master/   # worktree layout
```

Verify `pom.xml` exists at the root. If not found, suggest the `clone` skill.

### Step 2: Run Vulnerability Scan

```bash
uv run .agents/skills/deps/scripts/scan.py scan \
  --path <PROJECT_PATH> --compact --json
```

`--compact` deduplicates CVEs and reduces output size (~90% reduction). Parse the JSON
output for `summary.severity_counts` and `detailed` vulnerability list.

### Step 3: Run Version Check

```bash
uv run .agents/skills/deps/scripts/check.py pom \
  --path <PROJECT_PATH> --include-managed --json
```

This queries Maven Central for every dependency. Parse `dependencies` array for entries
with `has_patch_update`, `has_minor_update`, or `has_major_update`.

### Step 4: Apply Risk Framework

For each dependency that has a CVE or an available update, calculate risk score:

```
Risk Score = Category (0-2) + Jump (0-3) + CVE (-1 to +1) + Depth (0-1)
```

**Category** (how central is this dependency?):
- Framework (Spring Boot, Quarkus, Jakarta EE): +2
- Data/Network/DB/Security/Cloud: +1
- Utility/Testing: 0

**Jump** (how big is the version change?):
- Patch: 0
- Minor: +1
- Major: +3

**CVE** (does updating fix a vulnerability?):
- Fixes CRITICAL CVE: -1 (reduces risk -- urgent AND safe)
- Fixes other CVE: 0
- No CVE: +1

**Depth** (where does this dependency live?):
- Direct dependency: 0
- Deep transitive: +1

**Risk Levels:**
- LOW (0-1): Safe to batch together
- MEDIUM (2-3): Apply individually, validate each
- HIGH (4+): Research first, plan carefully

### Step 5: Generate Report

Present findings organized by **UPDATE RISK** (not CVE severity). This is the key insight:
CVE severity tells you "how dangerous is this vulnerability?" while update risk tells you
"how safe is this fix to apply?"

Example: A CRITICAL CVE with a patch-level fix = LOW risk update (urgent AND safe).

Structure the report with these sections:

```markdown
## Dependency Analysis: <service-name>

### Summary
- Analyzed: <date>
- Vulnerabilities: X critical, Y high, Z medium
- Updates available: A low-risk, B medium-risk, C high-risk

### LOW Risk Updates (batch together)
| Package | Current | Target | CVEs Fixed | Fix Location |
...

### MEDIUM Risk Updates (one at a time)
| Package | Current | Target | CVEs Fixed | Fix Location |
...

### HIGH Risk Updates (research first)
| Package | Current | Target | CVEs Fixed | Fix Location |
...
```

The "Fix Location" column tells the remediation phase WHERE to make the change:
- `version-property`: update a `<properties>` entry in pom.xml
- `direct`: update the `<version>` tag on the dependency element
- `bom`: update managed in a BOM import

---

## Workflow 2: Remediate

Use when: user asks to remediate, fix, update, or apply dependency changes.
Requires a prior scan report (from Workflow 1) or the user specifying which updates to apply.

### Phase 0: Parse Scope

Determine which risk tiers to remediate:
- `--low` or "fix the safe ones": LOW risk only
- `--medium`: LOW + MEDIUM
- `--all` or "fix everything": all tiers
- Specific packages: user names individual dependencies

### Phase 1: Verify Baseline

Before changing anything, confirm the project builds cleanly:

```bash
uv run .agents/skills/deps/scripts/javatest.py \
  --project <service-name> --validate
```

If baseline fails, STOP and report. Don't remediate on a broken foundation.

### Phase 2: Create Branch

```bash
git checkout main && git pull
git checkout -b agent/dep-remediation-$(date +%Y%m%d)
```

### Phase 3: LOW Risk Updates (Batch)

1. Apply ALL verified LOW risk updates to pom.xml
2. For each update, verify the target version exists first:
   ```bash
   uv run .agents/skills/deps/scripts/check.py check \
     -d <groupId>:<artifactId> -v <target-version> --json
   ```
3. Run build validation:
   ```bash
   uv run .agents/skills/deps/scripts/javatest.py \
     --project <service-name> --validate
   ```
4. On success: single commit `chore(deps): apply low-risk security updates`
5. On failure: bisect to find the problematic update, skip it, retry

### Phase 4: MEDIUM Risk Updates (Individual)

For each MEDIUM risk update:

1. Apply ONE update to pom.xml
2. Validate build:
   ```bash
   uv run .agents/skills/deps/scripts/javatest.py \
     --project <service-name> --validate
   ```
3. On success: commit `chore(deps): update <package> to <version>`
4. On failure: analyze error, attempt fix if localized, or skip with note

### Phase 5: HIGH Risk Updates (Research First)

For each HIGH risk update:

1. Research breaking changes (check changelog, migration guide)
2. Apply update
3. Fix compilation errors iteratively
4. Fix test failures iteratively
5. Commit with BREAKING CHANGE footer if applicable:
   ```
   chore(deps): update <package> to <version>

   BREAKING CHANGE: <description of what changed>
   ```

### Phase 6: Final Validation

Run full build one more time to confirm everything works together:

```bash
uv run .agents/skills/deps/scripts/javatest.py \
  --project <service-name> --validate
```

Compare test counts to baseline. Report any regressions.

### Phase 7: Summary

Report what was done:
- Applied: N updates (list with commit hashes)
- Skipped: M updates (list with reasons)
- Deferred: K updates (HIGH risk, needs planning)

---

## POM Editing Rules

When modifying pom.xml files:

1. **Version properties first**: If the version is defined as `${spring-boot.version}` in
   `<properties>`, update the property value, NOT the dependency element.

2. **Preserve formatting**: Match existing indentation (spaces vs tabs, indent depth).

3. **One change at a time for MEDIUM/HIGH**: Each update gets its own edit-validate cycle.

4. **Never change scope or exclusions**: Only change version numbers.

5. **Verify before commit**: Always run `check.py check` to confirm the target version
   exists on Maven Central before editing the POM.

---

## Multi-Repo Awareness

OSDU services share common libraries (`os-core-common`, `os-core-lib-azure`). When scanning:

- Flag when a vulnerability is in a shared library
- Note downstream impact: "This library is used by partition, storage, search..."
- After remediating a shared library, suggest validating dependent services

## Commit Messages

Use `aipr commit -m claude -s` for generating commit messages (per project CLAUDE.md rules).
If aipr is not available, use conventional commit format:

```
chore(deps): <description>
```
