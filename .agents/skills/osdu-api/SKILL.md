---
name: osdu-api
description: >-
  OSDU platform API access for SPI Stack deployments via the Istio gateway
  and Azure Entra ID authentication. Use when the user asks to query OSDU records,
  search data, list schemas, check entitlements, manage legal tags, interact
  with storage, or test OSDU API endpoints. Handles connection setup,
  authentication, and API calls through a single helper script.
  Not for: GitLab operations, MR monitoring, test reliability, or contributor
  analysis (use osdu-gitlab).
triggers:
  - "query OSDU"
  - "search records"
  - "list schemas"
  - "check entitlements"
  - "legal tags"
  - "OSDU API"
  - "connect to OSDU"
  - "call API"
compatibility: Requires kubectl with SPI Stack cluster access, az CLI with active login. Python 3.11+ and uv.
---

# OSDU API

Access OSDU platform APIs on SPI Stack deployments. Uses the Istio gateway
endpoint and Azure Entra ID for authentication (no port-forwarding needed).

## Quick Start

```bash
# 1. Connect (discovers gateway endpoint, gets Azure token)
uv run .agents/skills/osdu-api/scripts/osdu.py connect

# 2. List discovered services
uv run .agents/skills/osdu-api/scripts/osdu.py services

# 3. Probe all services for version info
uv run .agents/skills/osdu-api/scripts/osdu.py services --probe

# 4. Make API calls (path-based routing via gateway)
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/entitlements/v2/groups
uv run .agents/skills/osdu-api/scripts/osdu.py call POST /api/search/v2/query \
  -d '{"kind":"*:*:*:*","query":"*","limit":10}'

# 5. Call any service by name
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/unit/v3/info --service unit

# 6. Disconnect when done
uv run .agents/skills/osdu-api/scripts/osdu.py disconnect
```

## Connection Management

```bash
# Discover gateway endpoint and authenticate with Azure
uv run .agents/skills/osdu-api/scripts/osdu.py connect

# List all discovered OSDU services
uv run .agents/skills/osdu-api/scripts/osdu.py services

# Probe all services and report versions
uv run .agents/skills/osdu-api/scripts/osdu.py services --probe

# Check connection health and token TTL
uv run .agents/skills/osdu-api/scripts/osdu.py status

# Print raw access token (useful for manual curl)
uv run .agents/skills/osdu-api/scripts/osdu.py token

# Clean up state
uv run .agents/skills/osdu-api/scripts/osdu.py disconnect
```

The `connect` command uses `uv run spi info` to discover the gateway endpoint,
then gets an Azure access token via `az account get-access-token`.
No port-forwarding needed -- all traffic routes through the Istio gateway.

## Making API Calls

```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call <METHOD> <PATH> [OPTIONS]
```

| Option | Description | Example |
|--------|-------------|---------|
| `-d`, `--data` | JSON request body | `-d '{"kind":"*:*:*:*"}'` |
| `-q`, `--query` | Query string parameters | `-q 'limit=10&offset=0'` |
| `-p`, `--partition` | Override data partition (default: osdu) | `-p opendes` |
| `-s`, `--service` | Target service by name (bypasses path routing) | `-s unit` |

The script automatically:
- Routes requests through the Istio gateway (all services share one endpoint)
- Acquires/refreshes the Azure Entra ID token
- Sets `Authorization`, `data-partition-id`, and `Content-Type` headers
- Retries once on 401 (token refresh)

## Service Endpoints

All services are accessible through the gateway. The table below lists common services
with their API path prefixes.

| Service | Base Path | Key Operations |
|---------|-----------|----------------|
| Storage | `/api/storage/v2` | `GET /records/{id}`, `PUT /records`, `POST /query/records` |
| Search | `/api/search/v2` | `POST /query` |
| Legal | `/api/legal/v1` | `GET /legaltags`, `POST /legaltags` |
| Schema | `/api/schema-service/v1` | `GET /schema`, `GET /schema/{id}` |
| Entitlements | `/api/entitlements/v2` | `GET /groups`, `GET /members/{group}` |
| Partition | `/api/partition/v1` | `GET /partitions`, `GET /partitions/{id}` |
| File | `/api/file/v2` | `POST /files/uploadURL`, `GET /files/{id}` |
| Workflow | `/api/workflow/v1` | `GET /workflow`, `POST /workflow/{name}/workflowRun` |
| Indexer | `/api/indexer/v2` | `POST /reindex` |

## Common Operations

### Search for records
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call POST /api/search/v2/query \
  -d '{"kind":"*:*:*:*","query":"*","limit":10}'
```

### Get a specific record
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/storage/v2/records/{RECORD_ID}
```

### List schemas
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/schema-service/v1/schema \
  -q 'authority=osdu&limit=20'
```

### List legal tags
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/legal/v1/legaltags
```

### Check my entitlements
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/entitlements/v2/groups
```

### List partitions
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/partition/v1/partitions
```

### Health check (per service)
```bash
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/storage/v2/info
uv run .agents/skills/osdu-api/scripts/osdu.py call GET /api/search/v2/info
```

## Error Recovery

| Error | Cause | Fix |
|-------|-------|-----|
| "Not connected" | No state file | Run `connect` |
| "Gateway not found" | SPI Stack not deployed | Deploy with `uv run spi up` |
| 401 Unauthorized | Token expired (auto-retries once) | If persistent, `disconnect` then `connect` |
| 403 Forbidden | Insufficient permissions | Check entitlements groups |
| "az not authenticated" | Azure CLI not logged in | Run `az login` |

## Deep Reference

For full API details beyond this quick reference, see:
- [API Reference](references/api-reference.md) -- all endpoints, parameters, request/response schemas
- [Search Patterns](references/search-patterns.md) -- Elasticsearch query syntax and examples
- [Record Lifecycle](references/record-lifecycle.md) -- create, update, delete workflows with ACLs and legal tags
