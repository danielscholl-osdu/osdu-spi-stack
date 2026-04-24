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
from pathlib import Path

import typer

from ..config import Config, IngressMode
from ..helpers import (
    console, run_command, display_result, run_bicep_deployment,
    create_storage_classes, ensure_namespaces,
    install_gateway_api_crds, kubectl_apply_yaml, display_yaml,
    discover_dns_zone, set_ingress_dns_label,
    get_ingress_ip, create_ingress_config,
)
from ..secrets import ensure_secrets, get_or_create_seed
from ..azure_infra import provision_azure_infra
from ..runtime_bootstrap import write_keyvault_bootstrap_secrets
from ..templates import osdu_config_configmap, workload_identity_sa


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
INFRA_FLUX_BICEP = _REPO_ROOT / "infra" / "flux.bicep"


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


def _resolve_ingress_inputs(config: Config) -> None:
    """Resolve ingress-mode-specific inputs that require a live AKS cluster.

    Mutates ``config`` in place:
      - azure mode: patches the Istio ingress LB with azure-dns-label-name
        and waits for Azure to publish the FQDN (status.loadBalancer.
        ingress[0].hostname). Stores on ``config.ingress_fqdn``.
      - dns mode:   if ``config.dns_zone`` is empty, auto-discovers a single
        DNS zone in the current subscription and populates
        ``config.dns_zone`` + ``config.dns_zone_rg``.
      - ip mode:    no-op.
    """
    if config.ingress_mode == IngressMode.AZURE:
        config.ingress_fqdn = set_ingress_dns_label(
            dns_label=config.dns_label,
            location=config.location,
        )
    elif config.ingress_mode == IngressMode.DNS:
        if not config.dns_zone:
            zone, rg = discover_dns_zone()
            config.dns_zone = zone
            config.dns_zone_rg = rg
            display_result(f"Using DNS zone: {zone} (rg: {rg})")


def deploy_azure(config: Config, dry_run: bool = False):
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

    # Phase 4b: Ingress mode resolution (requires live cluster + Istio LB)
    _resolve_ingress_inputs(config)
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
    write_keyvault_bootstrap_secrets(
        config=config,
        keyvault_name=config.keyvault_name,
        storage_account_name=infra_outputs.get("common_storage_name", ""),
        elastic_password=seed["elastic_password"],
        redis_password=seed["redis_password"],
    )


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
