# OSDU GitLab Tools -- Troubleshooting

Shared troubleshooting guide for osdu-activity, osdu-engagement, osdu-quality, and glab.

## Authentication

All OSDU CLI tools authenticate in this order:
1. `--token` command-line flag
2. `GITLAB_TOKEN` environment variable
3. `glab` CLI authentication (if installed)

Token needs `read_api` scope minimum. For glab write operations (MR create, comment), `api` scope.

```bash
# Set token
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx

# Or authenticate via glab
glab auth login --hostname community.opengroup.org

# Verify auth status
glab auth status
```

## Tool Installation

```bash
# glab: see setup skill

# osdu-activity
uv tool install osdu-activity --index-url https://community.opengroup.org/api/v4/projects/1629/packages/pypi/simple

# osdu-engagement
uv tool install osdu-engagement --index-url https://community.opengroup.org/api/v4/projects/1631/packages/pypi/simple

# osdu-quality
uv tool install osdu-quality --index-url https://community.opengroup.org/api/v4/projects/1630/packages/pypi/simple
```

Or run the `setup` skill to install all tools automatically.

## Common Issues (All Tools)

### 401 Unauthorized

Missing or expired token. Set `GITLAB_TOKEN` or authenticate via `glab auth login`.

### ANSI codes in output

Always pass `--output markdown` or `--output json`. Default `tty` includes ANSI codes
that break parsing. Never omit the flag.

### Slow response

Filter with `--project` to reduce scope, or lower `--limit`/`--days`/`--pipelines` count.

## osdu-activity Specific

### No MRs Found

Project has no open MRs (healthy state), or only draft MRs exist (excluded by default).
Include drafts with `--include-draft`.

### Failed Jobs Not Showing

Default table style shows summary counts. Use list style with job details:
```bash
osdu-activity mr --style list --show-jobs --output markdown
```

### Missing Pipeline Status on MRs

Pipeline hasn't started yet, or CI isn't configured for that branch.
Check pipeline directly: `osdu-activity pipeline --project <name> --output markdown`

### Provider Filter Not Working

Provider filter applies to job names within pipelines, not MRs directly. Works best
with `osdu-activity pipeline` and `osdu-quality analyze`.

## osdu-engagement Specific

### No Contributors Found

Time period too short, or project had no activity. Expand time range
(`--days 90` or `--days 180`) and remove project filter.

### Contribution Counts Seem Low

The CLI counts merged MRs. Open MRs (not yet merged) aren't included.
Check if MRs are still open with `osdu-activity mr`.

### No ADRs Found

Try without filters first (`osdu-engagement decision --output markdown`), then narrow.
Check for recent ADR activity with `--days 90`.

## osdu-quality Specific

### No Pipelines Found

Project has no recent pipeline activity, or filters are too restrictive.
Remove `--provider`/`--stage` filters and try again, or increase `--pipelines 50`.

### Inconsistent Pass Rates

Increase sample size (`--pipelines 30`) to smooth out variance. Compare providers
to isolate whether flakiness is environment-specific.

### Missing Test Results for a Stage

Not all projects run all test stages. Check what stages exist with:
```bash
osdu-quality status --project <name> --output markdown
```

## glab Specific

### SSL Errors

`x509: certificate signed by unknown authority` -- custom CA. Fix with:
```bash
git config --global http.sslCAInfo /path/to/cert.pem
```

### 404 on Valid Project

Check the full namespace path (groups can be nested). Verify with `git remote -v`.

### Wrong Instance

If commands return unexpected results, verify `git remote -v` points to the correct
instance (`community.opengroup.org` or `gitlab.opengroup.org`).

## Issue Trackers

- osdu-activity: https://community.opengroup.org/osdu/ui/ai-devops-agent/osdu-activity/-/issues
- osdu-engagement: https://community.opengroup.org/osdu/ui/ai-devops-agent/osdu-engagement/-/issues
- osdu-quality: https://community.opengroup.org/osdu/ui/ai-devops-agent/osdu-quality/-/issues
