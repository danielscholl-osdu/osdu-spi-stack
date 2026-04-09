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

"""Cluster access information and endpoint display."""

import json
import subprocess

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.theme import Theme

console = Console(theme=Theme({
    "ready": "bold green",
    "info": "dim white",
    "warning": "bold yellow",
    "error": "bold red",
}))


def _kubectl_json(args: list):
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


def _get_gateway_ip() -> str:
    """Try to find the external IP of the Istio ingress gateway."""
    # AKS managed Istio ingress
    for ns in ["aks-istio-ingress", "istio-system"]:
        data = _kubectl_json(["get", "svc", "-n", ns])
        if not data or "items" not in data:
            continue
        for svc in data["items"]:
            svc_type = svc.get("spec", {}).get("type", "")
            if svc_type == "LoadBalancer":
                ingresses = svc.get("status", {}).get("loadBalancer", {}).get("ingress", [])
                for ing in ingresses:
                    ip = ing.get("ip") or ing.get("hostname")
                    if ip:
                        return ip
    return ""


def _get_live_credentials() -> dict:
    """Retrieve live credentials from Kubernetes secrets."""
    creds = {}

    # Elasticsearch
    es = _kubectl_json(["get", "secret", "elasticsearch-es-elastic-user", "-n", "platform"])
    if es:
        raw = es.get("data", {}).get("elastic", "")
        if raw:
            import base64
            creds["elasticsearch_password"] = base64.b64decode(raw).decode()

    # Redis
    redis = _kubectl_json(["get", "secret", "redis-credentials", "-n", "platform"])
    if redis:
        raw = redis.get("data", {}).get("password", "")
        if raw:
            import base64
            creds["redis_password"] = base64.b64decode(raw).decode()

    return creds


def render_info(show_secrets: bool = False, output_json: bool = False):
    gateway_ip = _get_gateway_ip()

    info = {
        "gateway_ip": gateway_ip,
        "endpoints": {},
        "internal_services": {},
    }

    if gateway_ip:
        base = f"http://{gateway_ip}"
        info["endpoints"] = {
            "partition": f"{base}/api/partition/v1/",
            "entitlements": f"{base}/api/entitlements/v2/",
            "legal": f"{base}/api/legal/v1/",
            "schema": f"{base}/api/schema-service/v1/",
            "storage": f"{base}/api/storage/v2/",
            "search": f"{base}/api/search/v2/",
            "file": f"{base}/api/file/",
            "workflow": f"{base}/api/workflow/",
        }

    info["internal_services"] = {
        "elasticsearch": "elasticsearch-es-http.platform.svc:9200",
        "redis": "redis-master.platform.svc:6380 (TLS)",
        "postgresql": "postgresql-rw.platform.svc:5432 (Airflow only)",
        "airflow": "airflow-web.platform.svc:8080",
    }

    if show_secrets:
        info["credentials"] = _get_live_credentials()

    if output_json:
        print(json.dumps(info, indent=2))
        return

    # Human-readable display
    console.print(Panel("[bold]SPI Stack Access Information[/bold]", border_style="cyan"))

    if gateway_ip:
        console.print(f"\n  [ready]Gateway IP:[/ready] {gateway_ip}")
    else:
        console.print("\n  [warning]Gateway IP not yet assigned (LoadBalancer pending)[/warning]")

    if info["endpoints"]:
        table = Table(title="OSDU API Endpoints", border_style="cyan")
        table.add_column("Service", style="cyan")
        table.add_column("URL", style="green")
        for svc, url in info["endpoints"].items():
            table.add_row(svc, url)
        console.print(table)

    table = Table(title="Internal Services", border_style="cyan")
    table.add_column("Service", style="cyan")
    table.add_column("Address", style="green")
    for svc, addr in info["internal_services"].items():
        table.add_row(svc, addr)
    console.print(table)

    if show_secrets and "credentials" in info:
        table = Table(title="Live Credentials (dev/test only)", border_style="yellow")
        table.add_column("Secret", style="cyan")
        table.add_column("Value", style="yellow")
        for k, v in info["credentials"].items():
            table.add_row(k, v)
        console.print(table)
