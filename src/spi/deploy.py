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

"""Deployment orchestrator.

Provisions Azure PaaS (via ``azure_infra.provision_azure_infra``), bootstraps
the cluster (namespaces, StorageClasses, Gateway API CRDs, ingress ConfigMap,
Workload Identity SAs, in-cluster seed secrets), activates GitOps via Flux,
and writes the KV runtime secrets that OSDU services read at startup.
"""

import subprocess
import time

import typer

from .azure_infra import provision_azure_infra
from .bicep import run_bicep_deployment
from .bootstrap import (
    create_storage_classes,
    ensure_namespaces,
    install_gateway_api_crds,
)
from .config import Config, IngressMode
from .console import console, display_result, display_yaml
from .ingress import (
    create_ingress_config,
    discover_dns_zone,
    get_ingress_ip,
    resolve_post_deploy_inputs,
)
from .paths import REPO_ROOT
from .secrets import ensure_secrets, get_or_create_seed
from .shell import kubectl_apply_yaml, run_command
from .templates import (
    osdu_config_configmap,
    spi_init_values_configmap,
    workload_identity_sa,
)

GITREPO_NAME = "osdu-spi-stack-system"

INFRA_FLUX_BICEP = REPO_ROOT / "infra" / "flux.bicep"


def _create_osdu_config(config: Config, infra_outputs: dict) -> None:
    """Create the osdu-config ConfigMap and workload identity SAs."""
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

    for ns in ["platform", "osdu"]:
        sa_yaml = workload_identity_sa(
            namespace=ns,
            client_id=infra_outputs.get("identity_client_id", ""),
            tenant_id=infra_outputs.get("tenant_id", ""),
        )
        kubectl_apply_yaml(sa_yaml, f"apply workload-identity-sa in {ns}")
    display_result("Workload Identity ServiceAccounts created")


def _create_spi_init_values(config: Config) -> None:
    """Apply the spi-init-values ConfigMap that the osdu-spi-init HelmRelease
    consumes via valuesFrom. Must run before Flux reconciles the HelmRelease.
    """
    console.print("\n[bold]Creating SPI init values ConfigMap...[/bold]")
    yaml_content = spi_init_values_configmap(config.data_partitions)
    display_yaml(yaml_content, "ConfigMap: spi-init-values")
    kubectl_apply_yaml(yaml_content, "apply spi-init-values ConfigMap")
    display_result(
        f"spi-init-values ConfigMap created for partitions: "
        f"{', '.join(config.data_partitions)}"
    )


def _write_keyvault_bootstrap_secrets(
    config: Config,
    keyvault_name: str,
    storage_account_name: str,
    elastic_password: str,
    redis_password: str,
) -> None:
    """Write the small set of secrets OSDU services read at startup.

    Partition reads tbl-storage-endpoint to locate its metadata table.
    Indexer and workflow read redis-hostname/redis-password via KeyVaultFacade.
    Search and indexer read {partition}-elastic-* via partition service API.

    Elastic credentials are written per-partition because the partition record
    resolves them by partition-prefixed secret name. All partitions share the
    single in-cluster ES cluster and therefore the same elastic user/password.
    """
    console.print("\n[bold]Writing OSDU bootstrap secrets to Key Vault...[/bold]")
    tbl_endpoint = f"https://{storage_account_name}.table.core.windows.net/"
    elastic_endpoint = "https://elasticsearch-es-http.platform.svc.cluster.local:9200"
    redis_hostname = "platform-redis-master.platform.svc.cluster.local"

    secrets_to_write: list[tuple[str, str]] = [
        ("tbl-storage-endpoint", tbl_endpoint),
        ("redis-hostname", redis_hostname),
        ("redis-password", redis_password),
    ]
    for p in config.data_partitions:
        secrets_to_write.extend([
            (f"{p}-elastic-endpoint", elastic_endpoint),
            (f"{p}-elastic-username", "elastic"),
            (f"{p}-elastic-password", elastic_password),
        ])

    for name, value in secrets_to_write:
        run_command(
            [
                "az", "keyvault", "secret", "set",
                "--vault-name", keyvault_name,
                "--name", name,
                "--value", value,
                "--output", "none",
            ],
            description=f"Set KV secret: {name}",
            display=False,
        )
        console.print(f"  [success]{name}[/success]")

    display_result(f"{len(secrets_to_write)} Key Vault secrets written")


