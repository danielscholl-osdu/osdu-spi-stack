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

"""Deployment status dashboard."""

import json
import subprocess
import time

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

console = Console(theme=Theme({
    "ready": "bold green",
    "progressing": "bold yellow",
    "failed": "bold red",
    "info": "dim white",
}))

# Dependency order matching the 7-layer Kustomization stack (ADR-007).
# Items not in this list sort to the end alphabetically.
_KUSTOMIZATION_ORDER = [
    "osdu-spi-stack-system-stack",
    "spi-namespaces",
    "spi-nodepools",
    "spi-cert-manager",
    "spi-eck-operator",
    "spi-cnpg-operator",
    "spi-gateway",
    "spi-elasticsearch",
    "spi-redis",
    "spi-postgresql",
    "spi-airflow",
    "spi-osdu-config",
    "spi-osdu-services",
    "spi-osdu-reference",
]
_KUSTOMIZATION_RANK = {name: i for i, name in enumerate(_KUSTOMIZATION_ORDER)}


def _kubectl_json(args: list) -> dict | list | None:
    result = subprocess.run(
        ["kubectl"] + args + ["-o", "json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except (json.JSONDecodeError, ValueError):
        return None


def _status_style(status: str, ready_ratio: str = "") -> str:
    s = status.lower()
    if s in ("true", "ready", "complete", "succeeded"):
        return "ready"
    if s == "running" and ready_ratio:
        # Running but not all containers ready is progressing, not ready
        parts = ready_ratio.split("/")
        if len(parts) == 2 and parts[0] == parts[1] and parts[0] != "0":
            return "ready"
        return "progressing"
    if s == "running":
        return "ready"
    if s in ("false", "failed", "error", "crashloopbackoff"):
        return "failed"
    return "progressing"


def _render_kustomizations():
    table = Table(title="Flux Kustomizations", border_style="cyan", expand=True)
    table.add_column("Name", style="cyan")
    table.add_column("Ready", justify="center")
    table.add_column("Status")

    data = _kubectl_json(["get", "kustomizations", "-n", "flux-system"])
    if not data or "items" not in data:
        console.print("  [info]No Kustomizations found[/info]")
        return

    items = sorted(
        data["items"],
        key=lambda x: _KUSTOMIZATION_RANK.get(x["metadata"]["name"], 999),
    )
    for item in items:
        name = item["metadata"]["name"]
        conditions = item.get("status", {}).get("conditions", [])
        ready = "Unknown"
        message = ""
        for c in conditions:
            if c.get("type") == "Ready":
                ready = c.get("status", "Unknown")
                message = c.get("message", "")[:60]
                break
        style = _status_style(ready)
        table.add_row(name, f"[{style}]{ready}[/{style}]", message)

    console.print(table)


def _render_helmreleases():
    table = Table(title="Helm Releases", border_style="cyan", expand=True)
    table.add_column("Name", style="cyan")
    table.add_column("Ready", justify="center")
    table.add_column("Revision")
    table.add_column("Status")

    data = _kubectl_json(["get", "helmreleases", "-n", "flux-system"])
    if not data or "items" not in data:
        console.print("  [info]No HelmReleases found[/info]")
        return

    for item in data["items"]:
        name = item["metadata"]["name"]
        conditions = item.get("status", {}).get("conditions", [])
        ready = "Unknown"
        message = ""
        for c in conditions:
            if c.get("type") == "Ready":
                ready = c.get("status", "Unknown")
                message = c.get("message", "")[:50]
                break
        revision = item.get("status", {}).get("lastAppliedRevision", "")
        style = _status_style(ready)
        table.add_row(name, f"[{style}]{ready}[/{style}]", revision[:20], message)

    console.print(table)


def _render_pods(namespace: str, title: str):
    table = Table(title=f"Pods: {title}", border_style="cyan", expand=True)
    table.add_column("Name", style="cyan")
    table.add_column("Ready", justify="center")
    table.add_column("Status")
    table.add_column("Restarts", justify="right")

    data = _kubectl_json(["get", "pods", "-n", namespace])
    if not data or "items" not in data:
        console.print(f"  [info]No pods in {namespace}[/info]")
        return

    for pod in data["items"]:
        name = pod["metadata"]["name"]
        phase = pod.get("status", {}).get("phase", "Unknown")
        containers = pod.get("status", {}).get("containerStatuses", [])
        ready_count = sum(1 for c in containers if c.get("ready"))
        total = len(containers)
        restarts = sum(c.get("restartCount", 0) for c in containers)
        ready_str = f"{ready_count}/{total}"
        style = _status_style(phase, ready_str)
        table.add_row(name[:50], ready_str, f"[{style}]{phase}[/{style}]", str(restarts))

    console.print(table)


def render_status():
    console.print(Panel("[bold]SPI Stack Deployment Status[/bold]", border_style="cyan"))
    _render_kustomizations()
    console.print()
    _render_helmreleases()
    console.print()
    _render_pods("foundation", "Foundation")
    console.print()
    _render_pods("platform", "Platform (Middleware)")
    console.print()
    _render_pods("osdu", "OSDU Services")


def watch_status():
    try:
        while True:
            console.clear()
            render_status()
            console.print(f"\n[info]Refreshing every 30s. Press Ctrl+C to stop.[/info]")
            time.sleep(30)
    except KeyboardInterrupt:
        console.print("\n[info]Watch stopped.[/info]")
