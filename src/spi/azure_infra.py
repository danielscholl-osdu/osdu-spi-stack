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

"""Azure PaaS infrastructure provisioning.

Hybrid model:
  - Resource Group + AKS Automatic + managed Istio are imperative (az CLI).
    AKS is kept imperative because AKS Automatic + managed-Istio has
    operational sequencing (mesh enable, CNI chaining, ingress gateway,
    safeguards relaxation) that Bicep does not cleanly model.
  - Key Vault soft-delete recovery is imperative pre-check (ARM cannot
    branch on a list-deleted query).
  - Everything else (Managed Identity, federated credentials, Key Vault
    creation, ACR, CosmosDB Gremlin + SQL, Service Bus + topics/subs,
    Storage + containers/tables, RBAC role assignments) is declared in
    Bicep at ``infra/main.bicep`` and deployed with
    ``az deployment group create``.
  - Cosmos DB primary keys are fetched after the deploy via
    ``az cosmosdb keys list`` (they are secure; not exposed as Bicep
    outputs).
  - Key Vault secret VALUES are written by the CLI post-deploy, since
    they derive from Bicep output values plus the Python-managed
    in-cluster seed passwords.

The function ``provision_azure_infra(config)`` returns the same shape of
infra_outputs dict as before so downstream callers
(_create_osdu_config, populate_keyvault_secrets,
write_keyvault_bootstrap_secrets) are unchanged.
"""

import json
from pathlib import Path
from typing import Any, Dict

from .config import Config
from .helpers import (
    console,
    display_result,
    run_bicep_deployment,
    run_command,
)

# ─────────────────────────────────────────────────────────────
# Path to the Bicep template. Relative to the repo root.
# src/spi/azure_infra.py  ->  three parents up is the repo root.
# ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
INFRA_MAIN_BICEP = _REPO_ROOT / "infra" / "main.bicep"


# ─────────────────────────────────────────────────────────────
# Resource-name helpers (preserve the existing naming contract).
# Bicep consumes these via parameters; the template does not
# re-derive names.
# ─────────────────────────────────────────────────────────────

def _storage_name(prefix: str, env: str) -> str:
    """Generate a storage account name (lowercase alphanumeric, 3-24 chars)."""
    safe = (prefix + env).replace("-", "").replace("_", "").lower()
    return safe[:24]


def _sb_name(partition: str, env: str) -> str:
    """Service Bus namespace name."""
    return f"osdu-{env}-{partition}-bus"[:50]


def _cosmos_sql_name(partition: str, env: str) -> str:
    """CosmosDB SQL account name for a partition."""
    return f"osdu-{env}-{partition}-cosmos"[:44]


def _cosmos_gremlin_name(env: str) -> str:
    """CosmosDB Gremlin account name."""
    return f"osdu-{env}-graph"[:44]


