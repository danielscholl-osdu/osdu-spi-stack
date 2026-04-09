---
name: ship
description: >
  Ship code changes to GitLab -- commit, push, and create merge requests for OSDU service
  repositories. Handles both own-branch shipping and contributing to someone else's MR.
triggers:
  - "send it"
  - "ship it"
  - "push my changes"
  - "create MR"
  - "create merge request"
  - "commit and push"
  - "contribute to MR"
  - "submit changes"
compatibility: Requires git and glab CLI. Optional aipr for commit message generation.
---

# ship -- Commit, Push & Merge Request

Ship code changes to GitLab with quality checks, conventional commits, and MR creation.
Handles two modes: shipping your own work (send) and contributing to someone else's MR.

## Prerequisites

| Tool | Required | Install |
|------|----------|---------|
| `git` | Always | System package manager |
| `glab` | MR creation | `brew install glab` |
| `aipr` | Commit messages | Per CLAUDE.md instructions |

## Mode Detection

Before doing anything, determine the shipping mode:

1. **Check branch safety**: If on `main`, `master`, or a protected branch, STOP.
   Ask the user to create a feature branch first.

2. **Check if contributing**: Query for open MRs targeting the current branch:
   ```bash
   glab mr list --source-branch $(git branch --show-current) --state opened
   ```
   If the current branch belongs to someone else's open MR, switch to **Contribute Mode**.

3. **Check for changes**: Run `git status --short`. If nothing to commit, report and stop.

Default: **Send Mode** (own branch).

---

## Send Mode (Ship Your Own Work)

### Phase 1: Lite Code Review

View the full diff and scan for obvious issues:

```bash
git diff HEAD
git diff --cached
```

Check for:
- Hardcoded secrets (API keys, passwords, tokens)
- Dangerous files (`.tfstate`, `.env`, credentials)
- Debug/TODO artifacts left in code
- Obvious logic errors

If blocking concerns are found, report them and STOP. Let the user decide.

### Phase 2: Quality Checks

Run file-type-aware validation on changed files:

```bash
git diff --name-only HEAD
```

For each changed file type:
- **Terraform** (`.tf`): `terraform fmt -check`
- **YAML** (`.yaml`, `.yml`): validate with `python -c "import yaml; yaml.safe_load(open('file'))"`
- **Java** (`.java`): check for compilation (if in a Maven project)
- **Python** (`.py`): basic syntax check `python -m py_compile file.py`

Report failures but let the user decide whether to proceed.

### Phase 3: Commit

Generate a conventional commit message using `aipr`:

```bash
git add <specific-files>
git commit -m "$(aipr commit -m claude -s)"
```

**Commit rules:**
- Use conventional commit format: `type(scope): description`
- One-line subject under 72 characters
- NO `Co-Authored-By` lines
- NO `Signed-off-by` lines
- NO AI attribution footers
- If `aipr` is unavailable, write a manual conventional commit

Stage specific files, not `git add -A`. Never stage `.env`, credentials, or generated files.

### Phase 4: Push

```bash
git push -u origin $(git branch --show-current)
```

If the remote rejects (behind upstream), do NOT force-push. Report the situation and
suggest `git pull --rebase`.

### Phase 5: Create Merge Request

Check for an existing MR on this branch first:

```bash
glab mr list --source-branch $(git branch --show-current) --state opened
```

If no MR exists, create one:

1. **Detect target branch**: Query the repo's default branch:
   ```bash
   glab api "projects/:id" --jq '.default_branch'
   ```
   Use `dev` if it exists, otherwise the default branch.

2. **Get assignee**: Extract from `glab auth status` output.

3. **Generate MR description** using `aipr`:
   ```bash
   aipr pr -m claude -s
   ```

4. **Create MR**:
   ```bash
   glab mr create \
     --title "<conventional-commit-style title>" \
     --description "$(aipr pr -m claude -s)" \
     --assignee <username> \
     --remove-source-branch
   ```

5. Report the MR URL to the user.

If an MR already exists, just push (Phase 4) and report that the existing MR was updated.

---

## Contribute Mode (Push to Someone Else's MR)

Use when the current branch belongs to someone else's open MR, or the user explicitly
says "contribute to MR #N".

### Phase 1: Verify Parent MR

```bash
glab mr view <mr-number>
```

Confirm the MR is still open. Extract the source branch name.

### Phase 2: Prepare Contribution Branch

Create a contribution branch from the parent MR's source branch:

```bash
git checkout -b fix/<description>-for-mr-<number>
```

Branch naming: `test/improve-X`, `fix/Y-for-mr-845`, `chore/Z-for-mr-123`

### Phase 3: Commit & Push

Same commit rules as Send Mode Phase 3-4.

### Phase 4: Create Sub-MR

Create an MR that targets the **parent MR's source branch** (NOT `dev` or `main`):

```bash
glab mr create \
  --title "<type>: <description>" \
  --description "<brief explanation of what and why>" \
  --target-branch <parent-mr-source-branch> \
  --remove-source-branch
```

### Phase 5: Draft Comment on Parent MR

Draft a comment on the parent MR explaining the contribution:

```bash
glab mr comment <parent-mr-number> --message "<your comment>"
```

**Only post after user approval.** Show the draft first.

---

## GitLab Instance Handling

Detect the GitLab instance from the git remote or glab auth:

```bash
git remote get-url origin
glab auth status
```

Always use `--hostname` flag with glab when the remote is not `gitlab.com`:

```bash
glab mr create --hostname community.opengroup.org ...
```

## Comment Tone Rules

When drafting MR descriptions or comments:

- No em dashes. Use periods, commas, or rewrite.
- No opener praise ("Great work", "Nice changes"). Start with substance.
- No filler ("It's worth noting", "I noticed that", "Just wanted to mention").
- Short sentences. Technical and factual.
- Proportionate length: simple MR gets 2-3 sentences, complex gets a few paragraphs.
