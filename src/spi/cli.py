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

"""SPI CLI - Deploy OSDU SPI Stack on Azure AKS Automatic."""

import sys
from typing import Optional, List

import typer
from rich.panel import Panel
from rich.table import Table

from .config import Config, Profile
from .helpers import console, check_prerequisites, run_command, get_suspend_status, verify_spi_cluster
from .providers import PREREQ_TOOLS

app = typer.Typer(
    name="spi",
    help="SPI Stack - deploy, monitor, and manage OSDU on Azure AKS Automatic.",
    add_completion=False,
)


def _show_config(config: Config):
    table = Table(title="SPI Stack Deployment", border_style="cyan")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Profile", config.profile.value)
    if config.env:
        table.add_row("Environment", config.env)
    table.add_row("Cluster Name", config.cluster_name)
    table.add_row("Resource Group", config.resource_group)
    table.add_row("Location", config.location)
    table.add_row("Repository", config.repo_url)
    table.add_row("Branch", config.repo_branch)
    table.add_row("Data Partitions", ", ".join(config.data_partitions))
    table.add_row("Key Vault", config.keyvault_name)

    console.print(table)


def _show_next_steps(config: Config):
    console.print("\n[bold]Deployment initiated. Next steps:[/bold]")

    table = Table(border_style="dim")
    table.add_column("Action", style="cyan")
    table.add_column("Command", style="yellow")

    table.add_row("Watch progress", "kubectl get kustomizations -n flux-system --watch")
    table.add_row("Check operators", "kubectl get pods -n foundation")
    table.add_row("Check middleware", "kubectl get pods -n platform")
    table.add_row("Check services", "kubectl get pods -n osdu")
    table.add_row("View status", "uv run spi status")
    table.add_row("Cleanup", f"uv run spi down{config.env_flag}")

    console.print(table)


def _build_config(
    profile: Profile = Profile.CORE,
    env: str = "",
    repo_url: str = "https://github.com/danielscholl-osdu/osdu-spi-stack.git",
    branch: str = "main",
    location: str = "eastus2",
    data_partitions: Optional[List[str]] = None,
) -> Config:
    return Config.from_env(
        env=env,
        profile=profile,
        repo_url=repo_url,
        repo_branch=branch,
        location=location,
        data_partitions=data_partitions or ["opendes"],
    )


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

@app.command()
def check(
    output_json: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
):
    """Validate that required CLI tools are installed."""
    from .checks import run_checks, results_to_json

    results = run_checks()
    missing = sum(1 for r in results if not r["installed"])

    if output_json:
        print(results_to_json(results))
        raise typer.Exit(code=1 if missing else 0)

    table = Table(title="SPI Stack Prerequisites", border_style="cyan")
    table.add_column("Tool", style="cyan", min_width=10)
    table.add_column("Status", justify="center", min_width=8)
    table.add_column("Detail")

    for r in results:
        if r["installed"]:
            status = "[success]OK[/success]"
            detail = r["version"]
        else:
            status = "[error]MISSING[/error]"
            hint = r.get("install_cmd", "")
            detail = f"[info]{hint}[/info]" if hint else "[dim]no install hint[/dim]"
        table.add_row(r["name"], status, detail)

    console.print()
    console.print(table)

    installed = sum(1 for r in results if r["installed"])
    if missing == 0:
        console.print(f"\n[success]All {len(results)} tools available.[/success]")
    else:
        console.print(f"\n[warning]{installed}/{len(results)} installed, {missing} missing.[/warning]")
        raise typer.Exit(code=1)


