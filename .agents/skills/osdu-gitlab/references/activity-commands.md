# OSDU Activity CLI Reference

Complete command reference for the `osdu-activity` CLI tool.

## Global Options

```
--version, -v    Show version and exit
--help           Show help and exit
```

## Commands

### osdu-activity mr

Show merge request report across OSDU projects.

```
Usage: osdu-activity mr [OPTIONS]

Options:
  --project, -p TEXT         Project(s) to analyze (comma-separated, fuzzy match)
  --provider TEXT            Filter jobs by provider: azure, aws, gcp, ibm, core
  --milestone, -m TEXT       Filter by milestone (fuzzy match supported)
  --state [opened|merged|closed|all]  MR state filter [default: opened]
  --user, -u TEXT            Filter by any user involvement (author, assignee, or reviewer)
  --author TEXT              Filter by MR author username
  --assignee TEXT            Filter by MR assignee username
  --reviewer TEXT            Filter by MR reviewer username
  --style, -s [table|list]   Display style [default: table]
  --output, -o [tty|json|markdown]  Output format [default: tty]
  --output-dir TEXT          Directory for file output
  --token TEXT               GitLab access token [env var: GITLAB_TOKEN]
  --include-draft            Include draft/WIP merge requests
  --show-jobs, -j            Show failed job details (list style only)
  --limit, -l INTEGER        Maximum items per project [default: 20]
  --help                     Show this message and exit
```

### osdu-activity pipeline

Show pipeline report across OSDU projects.

```
Usage: osdu-activity pipeline [OPTIONS]

Options:
  --project, -p TEXT         Project(s) to analyze (comma-separated, fuzzy match)
  --provider TEXT            Filter jobs by provider: azure, aws, gcp, ibm, core
  --style, -s [table|list]   Display style [default: table]
  --output, -o [tty|json|markdown]  Output format [default: tty]
  --output-dir TEXT          Directory for file output
  --token TEXT               GitLab access token [env var: GITLAB_TOKEN]
  --include-draft            Include pipelines from draft/WIP merge requests
  --limit, -l INTEGER        Maximum items per project [default: 20]
  --help                     Show this message and exit
```

### osdu-activity issue

Show issue report across OSDU projects.

```
Usage: osdu-activity issue [OPTIONS]

Options:
  --project, -p TEXT         Project(s) to analyze (comma-separated, fuzzy match)
  --provider TEXT            Filter jobs by provider
  --style, -s [table|list]   Display style [default: table]
  --output, -o [tty|json|markdown]  Output format [default: tty]
  --output-dir TEXT          Directory for file output
  --token TEXT               GitLab access token [env var: GITLAB_TOKEN]
  --limit, -l INTEGER        Maximum items per project [default: 50]
  --adr                      Show only ADR issues
  --help                     Show this message and exit
```

### osdu-activity update

Check for and install updates from GitLab Package Registry.

```
Usage: osdu-activity update [OPTIONS]

Options:
  --check-only       Only check for updates, don't install
  --force            Force reinstall even if up to date
  --token TEXT       GitLab access token [env var: GITLAB_TOKEN]
  --help             Show this message and exit
```

## Display Styles

| Style | Description |
|-------|-------------|
| `table` | Summary view with counts and status (default) |
| `list` | Detailed view with individual items |

## Filtering Tips

- Combine filters: `osdu-activity mr --project partition --provider azure --output markdown`
- Fuzzy matching: `--project idx` matches indexer-service, indexer-queue
- Draft MRs excluded by default -- use `--include-draft` to include them
- Milestone fuzzy match: `--milestone M26` matches "M26", "Milestone 26", "m26"
- Projects can be comma-separated: `--project partition,storage,search`

## Cloud Providers

Valid provider values: `azure`, `aws`, `gcp`, `ibm`, `cimpl` (Venus), `core` (shared tests)