# ─────────────────────────────────────────────────────────────
# Phase 1: Core infrastructure (imperative; Bicep-incompatible)
# ─────────────────────────────────────────────────────────────

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
    """Create an AKS Automatic cluster with managed Istio.

    Kept imperative because the mesh bootstrap (enable, CNI chaining,
    ingress gateway, safeguards relaxation) is operational sequencing
    that ARM does not express cleanly.
    """
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
             "--enable-azure-service-mesh",
             # AKS Automatic requires the DisableSSH feature on the initial
             # system nodepool. Without --ssh-access disabled, az aks create
             # returns BadRequest on the "Automatic" SKU.
             "--ssh-access", "disabled",
             "--output", "json"],
            description=f"Create AKS Automatic: {config.cluster_name}",
        )
    display_result(f"AKS Automatic cluster {config.cluster_name} ready")

    # --enable-azure-service-mesh on create leaves a background update
    # in flight after az aks create returns. Wait for it to settle before
    # the next cluster update, otherwise we hit OperationNotAllowed.
    run_command(
        ["az", "aks", "wait",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--updated", "--interval", "30"],
        description="Wait for cluster to be ready",
        display=False,
    )

    # Relax Deployment Safeguards for the three namespaces we manage.
    # The uniqueServiceSelectors constraint blocks ECK from creating its
    # http + transport services (both select the same pods), and container
    # probe/resource constraints collide with a few upstream charts. We
    # drop enforcement to Warning and exclude platform/osdu/foundation so
    # workloads can start while other namespaces keep full enforcement.
    _configure_safeguards(config)

    # Enable Istio mesh and external ingress gateway (idempotent)
    _ensure_istio_mesh(config)

    console.print("\n[bold]Fetching cluster credentials...[/bold]")
    run_command(
        ["az", "aks", "get-credentials",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--overwrite-existing"],
        description="Merge kubeconfig",
    )


def _configure_safeguards(config: Config):
    """Set AKS Deployment Safeguards to Warning and exclude managed namespaces."""
    console.print("\n[bold]Configuring Deployment Safeguards...[/bold]")
    run_command(
        [
            "az", "aks", "update",
            "--resource-group", config.resource_group,
            "--name", config.cluster_name,
            "--safeguards-level", "Warning",
            "--safeguards-excluded-ns", "platform,osdu,foundation",
            "--output", "none",
        ],
        description="Safeguards: Warning + exclude platform,osdu,foundation",
    )
    display_result("Deployment Safeguards relaxed for managed namespaces")


def _ensure_istio_mesh(config: Config):
    """Ensure Istio service mesh and external ingress gateway are enabled."""
    result = run_command(
        ["az", "aks", "show",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--query", "serviceMeshProfile",
         "--output", "json"],
        description="Check Istio mesh status",
        display=False,
    )
    mesh = json.loads(result.stdout or "{}")

    if mesh.get("mode") != "Istio":
        console.print("\n[bold]Enabling Istio service mesh...[/bold]")
        run_command(
            ["az", "aks", "mesh", "enable",
             "--resource-group", config.resource_group,
             "--name", config.cluster_name],
            description="Enable Azure Service Mesh",
        )
        display_result("Istio service mesh enabled")
    else:
        display_result("Istio service mesh already enabled")

    run_command(
        ["az", "aks", "wait",
         "--resource-group", config.resource_group,
         "--name", config.cluster_name,
         "--updated", "--interval", "30"],
        description="Wait for cluster to be ready",
        display=False,
    )

    # Enable CNI chaining to avoid NET_ADMIN capability requirement
    # (AKS Deployment Safeguards block istio-init with NET_ADMIN)
    cni_mode = (
        (mesh.get("istio") or {})
        .get("components", {})
        .get("proxyRedirectionMechanism", "")
    )
    if cni_mode != "CNIChaining":
        console.print("\n[bold]Enabling Istio CNI chaining...[/bold]")
        run_command(
            ["az", "aks", "mesh", "enable-istio-cni",
             "--resource-group", config.resource_group,
             "--name", config.cluster_name],
            description="Enable Istio CNI chaining",
        )
        run_command(
            ["az", "aks", "wait",
             "--resource-group", config.resource_group,
             "--name", config.cluster_name,
             "--updated", "--interval", "30"],
            description="Wait for cluster to be ready",
            display=False,
        )
        display_result("Istio CNI chaining enabled")
    else:
        display_result("Istio CNI chaining already enabled")

    gateways = (mesh.get("istio") or {}).get("components", {}).get("ingressGateways") or []
    has_external = any(g.get("enabled") and g.get("mode") == "External" for g in gateways)
    if not has_external:
        console.print("\n[bold]Enabling Istio external ingress gateway...[/bold]")
        run_command(
            ["az", "aks", "mesh", "enable-ingress-gateway",
             "--resource-group", config.resource_group,
             "--name", config.cluster_name,
             "--ingress-gateway-type", "External"],
            description="Enable external ingress gateway",
        )
        display_result("Istio external ingress gateway enabled")
    else:
        display_result("Istio external ingress gateway already enabled")


def get_aks_oidc_issuer(config: Config) -> str:
    """Get the OIDC issuer URL for the AKS cluster. Needed for federated credentials."""
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


# ─────────────────────────────────────────────────────────────
# Key Vault soft-delete pre-check (imperative; ARM cannot branch on
# list-deleted queries)
# ─────────────────────────────────────────────────────────────

def _recover_soft_deleted_keyvault(config: Config):
    """If the target Key Vault was previously soft-deleted, recover it.

    Bicep would otherwise fail with "vault name already exists in this
    region" when attempting to create a vault whose soft-deleted twin
    still occupies the namespace.
    """
    deleted_check = run_command(
        ["az", "keyvault", "list-deleted",
         "--query", f"[?name=='{config.keyvault_name}']",
         "--output", "json"],
        description=f"Check for soft-deleted Key Vault: {config.keyvault_name}",
        check=False,
        display=False,
    )
    deleted_vaults = json.loads(deleted_check.stdout or "[]")
    if deleted_vaults:
        console.print(f"\n[warning]Recovering soft-deleted Key Vault '{config.keyvault_name}'...[/warning]")
        run_command(
            ["az", "keyvault", "recover",
             "--name", config.keyvault_name,
             "--resource-group", config.resource_group,
             "--output", "json"],
            description=f"Recover Key Vault: {config.keyvault_name}",
        )
        display_result(f"Key Vault {config.keyvault_name} recovered")


# ─────────────────────────────────────────────────────────────
# Bicep parameter assembly and output reshaping
# ─────────────────────────────────────────────────────────────

def _build_bicep_params(config: Config, oidc_issuer: str) -> Dict[str, Any]:
    """Translate Config into the parameter dict consumed by infra/main.bicep."""
    return {
        "envName": config.env,
        "location": config.location,
        "clusterName": config.cluster_name,
        "identityName": config.identity_name,
        "keyVaultName": config.keyvault_name,
        "acrName": config.acr_name,
        "dataPartitions": config.data_partitions,
        "primaryPartition": config.primary_partition,
        "gremlinAccountName": _cosmos_gremlin_name(config.env),
        "commonStorageName": _storage_name("osdu" + config.env + "common", ""),
        "cosmosSqlNames": [
            _cosmos_sql_name(p, config.env) for p in config.data_partitions
        ],
        "serviceBusNames": [
            _sb_name(p, config.env) for p in config.data_partitions
        ],
        "partitionStorageNames": [
            _storage_name("osdu" + config.env + p, "") for p in config.data_partitions
        ],
        "oidcIssuerUrl": oidc_issuer,
    }


def _reshape_bicep_outputs(bicep_outputs: Dict[str, Any]) -> Dict[str, Any]:
    """Convert Bicep camelCase outputs into the legacy infra_outputs dict.

    Bicep emits per-partition data as parallel arrays (indexed by the
    dataPartitions order). This function zips those arrays back into the
    per-partition keys that the downstream code reads
    (e.g., ``opendes_cosmos_endpoint``).
    """
    out: Dict[str, Any] = {
        "identity_client_id": bicep_outputs.get("identityClientId", ""),
        "identity_principal_id": bicep_outputs.get("identityPrincipalId", ""),
        "identity_id": bicep_outputs.get("identityResourceId", ""),
        "keyvault_uri": bicep_outputs.get("keyvaultUri", ""),
        "keyvault_id": bicep_outputs.get("keyvaultId", ""),
        "acr_id": bicep_outputs.get("acrId", ""),
        "acr_login_server": bicep_outputs.get("acrLoginServer", ""),
        "graph_endpoint": bicep_outputs.get("graphEndpoint", ""),
        "graph_account_id": bicep_outputs.get("graphAccountId", ""),
        "common_storage_name": bicep_outputs.get("commonStorageName", ""),
        "common_storage_id": bicep_outputs.get("commonStorageId", ""),
    }

    partition_names = bicep_outputs.get("partitionNames", []) or []
    cosmos_endpoints = bicep_outputs.get("partitionCosmosEndpoints", []) or []
    cosmos_account_ids = bicep_outputs.get("partitionCosmosAccountIds", []) or []
    sb_ids = bicep_outputs.get("partitionServiceBusIds", []) or []
    sb_names = bicep_outputs.get("partitionServiceBusNames", []) or []
    storage_ids = bicep_outputs.get("partitionStorageIds", []) or []
    storage_names = bicep_outputs.get("partitionStorageNamesOut", []) or []

    for i, partition in enumerate(partition_names):
        if i < len(cosmos_endpoints):
            out[f"{partition}_cosmos_endpoint"] = cosmos_endpoints[i]
        if i < len(cosmos_account_ids):
            out[f"{partition}_cosmos_account_id"] = cosmos_account_ids[i]
        if i < len(sb_ids):
            out[f"{partition}_servicebus_id"] = sb_ids[i]
        if i < len(sb_names):
            out[f"{partition}_sb_namespace"] = sb_names[i]
        if i < len(storage_ids):
            out[f"{partition}_storage_id"] = storage_ids[i]
        if i < len(storage_names):
            out[f"{partition}_storage_name"] = storage_names[i]

    return out


def _fetch_cosmos_keys(config: Config, outputs: Dict[str, Any]):
    """Fetch CosmosDB primary keys after the Bicep deploy.

    The keys are secure and not exposed as Bicep outputs. They are read
    here and merged into ``outputs`` so ``populate_keyvault_secrets`` can
    store them in Key Vault.
    """
    console.print("\n[bold]Fetching CosmosDB keys...[/bold]")

    gremlin_result = run_command(
        ["az", "cosmosdb", "keys", "list",
         "--name", _cosmos_gremlin_name(config.env),
         "--resource-group", config.resource_group,
         "--output", "json"],
        description=f"Get Gremlin keys: {_cosmos_gremlin_name(config.env)}",
        display=False,
    )
    gk = json.loads(gremlin_result.stdout)
    outputs["graph_primary_key"] = gk.get("primaryMasterKey", "")

    for partition in config.data_partitions:
        sql_result = run_command(
            ["az", "cosmosdb", "keys", "list",
             "--name", _cosmos_sql_name(partition, config.env),
             "--resource-group", config.resource_group,
             "--output", "json"],
            description=f"Get CosmosDB keys: {_cosmos_sql_name(partition, config.env)}",
            display=False,
        )
        sk = json.loads(sql_result.stdout)
        outputs[f"{partition}_cosmos_primary_key"] = sk.get("primaryMasterKey", "")

    display_result(f"CosmosDB keys fetched for {len(config.data_partitions) + 1} accounts")


# ─────────────────────────────────────────────────────────────
# Key Vault secret values (data-plane; post-Bicep)
# ─────────────────────────────────────────────────────────────

def populate_keyvault_secrets(config: Config, infra_outputs: Dict[str, Any]):
    """Store Azure PaaS connection info in Key Vault.

    Writes secret VALUES (data-plane operation). The Key Vault itself
    and the identity's Secrets User role assignment come from Bicep.
    """
    console.print("\n[bold]Populating Key Vault secrets...[/bold]")

    secrets: Dict[str, str] = {
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

    if "graph_endpoint" in infra_outputs:
        secrets["graph-db-endpoint"] = infra_outputs["graph_endpoint"]
    if "graph_primary_key" in infra_outputs:
        secrets["graph-db-primary-key"] = infra_outputs["graph_primary_key"]

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

    active_secrets = {k: v for k, v in secrets.items() if v}
    for name, value in active_secrets.items():
        run_command(
            ["az", "keyvault", "secret", "set",
             "--vault-name", config.keyvault_name,
             "--name", name,
             "--value", value,
             "--output", "none"],
            description=f"Set secret: {name}",
            display=False,
            check=False,
        )

    display_result(f"Key Vault secrets populated ({len(active_secrets)} secrets)")


# ─────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────

def provision_azure_infra(config: Config) -> Dict[str, Any]:
    """Provision all Azure PaaS resources. Returns infra_outputs for K8s bootstrap.

    Order:
      1. Verify Azure login; capture tenant/subscription IDs.
      2. Create resource group (imperative).
      3. Create AKS Automatic + mesh (imperative, Phase 5 deferred).
      4. Recover soft-deleted Key Vault if present (imperative pre-check).
      5. Fetch AKS OIDC issuer URL (required for federated credentials).
      6. Deploy Bicep template (identity + FCs, KV, ACR, Gremlin, common
         storage, per-partition Cosmos/ServiceBus/Storage, RBAC).
      7. Fetch Cosmos primary keys (secure; not in Bicep outputs).
      8. Populate Key Vault secret values.
    """
    outputs: Dict[str, Any] = {}

    console.print("\n[bold]Verifying Azure login...[/bold]")
    result = run_command(
        ["az", "account", "show", "--output", "json"],
        description="Check Azure subscription",
    )
    account = json.loads(result.stdout)
    outputs["tenant_id"] = account.get("tenantId", "")
    outputs["subscription_id"] = account.get("id", "")
    console.print(
        f"  [info]Subscription: {account.get('name', 'unknown')} "
        f"({account.get('id', '')})[/info]"
    )

    create_resource_group(config)
    create_aks_automatic(config)
    _recover_soft_deleted_keyvault(config)
    oidc_issuer = get_aks_oidc_issuer(config)

    console.print("\n[bold]Deploying Azure PaaS resources via Bicep...[/bold]")
    console.print(
        "  [info]Identity, KeyVault, ACR, CosmosDB, Service Bus, Storage, "
        "and RBAC role assignments are declared in infra/main.bicep.[/info]"
    )
    bicep_params = _build_bicep_params(config, oidc_issuer)
    bicep_outputs = run_bicep_deployment(
        template_path=str(INFRA_MAIN_BICEP),
        parameters=bicep_params,
        resource_group=config.resource_group,
        deployment_name=f"spi-{config.env or 'base'}",
    )
    outputs.update(_reshape_bicep_outputs(bicep_outputs))
    display_result("Bicep deployment complete")

    _fetch_cosmos_keys(config, outputs)
    populate_keyvault_secrets(config, outputs)

    return outputs
