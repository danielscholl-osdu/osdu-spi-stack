# OSDU Quality CLI Reference

Complete command reference for the `osdu-quality` CLI tool.

## Global Options

```
--version, -v    Show version and exit
--help, -h       Show help and exit
```

## Commands

### osdu-quality analyze

Multi-project quality analysis. Analyzes test reliability across multiple pipelines,
detects flaky tests, calculates pass rates, and provides cloud provider metrics.

```
Usage: osdu-quality analyze [OPTIONS]

Options:
  --pipelines INTEGER    Number of pipelines to analyze per project [default: 10]
  --project TEXT         Specific project(s) to analyze (comma-separated)
  --output TEXT          Output format: tty (terminal), json, markdown [default: tty]
  --output-dir TEXT      Directory to save markdown reports
  --token TEXT           GitLab token (or use GITLAB_TOKEN env var, or glab auth)
  --stage TEXT           Filter by stage (unit, integration, acceptance)
  --provider TEXT        Filter by cloud provider (azure, aws, gcp, ibm, cimpl, core)
  --help, -h             Show this message and exit
```

**Examples:**

```bash
osdu-quality analyze --output markdown
osdu-quality analyze --project partition --output markdown
osdu-quality analyze --project partition,storage --output markdown
osdu-quality analyze --stage integration --output markdown
osdu-quality analyze --provider azure --output markdown
osdu-quality analyze --pipelines 20 --output markdown
```

### osdu-quality status

Latest test status by stage.

```
Usage: osdu-quality status [OPTIONS]

Options:
  --pipelines INTEGER    Number of pipelines to analyze per project [default: 10]
  --project TEXT         Specific project(s) to analyze (comma-separated)
  --output TEXT          Output format: tty, json, markdown [default: tty]
  --output-dir TEXT      Directory to save markdown reports
  --token TEXT           GitLab token (or use GITLAB_TOKEN env var, or glab auth)
  --venus / --no-venus   Show only CIMPL (Venus) provider jobs [default: no-venus]
  --no-release           Skip release tag rows (show only master/main branch)
  --help, -h             Show this message and exit
```

### osdu-quality tests

Detailed test results from pipeline jobs. Parses job logs for individual test results.

```
Usage: osdu-quality tests [OPTIONS]

Options:
  --project, -p TEXT     Project to analyze (required)
  --pipeline INTEGER     Specific pipeline ID [default: latest master pipeline]
  --output, -o TEXT      Output format: tty, json, markdown [default: tty]
  --output-dir TEXT      Directory for file output
  --token TEXT           GitLab token (or set GITLAB_TOKEN env var)
  --help, -h             Show this message and exit
```

### osdu-quality update

Check for and install updates from GitLab Package Registry.

```
Usage: osdu-quality update [OPTIONS]

Options:
  --check-only    Only check for updates, don't install
  --help          Show this message and exit
```

## Stages

Valid stage values: `unit`, `integration`, `acceptance`

## Cloud Providers

Valid provider values: `azure`, `aws`, `gcp`, `ibm`, `cimpl` (Venus), `core` (shared tests)
