---
name: osdu-mr
description: >
  Manage the lifecycle of GitLab merge requests -- code review with pipeline diagnostics,
  trusted branch sync (allow), and FOSSA NOTICE file fixes. Operates on existing MRs.
triggers:
  - "review MR"
  - "review merge request"
  - "look at MR"
  - "assess MR"
  - "allow MR"
  - "sync trusted"
  - "trigger trusted tests"
  - "fix fossa"
  - "update NOTICE"
  - "fossa"
compatibility: Requires glab CLI and git. curl or wget for FOSSA NOTICE downloads.
---

# osdu-mr -- MR Review, Allow & FOSSA

Three modes for managing existing GitLab merge requests:
- **Review**: Code analysis + pipeline diagnostics with a verdict
- **Allow**: Trusted branch sync to trigger full CI (OSDU maintainer pattern)
- **FOSSA**: Fix NOTICE file from failed pipeline artifacts

## Prerequisites

| Tool | Required For | Install |
|------|-------------|---------|
| `glab` | All modes | `brew install glab` |
| `git` | Allow + FOSSA modes | System package manager |

## Mode Detection

Route based on user intent:
- "review MR 845" / "look at this MR" / MR URL -> **Review**
- "allow MR 845" / "sync trusted" / "trigger trusted tests" -> **Allow**
- "fix fossa" / "update NOTICE" / "fossa MR 845" -> **FOSSA**

---

## Review Mode

### Input Parsing

Accept any of:
- Full URL: `https://community.opengroup.org/osdu/platform/system/search-service/-/merge_requests/845`
- Short ref: `search-service!845`
- MR number (if in the service repo): `845`

Extract: hostname, project path, MR number.

### Phase 1: Fetch MR Context (parallel)

**1a. MR Metadata:**
```bash
glab mr view <number> --json title,author,description,sourceBranch,targetBranch,labels,milestone,state
```

**1b. Diff:**
```bash
glab api "projects/:id/merge_requests/<number>/changes?access_raw_diffs=true"
```

Fallback if too large:
```bash
glab api "projects/:id/merge_requests/<number>.diff"
```

**1c. Pipeline Status:**
```bash
glab api "projects/:id/merge_requests/<number>/pipelines"
```

Then fetch jobs for the most recent pipeline:
```bash
glab api "projects/:id/pipelines/<pipeline-id>/jobs"
```

**Important -- OSDU Child Pipeline Detection:**

OSDU uses a parent/child pipeline pattern. The parent pipeline contains a `trigger-trusted-tests`
job that spawns a child pipeline with the actual tests. When analyzing pipelines:

1. Look for a job named `trigger` or `trigger-trusted-tests` in the parent pipeline
2. If found, extract the child pipeline ID from the job trace:
   ```bash
   glab api "projects/:id/jobs/<trigger-job-id>/trace" | grep -o 'pipeline.*[0-9]*'
   ```
3. Fetch the child pipeline's jobs -- those are the real test results

### Phase 2: Code Analysis

**Categorize changes** by area:
- Dependencies (pom.xml, package.json, requirements.txt)
- CI/CD (.gitlab-ci.yml, Dockerfile)
- Source core (shared modules)
- Source provider (provider-specific code)
- Tests
- API/Contract (swagger, OpenAPI)
- Docs
- Config (application.properties, values.yaml)

**Review checklist:**
- Security: hardcoded secrets, injection vectors, unsafe deserialization
- Behavior changes: null handling, exception types, return value semantics
- API contracts: breaking changes to endpoints, request/response schemas
- Cross-provider consistency: does this change affect core-plus behavior?
- Test coverage: are new paths tested?

**Summary:** Write 3-5 sentences explaining what the MR does and why.

### Phase 3: Pipeline Diagnostics

For each failed job:

1. **Get job log** (last 80 lines):
   ```bash
   glab api "projects/:id/jobs/<job-id>/trace" | tail -80
   ```

2. **Classify the failure:**
   - **MR-caused**: Changed files in the MR triggered the failure
   - **Pre-existing**: Same failure exists on the target branch's latest pipeline
   - **Environment**: Infrastructure issue (DNS, cluster, timeouts, certificates)
   - **Transient**: One-time failure, resource contention, intermittent

3. **Build pipeline summary table:**
   ```
   | Job | Status | Classification | Details |
   ```

4. **Separate blockers from non-blockers.** Only MR-caused failures are blockers.

