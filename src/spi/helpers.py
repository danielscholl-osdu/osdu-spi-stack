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

"""Shared command helpers and display utilities."""

import os
import shlex
import subprocess
import sys
import time
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.theme import Theme

# ---------------------------------------------------------------------------
# Rich console (shared across all modules)
# ---------------------------------------------------------------------------
custom_theme = Theme(
    {
        "azure": "bold cyan",
        "kubectl": "bold green",
        "flux": "bold magenta",
        "helm": "bold yellow",
        "info": "dim white",
        "success": "bold green",
        "error": "bold red",
        "warning": "bold yellow",
    }
)

console = Console(theme=custom_theme)

TRANSIENT_KUBECTL_ERRORS = (
    "connection refused",
    "connection reset by peer",
    "context deadline exceeded",
    "eof",
    "i/o timeout",
    "no route to host",
    "service unavailable",
    "temporarily unavailable",
    "the server is currently unable to handle the request",
    "tls handshake timeout",
)


# ---------------------------------------------------------------------------
# Command execution with transparency
# ---------------------------------------------------------------------------

def run_command(
    cmd_list: List[str],
    capture_output: bool = True,
    text: bool = True,
    display: bool = True,
    description: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command and display it in a formatted panel."""
    formatted_parts = []
    if cmd_list:
        formatted_parts.append(cmd_list[0])

    i = 1
    while i < len(cmd_list):
        if cmd_list[i].startswith("-"):
            formatted_parts.append("\\\n  " + shlex.quote(cmd_list[i]))
        else:
            formatted_parts.append(shlex.quote(cmd_list[i]))
        i += 1

    formatted_cmd = " ".join(formatted_parts)

    if display:
        first = cmd_list[0] if cmd_list else ""
        style_map = {
            "az": ("azure", "[azure]Azure CLI[/azure]"),
            "kubectl": ("kubectl", "[kubectl]Kubernetes[/kubectl]"),
            "flux": ("flux", "[flux]Flux CD[/flux]"),
            "helm": ("helm", "[helm]Helm[/helm]"),
        }
        style, title = style_map.get(first, ("white", "Command"))

        if description:
            title = f"{title}: {description}"

        command_syntax = Syntax(formatted_cmd, "bash", theme="monokai", line_numbers=False)
        console.print(Panel(command_syntax, title=title, border_style=style))

    result = subprocess.run(cmd_list, capture_output=capture_output, text=text)

    if check and result.returncode != 0:
        if result.stderr and result.stderr.strip():
            console.print(Panel(result.stderr.strip(), title="Error Output", border_style="error"))
        console.print(f"[error]Command failed (exit code {result.returncode})[/error]")
        raise typer.Exit(code=1)

    return result


def display_result(success_message: str):
    console.print(f"[success]  {success_message}[/success]")


def display_yaml(content: str, title: str = "Kubernetes YAML"):
    yaml_syntax = Syntax(content.strip(), "yaml", theme="monokai", line_numbers=True)
    console.print(Panel(yaml_syntax, title=f"[bold cyan]{title}[/bold cyan]", border_style="cyan", expand=False))


def get_suspend_status() -> bool:
    """Check if the Flux GitRepository source is suspended."""
    result = subprocess.run(
        ["kubectl", "get", "gitrepository", "osdu-spi-stack-system",
         "-n", "flux-system", "-o", "jsonpath={.spec.suspend}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip().lower() == "true"


# ---------------------------------------------------------------------------
# Cluster identity guard
# ---------------------------------------------------------------------------

SPI_CONTEXT_PREFIX = "spi-stack"


def _get_current_context() -> str:
    """Return the current kubectl context name, or empty string on failure."""
    result = subprocess.run(
        ["kubectl", "config", "current-context"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def _is_spi_context(context: str) -> bool:
    """Check if a context name looks like an spi-stack cluster."""
    return context.startswith(SPI_CONTEXT_PREFIX)


def _has_spi_fingerprint() -> bool:
    """Check if the cluster has the osdu-spi-stack-system deployment.

    Checks kubectl first (GitRepository CRD). If Flux CRDs are not yet
    installed (e.g. right after spi up --no-wait), falls back to checking
    the AKS Flux configuration via az CLI.
    """
    result = subprocess.run(
        ["kubectl", "get", "gitrepository", "osdu-spi-stack-system",
         "-n", "flux-system", "--no-headers"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        return True

    # Flux CRDs may not exist yet; check AKS extension instead
    ctx = _get_current_context()
    cluster_name = ctx if ctx else ""
    if not cluster_name:
        return False
    # Resource group matches cluster name for spi-stack deployments
    result = subprocess.run(
        ["az", "k8s-configuration", "flux", "show",
         "--resource-group", cluster_name,
         "--cluster-name", cluster_name,
         "--cluster-type", "managedClusters",
         "--name", "osdu-spi-stack-system",
         "--query", "provisioningState",
         "--output", "tsv"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def verify_spi_cluster() -> str:
    """Verify the current kubectl context points to an spi-stack cluster.

    Returns the context name on success. Exits with an error if the
    cluster does not appear to be an spi-stack deployment.

    Set SPI_SKIP_GUARD=1 to bypass this check.
    """
    if os.environ.get("SPI_SKIP_GUARD", "") == "1":
        ctx = _get_current_context() or "unknown"
        console.print(f"  [warning]Cluster guard bypassed (SPI_SKIP_GUARD=1), context: {ctx}[/warning]")
        return ctx

    ctx = _get_current_context()
    if not ctx:
        console.print("[error]Cannot determine kubectl context.[/error]")
        console.print("[dim]Make sure your kubeconfig is set and the cluster is running.[/dim]")
        raise typer.Exit(code=1)

    if not _is_spi_context(ctx):
        console.print(f"[error]Current context '{ctx}' does not look like an spi-stack cluster.[/error]")
        console.print(f"[dim]Expected a context starting with '{SPI_CONTEXT_PREFIX}'.[/dim]")
        console.print("[dim]If this is intentional, set SPI_SKIP_GUARD=1 to bypass.[/dim]")
        raise typer.Exit(code=1)

    if not _has_spi_fingerprint():
        console.print(f"[error]Context '{ctx}' is set, but the cluster has no spi-stack deployment.[/error]")
        console.print("[dim]The osdu-spi-stack-system GitRepository was not found in flux-system.[/dim]")
        console.print("[dim]Run 'uv run spi up' to deploy, or set SPI_SKIP_GUARD=1 to bypass.[/dim]")
        raise typer.Exit(code=1)

    return ctx


def kubectl_apply_yaml(
    yaml_content: str,
    description: str,
    retries: int = 4,
    base_delay: int = 2,
) -> subprocess.CompletedProcess:
    """Apply YAML via kubectl with retry/backoff for transient API failures."""
    delay = base_delay
    for attempt in range(1, retries + 1):
        proc = subprocess.run(
            ["kubectl", "apply", "-f", "-"],
            input=yaml_content,
            capture_output=True,
            text=True,
        )
        if proc.returncode == 0:
            return proc

        stderr = (proc.stderr or proc.stdout or "").strip()
        lowered = stderr.lower()
        is_transient = any(marker in lowered for marker in TRANSIENT_KUBECTL_ERRORS)
        if is_transient and attempt < retries:
            console.print(
                f"  [warning]{description} hit a transient Kubernetes API error; "
                f"retrying in {delay}s (attempt {attempt}/{retries})[/warning]"
            )
            time.sleep(delay)
            delay *= 2
            continue

        console.print(f"  [error]Failed to {description}: {stderr or 'unknown error'}[/error]")
        raise typer.Exit(code=1)

    raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Tool prerequisite checks
# ---------------------------------------------------------------------------

def check_tool(name: str, args: Optional[List[str]] = None) -> bool:
    from .checks import check_tool_status
    installed, _ = check_tool_status(name, args)
    return installed


def check_prerequisites(tools: List[str]):
    from .checks import TOOL_REGISTRY, get_install_hint

    console.print("\n[bold]Checking prerequisites...[/bold]")

    missing = []
    for tool in tools:
        info = TOOL_REGISTRY.get(tool, {})
        args = info.get("check_args")
        if check_tool(tool, args):
            console.print(f"  [success]{tool}[/success]")
        else:
            console.print(f"  [error]{tool} -- NOT FOUND[/error]")
            hint = get_install_hint(tool)
            if hint:
                console.print(f"    [info]Install: {hint}[/info]")
            missing.append(tool)

    if missing:
        console.print(f"\n[error]Missing required tools: {', '.join(missing)}[/error]")
        console.print("[dim]Run 'uv run spi check' for full details.[/dim]")
        raise typer.Exit(code=1)


# ---------------------------------------------------------------------------
# Namespace creation
# ---------------------------------------------------------------------------

def _detect_istio_revision() -> str:
    """Detect the installed Istio ASM revision from the cluster."""
    result = subprocess.run(
        ["kubectl", "get", "ns", "aks-istio-system",
         "-o", "jsonpath={.metadata.labels.istio\\.io/rev}"],
        capture_output=True, text=True,
    )
    rev = result.stdout.strip()
    if rev:
        return rev
    # Fallback: check for istiod pods
    result = subprocess.run(
        ["kubectl", "get", "pods", "-n", "aks-istio-system",
         "-o", "jsonpath={.items[0].metadata.labels.istio\\.io/rev}"],
        capture_output=True, text=True,
    )
    return result.stdout.strip() or "asm-1-27"


def ensure_namespaces(istio_revision: str = ""):
    """Create namespaces with Istio sidecar injection labels."""
    console.print("\n[bold]Ensuring namespaces...[/bold]")

    if not istio_revision:
        istio_revision = _detect_istio_revision()
    console.print(f"  [info]Istio revision: {istio_revision}[/info]")

    for ns in ["flux-system", "foundation"]:
        subprocess.run(
            ["kubectl", "create", "namespace", ns],
            capture_output=True, text=True,
        )

    # Namespaces with Istio injection
    for ns in ["platform", "osdu"]:
        yaml_content = f"""\
apiVersion: v1
kind: Namespace
metadata:
  name: {ns}
  labels:
    istio.io/rev: {istio_revision}
"""
        kubectl_apply_yaml(yaml_content, f"create namespace {ns}")

    display_result("Namespaces ready")


# ---------------------------------------------------------------------------
# StorageClass creation
# ---------------------------------------------------------------------------

STORAGE_CLASSES = ["pg-storageclass", "redis-storageclass", "es-storageclass"]


def create_storage_classes():
    """Create Premium StorageClasses for stateful middleware."""
    from .templates import storage_class

    console.print("\n[bold]Creating StorageClasses...[/bold]")
    provisioner = "disk.csi.azure.com"
    extra_params = "  skuName: Premium_LRS"
    console.print(f"  [info]Using provisioner: {provisioner}[/info]")

    for sc_name in STORAGE_CLASSES:
        yaml_content = storage_class(sc_name, provisioner, extra_params)
        display_yaml(yaml_content, f"StorageClass: {sc_name}")
        kubectl_apply_yaml(yaml_content, f"apply StorageClass {sc_name}")
        console.print(f"  [success]{sc_name} created[/success]")


# ---------------------------------------------------------------------------
# Gateway API CRDs
# ---------------------------------------------------------------------------

def install_gateway_api_crds():
    console.print("\n[bold]Installing Gateway API CRDs...[/bold]")
    run_command(
        ["kubectl", "apply", "-f",
         "https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.2.1/standard-install.yaml"],
        description="Install Gateway API CRDs",
    )
    display_result("Gateway API CRDs installed")
