---
name: osdu-test
description: >-
  Run Java integration tests against a live SPI Stack environment. Handles
  environment resolution from the running cluster, Azure Entra ID auth,
  test pattern detection (Azure provider tests preferred), Surefire result
  parsing. Use when the user asks to test a service, verify the deployment,
  or run integration tests.
  Not for: unit tests, acceptance tests, or testing without a live cluster.
triggers:
  - "integration test"
  - "run tests against"
  - "test partition"
  - "test storage"
  - "test legal"
  - "test the environment"
  - "verify the deployment"
  - "run tests"
compatibility: Requires java 17+, mvn, uv, az CLI with active login. Cloned service repos in workspace.
---

# OSDU Integration Tests

Run Java integration tests from cloned OSDU service repositories against a live
SPI Stack environment.

## Key Differences from Acceptance Tests

SPI Stack uses the Azure provider variant of OSDU services. The integration tests
live in `testing/*-test-azure/` directories (Pattern B), not in standalone
acceptance test modules. Auth is via Azure Entra ID, not Keycloak OIDC.

| Aspect | Acceptance (cloud-agnostic) | Integration (SPI) |
|--------|-------------------|-------------------|
| Test module | `*-acceptance-test/` | `testing/*-test-azure/` |
| Auth | Keycloak OIDC | Azure Entra ID |
| Pattern priority | A first, B fallback | B first, A fallback |
| SSL truststore | Required (self-signed) | Not needed (Azure TLS) |
| Env resolution | `cimpl info --json` | `spi info --json` |

## Step 1: Locate the Service Repository

The service must be cloned in the workspace (use the `clone` skill first).

```bash
# Clone the service if not already present
uv run .agents/skills/clone/scripts/clone.py \
  https://community.opengroup.org/osdu/platform/system/partition.git
```

The script searches for the service in `$OSDU_WORKSPACE` or `./workspace`:
- Worktree layout: `workspace/<service>/master/`
- Flat clone: `workspace/<service>/`

## Step 2: Dry Run First

Always verify configuration before executing tests:

```bash
uv run .agents/skills/osdu-test/scripts/javatest_integration.py \
  --service partition --dry-run
```

The dry run shows:
- Resolved environment (gateway endpoint, tenant, auth method)
- Detected test pattern (A or B) and test module path
- Environment variable mapping (all vars the tests need)
- Maven commands that would execute

## Step 3: Execute Tests

```bash
uv run .agents/skills/osdu-test/scripts/javatest_integration.py \
  --service partition
```

### Options

| Flag | Description | Example |
|------|-------------|---------|
| `--service` | OSDU service name (required) | `--service storage` |
| `--endpoint` | Override OSDU endpoint URL | `--endpoint https://my.gateway.ip` |
| `--workspace` | Override workspace path | `--workspace /path/to/workspace` |
| `--pattern` | Force test pattern (A or B) | `--pattern B` |
| `--dry-run` | Show config without executing | `--dry-run` |

## Step 4: Interpret Results

The script parses Surefire XML reports and outputs structured results:

```
Integration Tests: partition
Test Module: partition-test-azure (Pattern B)
Environment: https://10.0.0.1
Duration: 45.2s
Status: PASSED

  Test Class                                    Result   Time
  --------------------------------------------- -------- ------
  PartitionServiceTest#createPartition           PASS     2.3s
  PartitionServiceTest#getPartition              PASS     1.1s
  ...

Tests: 12 passed, 0 failed, 0 errors, 0 skipped
```

## Test Pattern Detection

### Pattern B: Azure Provider Tests (Preferred for SPI)

Located at `testing/<service>-test-azure/`. These tests are designed for the
Azure provider and expect Azure-specific environment variables.

If a `testing/<service>-test-core/` module exists, it is built first as a
dependency.

### Pattern A: Acceptance Tests (Fallback)

Located at `<service>-acceptance-test/`. These use OIDC credentials and are
the primary pattern for cloud-agnostic deployments. Used as fallback if
Pattern B is not available.

## Environment Resolution

The script resolves the test environment automatically from the running SPI
Stack cluster:

1. Runs `uv run spi info --json --show-secrets` to get endpoints and config
2. Gets an Azure access token via `az account get-access-token`
3. Maps cluster values to the env vars each test expects (discovered by
   scanning Java source for `System.getenv()` calls)

### Azure Auth Variables

Instead of Keycloak OIDC credentials, the script provides Azure identity:

| Variable | Source |
|----------|--------|
| `AZURE_AD_TENANT_ID` | From `spi info` (Azure tenant) |
| `AZURE_AD_APP_RESOURCE_ID` | From `spi info` (managed identity client ID) |
| `AZURE_TESTER_SERVICEPRINCIPAL_SECRET` | Azure CLI access token |
| `INTEGRATION_TESTER` | From `spi info` or az CLI |
| `NO_DATA_ACCESS_TESTER` | Same as integration tester |
| `DATA_PARTITION_ID` | From `spi info` (partition name) |

## Supported Services

partition, entitlements, legal, schema, storage, search, indexer, file, workflow,
unit, crs-catalog, crs-conversion

## Multi-Service Testing

Run tests for multiple services sequentially:

```bash
for svc in partition entitlements legal storage search; do
  uv run .agents/skills/osdu-test/scripts/javatest_integration.py --service $svc
done
```

## Error Handling

| Error | Cause | Fix |
|-------|-------|-----|
| Service not found | Not cloned | Use `clone` skill first |
| No test module found | Service lacks azure tests | Try `--pattern A` |
| Cannot resolve environment | Cluster not running | Run `uv run spi status` |
| Azure auth failed | Not logged in | Run `az login` |
| Maven build failed | Dependency issues | Check `mvn --version`, try building from service root first |