### Phase 4: Verdict

Recommend one of:
- **Approve**: Clean code, tests pass, no concerns
- **Approve with notes**: Minor suggestions, nothing blocking
- **Needs work**: Issues that should be fixed before merge
- **Blocked**: Pipeline failures caused by this MR

### Phase 5: Draft Comment

Generate a developer-voice comment for the MR. **Do NOT post automatically.**
Show the draft and wait for user approval.

**Tone rules:**
- No em dashes. Use periods or commas.
- No opener praise ("Great work"). Start with substance.
- No filler ("It's worth noting", "I noticed that").
- Short sentences. Technical and factual.
- Proportionate length to MR complexity.

To post after approval:
```bash
glab mr comment <number> --message "<approved comment>"
```

---

## Allow Mode (Trusted Branch Sync)

OSDU uses a two-tier CI/CD security model:
- Developers push to regular branches -> parent pipeline runs (limited scope)
- Maintainers sync to a trusted branch -> `trigger-trusted-tests` verifies SHA -> child pipeline runs (full tests)

### Phase 1: Review Before Allow

Before syncing, do a quick review:

1. Get MR metadata (title, author, labels, milestone)
2. Check commit history for conventional commit compliance
3. Quick security scan (no hardcoded secrets, no suspicious patterns)
4. Suggest labels based on changed files:
   - Common/shared code -> `common`
   - Provider-specific -> provider label (e.g., `azure`, `core-plus`)
   - Dependencies -> `dependencies`
   - CI/CD -> `ci/cd`
   - Docs -> `documentation`
5. Provide recommendation: APPROVE | REVIEW NEEDED | CAUTION

### Phase 2: Sync Trusted Branch

When the user says "allow it" or "sync trusted":

1. Parse MR number (from input or detect from current branch)
2. Get the MR's source branch name
3. Derive trusted branch: `trusted-<source-branch>`
4. Sync:
   ```bash
   git push origin <source-branch>:refs/heads/trusted-<source-branch> --force
   ```
5. Optionally retry the `trigger-trusted-tests` job:
   ```bash
   glab api --method POST "projects/:id/jobs/<job-id>/retry"
   ```

---

## FOSSA Mode (Fix NOTICE File)

When a FOSSA license check fails in the pipeline, this mode retrieves the correct
NOTICE file from the pipeline artifacts and commits it.

### Workflow

1. **Determine MR number** (from input or detect from current branch):
   ```bash
   glab mr list --source-branch $(git branch --show-current) --state opened --json number
   ```

2. **Get project ID:**
   ```bash
   glab api "projects/:fullpath" --jq '.id'
   ```

3. **Find the parent pipeline** (source: `merge_request_event`):
   ```bash
   glab api "projects/:id/merge_requests/<number>/pipelines"
   ```

4. **Find the child pipeline** from `trigger-trusted-tests` job trace:
   ```bash
   glab api "projects/:id/jobs/<trigger-job-id>/trace"
   ```
   Extract child pipeline ID from the output.

5. **Check `fossa-check-notice` job** in child pipeline:
   - If `success`: report "FOSSA check passed, no action needed" and STOP
   - If `failed`: continue

6. **Extract NOTICE URL** from job log:
   ```bash
   glab api "projects/:id/jobs/<fossa-check-job-id>/trace" | grep wget
   ```
   The log contains a wget command with the URL to the correct NOTICE file.

7. **Download updated NOTICE** from `fossa-analyze` job artifacts:
   - Artifact path: `fossa-output/generated-clean-NOTICE`
   - Use web fetch or wget to download

8. **Verify NOTICE file** is not empty. If empty, report error and STOP.

9. **Commit and push:**
   ```bash
   git add NOTICE
   git commit -m "$(aipr commit -m claude -s)"
   git push origin $(git branch --show-current)
   ```

### Error Handling

- No MR found: ask user for MR number
- Pipeline not found: report error with MR URL
- `fossa-check-notice` already passed: report success, no action
- No wget URL in log: report error, show relevant log section
- Download fails: report error with URL for manual download
- Empty NOTICE file: report error, do not commit

---

## GitLab Instance Handling

Always detect the GitLab hostname from the git remote:

```bash
git remote get-url origin
```

Use `--hostname` flag with glab for non-gitlab.com instances:

```bash
glab mr view 845 --hostname community.opengroup.org
```
