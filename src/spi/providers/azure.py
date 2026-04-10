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

"""Azure provider - AKS Automatic with SPI services via GitOps."""

import time

import typer

from ..config import Config
from ..helpers import (
    console, run_command, display_result,
    create_storage_classes, ensure_namespaces,
    install_gateway_api_crds, kubectl_apply_yaml, display_yaml,
)
from ..secrets import ensure_secrets, get_or_create_seed
from ..azure_infra import provision_azure_infra
from ..runtime_bootstrap import (
    apply_redis_destination_rule,
    copy_elastic_ca_to_osdu,
    copy_redis_ca_to_osdu,
    write_keyvault_bootstrap_secrets,
)
from ..templates import osdu_config_configmap, workload_identity_sa


def _flux_config_exists(config: Config) -> bool:
    result = run_command(
        ["az", "k8s-configuration", "flux", "show",
         "--resource-group", config.resource_group,
         "--cluster-name", config.cluster_name,
         "--cluster-type", "managedClusters",
         "--name", "osdu-spi-stack-system"],
        display=False,
        check=False,
    )
    return result.returncode == 0


def _create_osdu_config(config: Config, infra_outputs: dict):
    """Create the osdu-config ConfigMap and workload identity SA in the osdu namespace."""
    console.print("\n[bold]Creating OSDU configuration...[/bold]")

    partition = config.primary_partition
    yaml_content = osdu_config_configmap(
        domain="",  # Updated later by `spi info` once external IP is known
        data_partition=partition,
        tenant_id=infra_outputs.get("tenant_id", ""),
        identity_client_id=infra_outputs.get("identity_client_id", ""),
        keyvault_uri=infra_outputs.get("keyvault_uri", ""),
        keyvault_name=config.keyvault_name,
        cosmosdb_endpoint=infra_outputs.get(f"{partition}_cosmos_endpoint", ""),
        storage_account_name=infra_outputs.get("common_storage_name", ""),
        servicebus_namespace=infra_outputs.get(f"{partition}_sb_namespace", ""),
    )
    display_yaml(yaml_content, "ConfigMap: osdu-config")
    kubectl_apply_yaml(yaml_content, "apply osdu-config ConfigMap")
    display_result("osdu-config ConfigMap created")

    # Create workload identity SA in both platform and osdu namespaces
    for ns in ["platform", "osdu"]:
        sa_yaml = workload_identity_sa(
            namespace=ns,
            client_id=infra_outputs.get("identity_client_id", ""),
            tenant_id=infra_outputs.get("tenant_id", ""),
        )
        kubectl_apply_yaml(sa_yaml, f"apply workload-identity-sa in {ns}")
    display_result("Workload Identity ServiceAccounts created")


def deploy_azure(config: Config):
    """Provision Azure infra, bootstrap Kubernetes, deploy via GitOps."""
    # Phase 1-3: Azure infrastructure
    infra_outputs = provision_azure_infra(config)

    # Phase 4: Kubernetes bootstrap
    ensure_namespaces()
    ensure_secrets()
    create_storage_classes()
    install_gateway_api_crds()
    _create_osdu_config(config, infra_outputs)

    # Phase 5: GitOps activation via AKS native extension
    flux_verb = "update" if _flux_config_exists(config) else "create"
    console.print(f"\n[bold]Deploying via AKS GitOps extension ({flux_verb})...[/bold]")
    cmd = [
        "az", "k8s-configuration", "flux", flux_verb,
        "--resource-group", config.resource_group,
        "--cluster-name", config.cluster_name,
        "--cluster-type", "managedClusters",
        "--name", "osdu-spi-stack-system",
    ]
    if flux_verb == "create":
        cmd += ["--namespace", "flux-system", "--scope", "cluster"]
    cmd += [
        "--url", config.repo_url,
        "--branch", config.repo_branch,
        "--no-wait",
        "--kustomization",
        "name=stack",
        f"path=./software/stacks/osdu/profiles/{config.profile.value}",
        "prune=true",
        "sync-interval=10m",
        "timeout=30m",
    ]
    run_command(cmd, description=f"Configure GitOps: profile {config.profile.value}")

    # Phase 6: Runtime bootstrap -- bridge middleware to OSDU services.
    # These steps can only run after Flux has reconciled Redis and ES,
    # so they poll for the resulting secrets with a timeout. The Istio
    # DestinationRule and Key Vault secrets can be applied immediately
    # without waiting.
    _runtime_bootstrap(config, infra_outputs)


def _runtime_bootstrap(config: Config, infra_outputs: dict):
    """Post-handoff bootstrap: Istio DR, KV secrets, cert copies."""
    console.print("\n[bold]Running post-handoff bootstrap...[/bold]")

    # Non-blocking: apply Istio DestinationRule for Redis
    apply_redis_destination_rule()

    # Non-blocking: write the small set of KV secrets OSDU services read at startup
    seed = get_or_create_seed()
    write_keyvault_bootstrap_secrets(
        config=config,
        keyvault_name=config.keyvault_name,
        storage_account_name=infra_outputs.get("common_storage_name", ""),
        elastic_password=seed["elastic_password"],
        redis_password=seed["redis_password"],
    )

    # Blocking with timeout: wait for Flux-managed middleware secrets
    copy_redis_ca_to_osdu()
    copy_elastic_ca_to_osdu()


def cleanup_azure(config: Config):
    """Delete Azure resource group and all resources."""
    console.print("\n[bold]Cleaning up Azure resources...[/bold]")
    result = run_command(
        ["az", "group", "delete",
         "--name", config.resource_group,
         "--yes", "--no-wait"],
        description=f"Delete resource group: {config.resource_group}",
        check=False,
    )
    if result.returncode != 0:
        console.print(f"[error]Azure cleanup request failed for {config.resource_group}.[/error]")
        raise typer.Exit(code=1)

    console.print("  [info]Waiting briefly for Azure to acknowledge the deletion...[/info]")
    deadline = time.time() + 60
    while time.time() < deadline:
        exists = run_command(
            ["az", "group", "exists", "--name", config.resource_group],
            description=f"Check resource group status: {config.resource_group}",
            display=False,
            check=False,
        )
        if exists.returncode == 0 and exists.stdout.strip().lower() == "false":
            display_result(f"Resource group {config.resource_group} deleted")
            return
        time.sleep(10)

    display_result("Cleanup accepted by Azure; deletion is continuing in the background")
    console.print(
        f"  [warning]Verify later with: az group exists --name {config.resource_group}[/warning]"
    )