@app.command()
def up(
    profile: Optional[Profile] = typer.Option(None, help="Deployment profile (default: core)"),
    env: str = typer.Option(..., "--env", help="Environment name (required, e.g. dev1, test)"),
    repo_url: str = typer.Option(
        "https://github.com/danielscholl-osdu/osdu-spi-stack.git",
        "--repo", help="Git repository URL"),
    branch: str = typer.Option("main", "--branch", help="Git branch"),
    location: str = typer.Option("eastus2", "--location", help="Azure region"),
    data_partitions: Optional[List[str]] = typer.Option(
        None, "--partition", help="Data partition names (can specify multiple)"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Show all sub-resource commands"),
):
    """Provision Azure infrastructure and deploy the OSDU SPI stack."""
    if profile is None:
        profile = Profile.CORE

    config = _build_config(
        profile=profile, env=env, repo_url=repo_url,
        branch=branch, location=location,
        data_partitions=data_partitions,
    )
    config.verbose = verbose

    console.print(Panel(
        "[bold]SPI Stack[/bold] - Azure-native OSDU Software Stack\n"
        "AKS Automatic + Azure PaaS + Flux CD GitOps",
        border_style="cyan",
    ))

    _show_config(config)
    check_prerequisites(PREREQ_TOOLS)

    try:
        from .providers.azure import deploy_azure
        deploy_azure(config)
        _show_next_steps(config)
        console.print("\n[success]SPI Stack deployment initiated. Flux is reconciling in the background.[/success]\n")
    except Exception as e:
        console.print(f"\n[error]Deployment failed: {e}[/error]")
        raise typer.Exit(code=1)


@app.command()
def down(
    env: str = typer.Option(..., "--env", help="Environment name"),
):
    """Tear down all Azure resources."""
    config = _build_config(env=env)

    console.print(Panel("[bold]SPI Stack Cleanup[/bold]", border_style="cyan"))
    _show_config(config)

    check_prerequisites(["az"])

    from .providers.azure import cleanup_azure
    cleanup_azure(config)


@app.command()
def info(
    show_secrets: bool = typer.Option(False, "--show-secrets", help="Display live Kubernetes credentials"),
    output_json: bool = typer.Option(False, "--json", help="Machine-readable JSON output"),
):
    """Show cluster access endpoints and optional credentials."""
    ctx = verify_spi_cluster()

    from .info import render_info
    if not output_json:
        console.print(f"  [dim]Cluster context: {ctx}[/dim]")
    render_info(show_secrets=show_secrets, output_json=output_json)


@app.command()
def status(
    watch: bool = typer.Option(False, "--watch", "-w", help="Continuous refresh"),
):
    """Show deployment health and reconciliation progress."""
    ctx = verify_spi_cluster()
    console.print(f"  [dim]Cluster context: {ctx}[/dim]")

    from .status import render_status, watch_status
    if watch:
        watch_status()
    else:
        render_status()


@app.command()
def reconcile(
    suspend: bool = typer.Option(False, "--suspend", help="Freeze: stop Flux auto-reconciliation"),
    resume: bool = typer.Option(False, "--resume", help="Unfreeze: resume Flux auto-reconciliation"),
):
    """Force Flux to reconcile the git source and stack."""
    import datetime

    if suspend and resume:
        console.print("[error]Cannot use --suspend and --resume together.[/error]")
        raise typer.Exit(code=1)

    ctx = verify_spi_cluster()
    console.print(f"  [dim]Cluster context: {ctx}[/dim]")

    if suspend:
        console.print("\n[bold]Suspending GitRepository...[/bold]")
        run_command(
            ["kubectl", "patch", "gitrepository", "osdu-spi-stack-system",
             "-n", "flux-system", "-p", '{"spec":{"suspend":true}}',
             "--type=merge"],
            description="Suspend GitRepository (freeze reconciliation)",
        )
        console.print("[warning]GitRepository suspended.[/warning]")
        console.print("[dim]Run 'uv run spi reconcile --resume' to unfreeze.[/dim]")
        return

    if resume:
        console.print("\n[bold]Resuming GitRepository...[/bold]")
        run_command(
            ["kubectl", "patch", "gitrepository", "osdu-spi-stack-system",
             "-n", "flux-system", "-p", '{"spec":{"suspend":false}}',
             "--type=merge"],
            description="Resume GitRepository (unfreeze reconciliation)",
        )
        console.print("[success]GitRepository resumed.[/success]")
        return

    # Default: force reconcile
    if get_suspend_status():
        console.print(Panel(
            "[bold yellow]GitRepository is currently SUSPENDED.[/bold yellow]\n"
            "This reconcile is a one-shot trigger; Flux will not auto-reconcile future commits.\n"
            "[dim]Use --resume to unfreeze, or --suspend to re-freeze after.[/dim]",
            border_style="yellow",
        ))

    ts = datetime.datetime.now().isoformat()
    console.print("\n[bold]Reconciling...[/bold]")

    run_command(
        ["kubectl", "annotate", "--overwrite", "gitrepository/osdu-spi-stack-system",
         "-n", "flux-system", f"reconcile.fluxcd.io/requestedAt={ts}"],
        description="Trigger GitRepository reconciliation",
    )

    for name in ["osdu-spi-stack", "osdu-spi-stack-system-stack", "stack"]:
        run_command(
            ["kubectl", "annotate", "--overwrite", f"kustomization/{name}",
             "-n", "flux-system", f"reconcile.fluxcd.io/requestedAt={ts}"],
            description=f"Trigger Kustomization reconciliation ({name})",
            check=False,
        )

    console.print("[success]Reconciliation triggered.[/success]")
