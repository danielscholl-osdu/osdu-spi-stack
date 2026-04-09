# Copyright 2026, Microsoft
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Azure PaaS infrastructure provisioning via az CLI.

Creates all Azure resources required by the OSDU SPI stack:
  - AKS Automatic cluster
  - User-assigned managed identity + federated credentials
  - Key Vault
  - CosmosDB (Gremlin for entitlements, SQL per partition)
  - Service Bus (per partition, 14 topics)
  - Storage Accounts (common + per partition)
  - Role assignments (RBAC)
  - Key Vault secrets
"""

import json
from typing import Optional

from .config import Config
from .helpers import console, run_command, display_result


# ──────────────────────────────────────────────
# CosmosDB container definitions (from osdu-spi-infra)
# ──────────────────────────────────────────────

OSDU_DB_CONTAINERS = {
    "Authority": "/id",
    "EntityType": "/id",
    "FileLocationEntity": "/id",
    "IngestionStrategy": "/workflowType",
    "LegalTag": "/id",
    "MappingInfo": "/sourceSchemaKind",
    "RegisterAction": "/dataPartitionId",
    "RegisterDdms": "/dataPartitionId",
    "RegisterSubscription": "/dataPartitionId",
    "RelationshipStatus": "/id",
    "ReplayStatus": "/id",
    "SchemaInfo": "/partitionId",
    "Source": "/id",
    "StorageRecord": "/id",
    "StorageSchema": "/kind",
    "TenantInfo": "/id",
    "UserInfo": "/id",
    "Workflow": "/workflowId",
    "WorkflowCustomOperatorInfo": "/operatorId",
    "WorkflowCustomOperatorV2": "/partitionKey",
    "WorkflowRun": "/partitionKey",
    "WorkflowRunV2": "/partitionKey",
    "WorkflowRunStatus": "/partitionKey",
    "WorkflowV2": "/partitionKey",
}

OSDU_SYSTEM_DB_CONTAINERS = {
    "Authority": "/id",
    "EntityType": "/id",
    "SchemaInfo": "/partitionId",
    "Source": "/id",
    "WorkflowV2": "/partitionKey",
}

# Service Bus topics (from osdu-spi-infra locals.tf)
SERVICEBUS_TOPICS = {
    "indexing-progress": {
        "max_size": 1024,
        "subscriptions": {"indexing-progresssubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "legaltags": {
        "max_size": 1024,
        "subscriptions": {"legaltagssubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "recordstopic": {
        "max_size": 1024,
        "subscriptions": {
            "recordstopicsubscription": {"max_delivery": 5, "lock_duration": "PT5M"},
            "wkssubscription": {"max_delivery": 5, "lock_duration": "PT5M"},
        },
    },
    "recordstopicdownstream": {
        "max_size": 1024,
        "subscriptions": {"downstreamsub": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "recordstopiceg": {
        "max_size": 1024,
        "subscriptions": {"eg_sb_wkssubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "schemachangedtopic": {
        "max_size": 1024,
        "subscriptions": {"schemachangedtopicsubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "schemachangedtopiceg": {
        "max_size": 1024,
        "subscriptions": {"eg_sb_schemasubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "legaltagschangedtopiceg": {
        "max_size": 1024,
        "subscriptions": {"eg_sb_legaltagssubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "statuschangedtopic": {
        "max_size": 5120,
        "subscriptions": {"statuschangedtopicsubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "statuschangedtopiceg": {
        "max_size": 1024,
        "subscriptions": {"eg_sb_statussubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "recordstopic-v2": {
        "max_size": 1024,
        "subscriptions": {"recordstopic-v2-subscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "reindextopic": {
        "max_size": 1024,
        "subscriptions": {"reindextopicsubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
    "entitlements-changed": {
        "max_size": 1024,
        "subscriptions": {},
    },
    "replaytopic": {
        "max_size": 1024,
        "subscriptions": {"replaytopicsubscription": {"max_delivery": 5, "lock_duration": "PT5M"}},
    },
}

COMMON_STORAGE_CONTAINERS = [
    "system", "azure-webjobs-hosts", "azure-webjobs-eventhub",
    "airflow-logs", "airflow-dags",
    "share-unit", "share-crs", "share-crs-conversion",
]

PARTITION_STORAGE_CONTAINERS = [
    "legal-service-azure-configuration", "osdu-wks-mappings",
    "wdms-osdu", "file-staging-area", "file-persistent-area",
]

FEDERATED_CREDENTIAL_NAMESPACES = [
    "default", "osdu-core", "airflow", "osdu-system",
    "osdu-auth", "osdu-reference", "osdu", "platform",
]


# ──────────────────────────────────────────────
# Helper: safe name generation
# ──────────────────────────────────────────────

def _storage_name(prefix: str, env: str) -> str:
    """Generate a storage account name (lowercase alphanumeric, 3-24 chars)."""
    safe = (prefix + env).replace("-", "").replace("_", "").lower()
    return safe[:24]


def _sb_name(partition: str, env: str) -> str:
    """Generate a service bus namespace name."""
    return f"osdu-{env}-{partition}-sb"[:50]


def _cosmos_sql_name(partition: str, env: str) -> str:
    return f"osdu-{env}-{partition}-cosmos"[:44]


def _cosmos_gremlin_name(env: str) -> str:
    return f"osdu-{env}-graph"[:44]


# ──────────────────────────────────────────────
# Phase 1: Core infrastructure
# ──────────────────────────────────────────────

def create_resource_group(config: Config):
    console.print("\n[bold]Creating resource group...[/bold]")
    run_command(
        ["az", "group", "create",
         "--name", config.resource_group,
         "--location", config.location,
         "--output", "json"],
        description=f"Create resource group: {config.resource_group}",
    )
    display_result(f"Resource group {config.resource_group} ready")


def _aks_exists(config: Config) -> bool:
    result = run_command(
        ["az", "aks", "show",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--output", "json"],
        description=f"Check for existing cluster: {config.cluster_name}",
        check=False,
        display=False,
    )
    return result.returncode == 0


def create_aks_automatic(config: Config):
    """Create an AKS Automatic cluster."""
    if _aks_exists(config):
        console.print(f"\n[warning]AKS cluster '{config.cluster_name}' already exists. Using it.[/warning]")
    else:
        console.print("\n[bold]Creating AKS Automatic cluster (this takes ~10 minutes)...[/bold]")
        run_command(
            ["az", "aks", "create",
             "--resource-group", config.resource_group,
             "--name", config.cluster_name,
             "--location", config.location,
             "--sku", "automatic",
             "--no-ssh-key",
             "--output", "json"],
            description=f"Create AKS Automatic: {config.cluster_name}",
        )
    display_result(f"AKS Automatic cluster {config.cluster_name} ready")

    console.print("\n[bold]Fetching cluster credentials...[/bold]")
    run_command(
        ["az", "aks", "get-credentials",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--overwrite-existing"],
        description="Merge kubeconfig",
    )


def create_managed_identity(config: Config) -> dict:
    """Create user-assigned managed identity, return identity info."""
    console.print("\n[bold]Creating managed identity...[/bold]")
    result = run_command(
        ["az", "identity", "create",
         "--name", config.identity_name,
         "--resource-group", config.resource_group,
         "--location", config.location,
         "--output", "json"],
        description=f"Create identity: {config.identity_name}",
    )
    identity = json.loads(result.stdout)
    display_result(f"Managed identity {config.identity_name} ready")
    return identity


def create_key_vault(config: Config) -> dict:
    """Create Key Vault with RBAC authorization."""
    console.print("\n[bold]Creating Key Vault...[/bold]")
    result = run_command(
        ["az", "keyvault", "create",
         "--name", config.keyvault_name,
         "--resource-group", config.resource_group,
         "--location", config.location,
         "--enable-rbac-authorization",
         "--output", "json"],
        description=f"Create Key Vault: {config.keyvault_name}",
    )
    kv = json.loads(result.stdout)
    display_result(f"Key Vault {config.keyvault_name} ready")
    return kv


def create_acr(config: Config) -> dict:
    """Create Azure Container Registry."""
    console.print("\n[bold]Creating Container Registry...[/bold]")
    result = run_command(
        ["az", "acr", "create",
         "--name", config.acr_name,
         "--resource-group", config.resource_group,
         "--sku", "Basic",
         "--output", "json"],
        description=f"Create ACR: {config.acr_name}",
    )
    acr = json.loads(result.stdout)
    display_result(f"ACR {config.acr_name} ready")
    return acr


# ──────────────────────────────────────────────
# Phase 2: Data infrastructure
# ──────────────────────────────────────────────

def create_cosmos_gremlin(config: Config) -> dict:
    """Create CosmosDB Gremlin account for entitlements graph."""
    name = _cosmos_gremlin_name(config.env)
    console.print(f"\n[bold]Creating CosmosDB Gremlin account: {name}...[/bold]")
    result = run_command(
        ["az", "cosmosdb", "create",
         "--name", name,
         "--resource-group", config.resource_group,
         "--capabilities", "EnableGremlin",
         "--default-consistency-level", "Session",
         "--locations", f"regionName={config.location}", "failoverPriority=0", "isZoneRedundant=false",
         "--output", "json"],
        description=f"Create CosmosDB Gremlin: {name}",
    )
    account = json.loads(result.stdout)

    # Create database and graph
    run_command(
        ["az", "cosmosdb", "gremlin", "database", "create",
         "--account-name", name,
         "--resource-group", config.resource_group,
         "--name", "osdu-graph",
         "--output", "json"],
        description="Create Gremlin database: osdu-graph",
    )
    run_command(
        ["az", "cosmosdb", "gremlin", "graph", "create",
         "--account-name", name,
         "--resource-group", config.resource_group,
         "--database-name", "osdu-graph",
         "--name", "Entitlements",
         "--partition-key-path", "/dataPartitionId",
         "--max-throughput", "4000",
         "--output", "json"],
        description="Create Gremlin graph: Entitlements",
    )
    display_result(f"CosmosDB Gremlin {name} ready")
    return account


def create_cosmos_sql(config: Config, partition: str) -> dict:
    """Create CosmosDB SQL account for a partition."""
    name = _cosmos_sql_name(partition, config.env)
    console.print(f"\n[bold]Creating CosmosDB SQL account: {name} (partition: {partition})...[/bold]")
    result = run_command(
        ["az", "cosmosdb", "create",
         "--name", name,
         "--resource-group", config.resource_group,
         "--default-consistency-level", "Session",
         "--locations", f"regionName={config.location}", "failoverPriority=0", "isZoneRedundant=false",
         "--output", "json"],
        description=f"Create CosmosDB SQL: {name}",
    )
    account = json.loads(result.stdout)

    # Create osdu-db database
    run_command(
        ["az", "cosmosdb", "sql", "database", "create",
         "--account-name", name,
         "--resource-group", config.resource_group,
         "--name", "osdu-db",
         "--max-throughput", "4000",
         "--output", "json"],
        description=f"Create SQL database: osdu-db",
    )

    # Create containers
    for container, pk in OSDU_DB_CONTAINERS.items():
        run_command(
            ["az", "cosmosdb", "sql", "container", "create",
             "--account-name", name,
             "--resource-group", config.resource_group,
             "--database-name", "osdu-db",
             "--name", container,
             "--partition-key-path", pk,
             "--output", "json"],
            description=f"Create container: {container}",
            display=False,
        )

    # Create system database (only for primary partition)
    if partition == config.primary_partition:
        run_command(
            ["az", "cosmosdb", "sql", "database", "create",
             "--account-name", name,
             "--resource-group", config.resource_group,
             "--name", "osdu-system-db",
             "--max-throughput", "4000",
             "--output", "json"],
            description="Create SQL database: osdu-system-db",
        )
        for container, pk in OSDU_SYSTEM_DB_CONTAINERS.items():
            run_command(
                ["az", "cosmosdb", "sql", "container", "create",
                 "--account-name", name,
                 "--resource-group", config.resource_group,
                 "--database-name", "osdu-system-db",
                 "--name", container,
                 "--partition-key-path", pk,
                 "--output", "json"],
                description=f"Create system container: {container}",
                display=False,
            )

    display_result(f"CosmosDB SQL {name} ready ({len(OSDU_DB_CONTAINERS)} containers)")
    return account


def create_service_bus(config: Config, partition: str) -> dict:
    """Create Service Bus namespace with topics and subscriptions."""
    name = _sb_name(partition, config.env)
    console.print(f"\n[bold]Creating Service Bus: {name} (partition: {partition})...[/bold]")
    result = run_command(
        ["az", "servicebus", "namespace", "create",
         "--name", name,
         "--resource-group", config.resource_group,
         "--location", config.location,
         "--sku", "Standard",
         "--output", "json"],
        description=f"Create Service Bus: {name}",
    )
    ns = json.loads(result.stdout)

    for topic_name, topic_spec in SERVICEBUS_TOPICS.items():
        run_command(
            ["az", "servicebus", "topic", "create",
             "--namespace-name", name,
             "--resource-group", config.resource_group,
             "--name", topic_name,
             "--max-size", str(topic_spec["max_size"]),
             "--output", "json"],
            description=f"Create topic: {topic_name}",
            display=False,
        )
        for sub_name, sub_spec in topic_spec["subscriptions"].items():
            run_command(
                ["az", "servicebus", "topic", "subscription", "create",
                 "--namespace-name", name,
                 "--resource-group", config.resource_group,
                 "--topic-name", topic_name,
                 "--name", sub_name,
                 "--max-delivery-count", str(sub_spec["max_delivery"]),
                 "--lock-duration", sub_spec["lock_duration"],
                 "--output", "json"],
                description=f"Create subscription: {sub_name}",
                display=False,
            )

    display_result(f"Service Bus {name} ready ({len(SERVICEBUS_TOPICS)} topics)")
    return ns


def create_storage_accounts(config: Config) -> dict:
    """Create common and partition storage accounts."""
    results = {}

    # Common storage account
    common_name = _storage_name("osdu" + config.env + "common", "")
    console.print(f"\n[bold]Creating common storage account: {common_name}...[/bold]")
    result = run_command(
        ["az", "storage", "account", "create",
         "--name", common_name,
         "--resource-group", config.resource_group,
         "--location", config.location,
         "--sku", "Standard_LRS",
         "--kind", "StorageV2",
         "--output", "json"],
        description=f"Create storage: {common_name}",
    )
    results["common"] = json.loads(result.stdout)
    results["common_name"] = common_name

    # Get account key for container/table creation
    key_result = run_command(
        ["az", "storage", "account", "keys", "list",
         "--account-name", common_name,
         "--resource-group", config.resource_group,
         "--query", "[0].value",
         "--output", "tsv"],
        description="Get storage key",
        display=False,
    )
    common_key = key_result.stdout.strip()

    # Create common containers
    for container in COMMON_STORAGE_CONTAINERS:
        run_command(
            ["az", "storage", "container", "create",
             "--name", container,
             "--account-name", common_name,
             "--account-key", common_key,
             "--output", "json"],
            description=f"Create container: {container}",
            display=False,
        )

    # Create partitionInfo table
    run_command(
        ["az", "storage", "table", "create",
         "--name", "partitionInfo",
         "--account-name", common_name,
         "--account-key", common_key,
         "--output", "json"],
        description="Create table: partitionInfo",
        display=False,
    )
    display_result(f"Common storage {common_name} ready")

    # Partition storage accounts
    for partition in config.data_partitions:
        part_name = _storage_name("osdu" + config.env + partition, "")
        console.print(f"\n[bold]Creating partition storage: {part_name}...[/bold]")
        result = run_command(
            ["az", "storage", "account", "create",
             "--name", part_name,
             "--resource-group", config.resource_group,
             "--location", config.location,
             "--sku", "Standard_LRS",
             "--kind", "StorageV2",
             "--output", "json"],
            description=f"Create storage: {part_name}",
        )
        results[partition] = json.loads(result.stdout)
        results[f"{partition}_name"] = part_name

        pk_result = run_command(
            ["az", "storage", "account", "keys", "list",
             "--account-name", part_name,
             "--resource-group", config.resource_group,
             "--query", "[0].value",
             "--output", "tsv"],
            display=False,
            description="Get partition storage key",
        )
        part_key = pk_result.stdout.strip()

        for container in PARTITION_STORAGE_CONTAINERS:
            run_command(
                ["az", "storage", "container", "create",
                 "--name", container,
                 "--account-name", part_name,
                 "--account-key", part_key,
                 "--output", "json"],
                description=f"Create container: {container}",
                display=False,
            )
        display_result(f"Partition storage {part_name} ready")

    return results


# ──────────────────────────────────────────────
# Phase 3: Identity and access
# ──────────────────────────────────────────────

def get_aks_oidc_issuer(config: Config) -> str:
    """Get the OIDC issuer URL for the AKS cluster."""
    result = run_command(
        ["az", "aks", "show",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--query", "oidcIssuerProfile.issuerUrl",
         "--output", "tsv"],
        description="Get AKS OIDC issuer URL",
        display=False,
    )
    return result.stdout.strip()


def create_federated_credentials(config: Config, identity_name: str, oidc_issuer: str):
    """Create federated identity credentials for each namespace."""
    console.print("\n[bold]Creating federated identity credentials...[/bold]")
    for ns in FEDERATED_CREDENTIAL_NAMESPACES:
        cred_name = f"federated-ns-{ns}"
        subject = f"system:serviceaccount:{ns}:workload-identity-sa"
        run_command(
            ["az", "identity", "federated-credential", "create",
             "--name", cred_name,
             "--identity-name", identity_name,
             "--resource-group", config.resource_group,
             "--issuer", oidc_issuer,
             "--subject", subject,
             "--audiences", "api://AzureADTokenExchange",
             "--output", "json"],
            description=f"Federated credential: {ns}",
            display=False,
        )
    display_result(f"Federated credentials created ({len(FEDERATED_CREDENTIAL_NAMESPACES)} namespaces)")


def assign_roles(config: Config, identity_principal_id: str, resource_ids: dict):
    """Assign RBAC roles to the managed identity."""
    console.print("\n[bold]Assigning RBAC roles...[/bold]")

    assignments = []

    # Key Vault Secrets User
    if "keyvault" in resource_ids:
        assignments.append(("Key Vault Secrets User", resource_ids["keyvault"]))

    # Storage Blob Data Contributor on common storage
    if "common_storage" in resource_ids:
        assignments.append(("Storage Blob Data Contributor", resource_ids["common_storage"]))
        assignments.append(("Storage Table Data Contributor", resource_ids["common_storage"]))

    # Per-partition storage and service bus
    for partition in config.data_partitions:
        if f"{partition}_storage" in resource_ids:
            assignments.append(("Storage Blob Data Contributor", resource_ids[f"{partition}_storage"]))
        if f"{partition}_servicebus" in resource_ids:
            assignments.append(("Azure Service Bus Data Sender", resource_ids[f"{partition}_servicebus"]))
            assignments.append(("Azure Service Bus Data Receiver", resource_ids[f"{partition}_servicebus"]))

    # ACR Pull
    if "acr" in resource_ids:
        assignments.append(("AcrPull", resource_ids["acr"]))

    for role, scope in assignments:
        run_command(
            ["az", "role", "assignment", "create",
             "--role", role,
             "--assignee-object-id", identity_principal_id,
             "--assignee-principal-type", "ServicePrincipal",
             "--scope", scope,
             "--output", "json"],
            description=f"Assign: {role}",
            display=False,
            check=False,  # Idempotent; may already exist
        )

    display_result(f"RBAC roles assigned ({len(assignments)} assignments)")


def populate_keyvault_secrets(config: Config, infra_outputs: dict):
    """Store Azure PaaS connection info in Key Vault."""
    console.print("\n[bold]Populating Key Vault secrets...[/bold]")

    secrets = {
        "tenant-id": infra_outputs.get("tenant_id", ""),
        "subscription-id": infra_outputs.get("subscription_id", ""),
        "osdu-identity-id": infra_outputs.get("identity_client_id", ""),
        "keyvault-uri": infra_outputs.get("keyvault_uri", ""),
        "system-storage": infra_outputs.get("common_storage_name", ""),
        "app-dev-sp-username": infra_outputs.get("identity_client_id", ""),
        "app-dev-sp-password": "DISABLED",
        "app-dev-sp-tenant-id": infra_outputs.get("tenant_id", ""),
        "app-dev-sp-id": infra_outputs.get("identity_client_id", ""),
    }

    # Graph DB secrets
    if "graph_endpoint" in infra_outputs:
        secrets["graph-db-endpoint"] = infra_outputs["graph_endpoint"]
    if "graph_primary_key" in infra_outputs:
        secrets["graph-db-primary-key"] = infra_outputs["graph_primary_key"]

    # Per-partition secrets
    for partition in config.data_partitions:
        prefix = partition
        if f"{partition}_storage_name" in infra_outputs:
            secrets[f"{prefix}-storage"] = infra_outputs[f"{partition}_storage_name"]
        if f"{partition}_cosmos_endpoint" in infra_outputs:
            secrets[f"{prefix}-cosmos-endpoint"] = infra_outputs[f"{partition}_cosmos_endpoint"]
        if f"{partition}_cosmos_primary_key" in infra_outputs:
            secrets[f"{prefix}-cosmos-primary-key"] = infra_outputs[f"{partition}_cosmos_primary_key"]
        if f"{partition}_sb_namespace" in infra_outputs:
            secrets[f"{prefix}-sb-namespace"] = infra_outputs[f"{partition}_sb_namespace"]

    for name, value in secrets.items():
        if value:
            run_command(
                ["az", "keyvault", "secret", "set",
                 "--vault-name", config.keyvault_name,
                 "--name", name,
                 "--value", value,
                 "--output", "json"],
                description=f"Set secret: {name}",
                display=False,
            )

    display_result(f"Key Vault secrets populated ({len([v for v in secrets.values() if v])} secrets)")


# ──────────────────────────────────────────────
# Orchestrator: provision all Azure infrastructure
# ──────────────────────────────────────────────

def provision_azure_infra(config: Config) -> dict:
    """Provision all Azure PaaS resources. Returns infra outputs for K8s bootstrap."""
    outputs = {}

    # Get current subscription info
    console.print("\n[bold]Verifying Azure login...[/bold]")
    result = run_command(
        ["az", "account", "show", "--output", "json"],
        description="Check Azure subscription",
    )
    account = json.loads(result.stdout)
    outputs["tenant_id"] = account.get("tenantId", "")
    outputs["subscription_id"] = account.get("id", "")
    console.print(f"  [info]Subscription: {account.get('name', 'unknown')} ({account.get('id', '')})[/info]")

    # Phase 1: Core infrastructure
    create_resource_group(config)
    create_aks_automatic(config)

    identity = create_managed_identity(config)
    outputs["identity_client_id"] = identity.get("clientId", "")
    outputs["identity_principal_id"] = identity.get("principalId", "")
    outputs["identity_id"] = identity.get("id", "")

    kv = create_key_vault(config)
    outputs["keyvault_uri"] = kv.get("properties", {}).get("vaultUri", "")
    outputs["keyvault_id"] = kv.get("id", "")

    acr = create_acr(config)
    outputs["acr_id"] = acr.get("id", "")

    # Phase 2: Data infrastructure
    gremlin = create_cosmos_gremlin(config)
    outputs["graph_endpoint"] = gremlin.get("documentEndpoint", "")
    # Get Gremlin primary key
    gremlin_keys = run_command(
        ["az", "cosmosdb", "keys", "list",
         "--name", _cosmos_gremlin_name(config.env),
         "--resource-group", config.resource_group,
         "--output", "json"],
        description="Get Gremlin keys",
        display=False,
    )
    gk = json.loads(gremlin_keys.stdout)
    outputs["graph_primary_key"] = gk.get("primaryMasterKey", "")

    for partition in config.data_partitions:
        cosmos = create_cosmos_sql(config, partition)
        outputs[f"{partition}_cosmos_endpoint"] = cosmos.get("documentEndpoint", "")
        # Get SQL primary key
        sql_keys = run_command(
            ["az", "cosmosdb", "keys", "list",
             "--name", _cosmos_sql_name(partition, config.env),
             "--resource-group", config.resource_group,
             "--output", "json"],
            description=f"Get CosmosDB keys for {partition}",
            display=False,
        )
        sk = json.loads(sql_keys.stdout)
        outputs[f"{partition}_cosmos_primary_key"] = sk.get("primaryMasterKey", "")

        sb = create_service_bus(config, partition)
        sb_name = _sb_name(partition, config.env)
        outputs[f"{partition}_sb_namespace"] = sb_name

    storage = create_storage_accounts(config)
    outputs["common_storage_name"] = storage.get("common_name", "")
    outputs["common_storage_id"] = storage.get("common", {}).get("id", "")
    for partition in config.data_partitions:
        outputs[f"{partition}_storage_name"] = storage.get(f"{partition}_name", "")
        outputs[f"{partition}_storage_id"] = storage.get(partition, {}).get("id", "")

    # Phase 3: Identity and access
    oidc_issuer = get_aks_oidc_issuer(config)
    create_federated_credentials(config, config.identity_name, oidc_issuer)

    resource_ids = {
        "keyvault": outputs.get("keyvault_id", ""),
        "common_storage": outputs.get("common_storage_id", ""),
        "acr": outputs.get("acr_id", ""),
    }
    for partition in config.data_partitions:
        resource_ids[f"{partition}_storage"] = outputs.get(f"{partition}_storage_id", "")
        # Get service bus resource ID
        sb_show = run_command(
            ["az", "servicebus", "namespace", "show",
             "--name", _sb_name(partition, config.env),
             "--resource-group", config.resource_group,
             "--query", "id",
             "--output", "tsv"],
            display=False,
            description=f"Get Service Bus ID for {partition}",
        )
        resource_ids[f"{partition}_servicebus"] = sb_show.stdout.strip()

    assign_roles(config, outputs["identity_principal_id"], resource_ids)

    # Populate Key Vault with connection info
    populate_keyvault_secrets(config, outputs)

    return outputs
