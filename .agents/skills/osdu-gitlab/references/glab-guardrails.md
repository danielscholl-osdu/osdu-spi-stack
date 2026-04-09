# GitLab CLI (glab) -- Guardrails

This reference corrects common mistakes and fills knowledge gaps when using `glab`. Models
already know the basics -- this focuses on what they get wrong without guidance.

## Command Accuracy

These commands are frequently hallucinated or used with wrong syntax. Use exactly as shown:

```bash
# CORRECT comment syntax (glab mr note, not "glab mr note create" or "glab mr note list")
glab mr note <mr-number> -m "Comment text"

# CORRECT review listing (there is no "glab mr approve --list")
glab mr view <mr-number> --comments

# CORRECT MR creation with reviewers -- use = sign, comma-separated, no spaces
glab mr create --title "Fix bug" --reviewer=alice,bob --label="bug,urgent"

# CORRECT draft toggle (use update, not "glab mr draft")
glab mr update <mr-number> --draft
glab mr update <mr-number> --ready

# CORRECT pipeline variable passing (use -V, not --variable or --var)
glab ci run -V KEY1=value1 -V KEY2=value2

# CORRECT MR listing by state (default shows open only)
glab mr list                    # open MRs (default)
glab mr list --merged           # merged MRs
glab mr list --closed           # closed MRs
glab mr list --all              # ALL states combined

# WRONG -- these flags don't exist
# glab mr list --state=opened   # WRONG
# glab mr list --state=merged   # WRONG
```

## API Pagination (Easy to Get Wrong)

Pagination parameters go in the URL as query params, NOT as CLI flags:

```bash
# CORRECT -- per_page in the URL
glab api "projects/:id/jobs?per_page=100"

# CORRECT -- auto-paginate all results
glab api --paginate "projects/:id/pipelines/123/jobs?per_page=100"

# WRONG -- these flags don't exist on glab api
# glab api projects/:id/jobs --per-page 100    # WRONG
# glab api projects/:id/jobs -P 100             # WRONG
```

The `:id` placeholder auto-resolves to the current project when run inside a git repo.

## Self-Hosted GitLab (IMPORTANT: We Do NOT Use gitlab.com)

This project uses two self-hosted GitLab instances. NEVER default to gitlab.com:

| Instance | Purpose |
|----------|---------|
| `community.opengroup.org` | OSDU community projects (https, public) |
| `gitlab.opengroup.org` | OpenGroup internal projects (ssh for git, https for API) |

glab auto-detects the correct instance from the Git remote of the current repo. Before
running commands, verify you're targeting the right one:

```bash
# Check which instances you're authenticated to
glab auth status

# Verify current repo points to the right instance
git remote -v
```

If you need to specify an instance explicitly (e.g., outside a repo):

```bash
glab mr list -R community.opengroup.org/namespace/project
glab mr list -R gitlab.opengroup.org/namespace/project
```

For scripts/CI, set the host explicitly:

```bash
export GITLAB_HOST=community.opengroup.org   # or gitlab.opengroup.org
export GITLAB_TOKEN=<your-gitlab-personal-access-token>
```

Common self-hosted gotchas:

- **SSL errors** (`x509: certificate signed by unknown authority`): custom CA -- use `git config --global http.sslCAInfo /path/to/cert.pem`
- **401 after auth**: token needs `api` scope at minimum
- **404 on valid project**: check the full namespace path (groups can be nested)
- **Wrong instance**: if commands return unexpected results, check `git remote -v`

## Scripting Tips

```bash
# JSON output for scripting
glab mr list --output=json | jq '.[] | {iid: .iid, title: .title}'

# MR API includes head_pipeline inline -- no separate pipeline calls needed:
glab api --paginate "projects/:id/merge_requests?state=opened&per_page=100" \
  | jq '.[] | {iid: .iid, title: .title, pipeline: .head_pipeline.status}'

# GITLAB_TOKEN env var is auto-detected in CI; also set GITLAB_HOST for self-hosted
```