def _pin_gitops_source() -> None:
    """Suspend the GitRepository so future commits don't auto-roll (ADR-014).

    Waits up to 120s for the source-controller to publish its first artifact,
    then patches ``spec.suspend: true``. The wait is non-fatal: on timeout we
    warn and suspend anyway. Downstream Kustomizations/HelmReleases keep
    reconciling from the cached artifact.
    """
    console.print("\n[bold]Pinning environment to deploy commit...[/bold]")

    wait_result = subprocess.run(
        [
            "kubectl", "wait",
            "--for=condition=Ready",
            f"gitrepository/{GITREPO_NAME}",
            "-n", "flux-system",
            "--timeout=120s",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.DEVNULL,
    )
    if wait_result.returncode != 0:
        console.print(
            "  [warning]GitRepository did not become Ready within 120s; "
            "suspending anyway. Run 'spi reconcile' if reconciliation stalls.[/warning]"
        )

    run_command(
        [
            "kubectl", "patch", "gitrepository", GITREPO_NAME,
            "-n", "flux-system",
            "--type=merge",
            "-p", '{"spec":{"suspend":true}}',
        ],
        description="Suspend GitRepository (pin to deploy commit)",
        check=False,
    )
    display_result(
        "GitRepository pinned. Run 'spi reconcile' to pull updates, "
        "or 'spi reconcile --resume' to enable auto-reconciliation."
    )


def deploy_azure(config: Config, dry_run: bool = False) -> None:
    """Provision Azure infra, bootstrap Kubernetes, deploy via GitOps.

    In ``dry_run`` mode, only the Azure PaaS Bicep preview runs; AKS, the
    Kubernetes bootstrap phase, and GitOps activation are skipped so the
    caller can inspect what would change without actually provisioning.
    """
    # For dns mode we need to resolve the DNS zone BEFORE running main.bicep
    # so the conditional external-dns-identity + DNS Zone Contributor role
    # modules get the right scope + name.
    if not dry_run and config.ingress_mode == IngressMode.DNS and not config.dns_zone:
        zone, rg = discover_dns_zone()
        config.dns_zone = zone
        config.dns_zone_rg = rg

    # Phase 1-3: Azure infrastructure
    infra_outputs = provision_azure_infra(config, dry_run=dry_run)

    if dry_run:
        return

    # Phase 4: Kubernetes bootstrap
    ensure_namespaces()
    ensure_secrets()
    create_storage_classes()
    install_gateway_api_crds()
    _create_osdu_config(config, infra_outputs)
    _create_spi_init_values(config)

    # Phase 4b: Ingress mode resolution (requires live cluster + Istio LB)
    resolve_post_deploy_inputs(config)
    create_ingress_config(
        config=config,
        external_dns_client_id=infra_outputs.get("external_dns_client_id", ""),
        tenant_id=infra_outputs.get("tenant_id", ""),
        gateway_ip=get_ingress_ip(),
    )

    # Phase 5: GitOps activation (Flux extension + Kustomization via Bicep)
    console.print("\n[bold]Deploying Flux extension and GitOps config via Bicep...[/bold]")
    run_bicep_deployment(
        template_path=str(INFRA_FLUX_BICEP),
        parameters={
            "clusterName": config.cluster_name,
            "repoUrl": config.repo_url,
            "repoBranch": config.repo_branch,
            "profile": config.profile.value,
            "ingressMode": config.ingress_mode.value,
        },
        resource_group=config.resource_group,
        deployment_name=f"spi-flux-{config.env or 'base'}",
    )
    display_result(
        f"GitOps activated for profile: {config.profile.value}, "
        f"ingress: {config.ingress_mode.value}"
    )

    # Phase 6: Non-blocking runtime writes.
    # Cross-namespace CA copies and the Redis Istio DestinationRule moved
    # into Flux (software/stacks/osdu/bootstrap/) as Pass 1 of ADR-011.
    # Only the KV seed writes remain here; they run in seconds since all
    # values are known as soon as infra is up and the seed is generated.
    seed = get_or_create_seed()
    _write_keyvault_bootstrap_secrets(
        config=config,
        keyvault_name=config.keyvault_name,
        storage_account_name=infra_outputs.get("common_storage_name", ""),
        elastic_password=seed["elastic_password"],
        redis_password=seed["redis_password"],
    )

    # Phase 7: Pin the environment to the deploy commit (ADR-014).
    # Future commits to the tracked branch won't auto-reconcile until the
    # user runs 'spi reconcile' or 'spi reconcile --resume'.
    _pin_gitops_source()


def cleanup_azure(config: Config) -> None:
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
