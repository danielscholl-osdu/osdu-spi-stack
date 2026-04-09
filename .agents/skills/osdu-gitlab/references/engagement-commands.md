# OSDU Engagement CLI Reference

Complete command reference for the `osdu-engagement` CLI tool.

## Global Options

```
--version, -v    Show version and exit
--help, -h       Show help and exit
```

## Commands

### osdu-engagement contribution

Analyze code contributions across OSDU projects.

```
Usage: osdu-engagement contribution [OPTIONS] COMMAND [ARGS]...

Options:
  --days, -d INTEGER     Number of days to analyze [default: 30]
  --start-date TEXT      Start date (YYYY-MM-DD). Overrides --days
  --end-date TEXT        End date (YYYY-MM-DD). Defaults to today
  --project, -p TEXT     Filter to specific project (fuzzy matching)
  --output, -o TEXT      Output format: tty, json, markdown [default: tty]
  --output-dir TEXT      Directory for file output
  --token TEXT           GitLab token (or set GITLAB_TOKEN env var)
  --verbose              Show detailed progress
  --help, -h             Show this message and exit

Commands:
  trend    Historical contribution trend analysis
```

### osdu-engagement contribution trend

Historical contribution trend analysis.

```
Usage: osdu-engagement contribution trend [OPTIONS]

Options:
  --months INTEGER       Number of months to analyze
  --output, -o TEXT      Output format: tty, json, markdown [default: tty]
  --output-dir TEXT      Directory for file output
  --help, -h             Show this message and exit
```

### osdu-engagement decision

Analyze Architecture Decision Record (ADR) engagement.

```
Usage: osdu-engagement decision [OPTIONS]

Options:
  --days, -d INTEGER     Filter to ADRs with activity in last N days
  --start-date TEXT      Start date (YYYY-MM-DD)
  --end-date TEXT        End date (YYYY-MM-DD)
  --project, -p TEXT     Filter to specific project (fuzzy matching)
  --output, -o TEXT      Output format: tty, json, markdown [default: tty]
  --output-dir TEXT      Directory for file output
  --token TEXT           GitLab token (or set GITLAB_TOKEN env var)
  --verbose              Show detailed progress
  --help, -h             Show this message and exit
```

### osdu-engagement update

Check for and install updates from GitLab Package Registry.

```
Usage: osdu-engagement update [OPTIONS]

Options:
  --check-only    Only check for updates, don't install
  --help          Show this message and exit
```

## Date Filtering

```bash
osdu-engagement contribution --days 30     # Last 30 days
osdu-engagement contribution --days 90     # Last 90 days
osdu-engagement contribution --start-date 2025-01-01 --end-date 2025-01-14
```

`--start-date` overrides `--days` if both are provided.

## Metrics Explained

| Metric | Meaning |
|--------|---------|
| Merge Requests | Count of MRs created (feature/fix contribution) |
| Commits | Number of commits authored (code change volume) |
| Reviews | Number of MRs reviewed (code review participation) |
| Comments | Discussion participation in reviews |

## ADR Status Values

| Status | Meaning |
|--------|---------|
| `proposed` | Under discussion, not yet accepted |
| `accepted` | Approved and being implemented |
| `deprecated` | No longer relevant or superseded |
| `rejected` | Not accepted (rare) |

## Cloud Providers

Valid provider values: `azure`, `aws`, `gcp`, `ibm`, `cimpl` (Venus), `core` (shared tests)
