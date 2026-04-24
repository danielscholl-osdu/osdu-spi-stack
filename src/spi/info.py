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

"""Cluster access information and endpoint display.

Reads the `spi-ingress-config` ConfigMap written by the CLI at bootstrap
and renders the right base URL / middleware UI table per ingress mode:

  - ip:    http://<gateway-ip>/api/...                   (no middleware UIs)
  - azure: https://<auto-fqdn>/api/...  +  /kibana/  /airflow/
  - dns:   https://<host-osdu>/api/...  +  <host-kibana>  <host-airflow>
"""

import base64
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

# OSDU API services exposed via HTTPRoutes. Order preserved for display.
_OSDU_API_PATHS = [
    ("partition",       "/api/partition/v1/"),
    ("entitlements",    "/api/entitlements/v2/"),
    ("legal",           "/api/legal/v1/"),
    ("schema",          "/api/schema-service/v1/"),
    ("storage",         "/api/storage/v2/"),
    ("search",          "/api/search/v2/"),
    ("indexer",         "/api/indexer/v2/"),
    ("indexer-queue",   "/api/indexer-queue/v1/"),
    ("file",            "/api/file/v2/"),
    ("workflow",        "/api/workflow/v1/"),
    ("unit",            "/api/unit/v3/"),
    ("crs-catalog",     "/api/crs/catalog/v2/"),
    ("crs-conversion",  "/api/crs/converter/v2/"),
]


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


def _secret_value(namespace: str, name: str, key: str) -> str:
    """Read a base64-decoded value from a k8s Secret. Empty string on error."""
    data = _kubectl_json(["get", "secret", name, "-n", namespace])
    if not data:
        return ""
    raw = data.get("data", {}).get(key, "")
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode()
    except (ValueError, UnicodeDecodeError):
        return ""


def _read_ingress_config() -> dict:
    """Read the CLI-written spi-ingress-config ConfigMap. Empty dict if missing."""
    data = _kubectl_json(["get", "configmap", "spi-ingress-config", "-n", "flux-system"])
    if not data:
        return {}
    return data.get("data", {}) or {}


def _compute_endpoints(cfg: dict) -> tuple:
    """Return (mode, base_url, endpoints_dict, middleware_dict).

    mode: "ip" | "azure" | "dns"
    base_url: full URL for the primary host, or "" if not yet known.
    endpoints_dict: {"partition": "http(s)://...", ...} for all 13 services.
    middleware_dict: {"Kibana": url, "Airflow": url} — empty in ip mode.
    """
    mode = (cfg.get("INGRESS_MODE") or "").lower()

    if mode == "azure":
        fqdn = cfg.get("INGRESS_FQDN", "")
        base = f"https://{fqdn}" if fqdn else ""
        endpoints = {svc: f"{base}{path}" for svc, path in _OSDU_API_PATHS} if base else {}
        middleware = {"Kibana": f"{base}/kibana/", "Airflow": f"{base}/airflow/"} if base else {}
        return mode, base, endpoints, middleware

    if mode == "dns":
        osdu_host = cfg.get("INGRESS_HOST_OSDU", "")
        kibana_host = cfg.get("INGRESS_HOST_KIBANA", "")
        airflow_host = cfg.get("INGRESS_HOST_AIRFLOW", "")
        base = f"https://{osdu_host}" if osdu_host else ""
        endpoints = {svc: f"{base}{path}" for svc, path in _OSDU_API_PATHS} if base else {}
        middleware = {}
        if kibana_host:
            middleware["Kibana"] = f"https://{kibana_host}/"
        if airflow_host:
            middleware["Airflow"] = f"https://{airflow_host}/"
        return mode, base, endpoints, middleware

    # Fallback: ip mode or no ConfigMap yet.
    ip = cfg.get("GATEWAY_IP", "") or _discover_gateway_ip()
    base = f"http://{ip}" if ip else ""
    endpoints = {svc: f"{base}{path}" for svc, path in _OSDU_API_PATHS} if base else {}
    return "ip", base, endpoints, {}


def _discover_gateway_ip() -> str:
    """Fallback: find the Istio ingress LB IP when the ConfigMap is missing."""
    for ns in ["aks-istio-ingress", "istio-system"]:
        data = _kubectl_json(["get", "svc", "-n", ns])
        if not data or "items" not in data:
            continue
        for svc in data["items"]:
            if svc.get("spec", {}).get("type") != "LoadBalancer":
                continue
            for ing in svc.get("status", {}).get("loadBalancer", {}).get("ingress", []):
                ip = ing.get("ip") or ing.get("hostname")
                if ip:
                    return ip
    return ""


def _get_live_credentials() -> dict:
    """Retrieve in-cluster credentials for the middleware UIs."""
    creds = {}
    elastic_pw = _secret_value("platform", "elasticsearch-es-elastic-user", "elastic")
    if elastic_pw:
        creds["elastic_user"] = "elastic"
        creds["elastic_password"] = elastic_pw
    redis_pw = _secret_value("platform", "redis-credentials", "password")
    if redis_pw:
        creds["redis_password"] = redis_pw
    airflow_pw = _secret_value("platform", "airflow-webserver-credentials", "password")
    if airflow_pw:
        creds["airflow_user"] = "admin"
        creds["airflow_password"] = airflow_pw
    return creds


def render_info(show_secrets: bool = False, output_json: bool = False):
    cfg = _read_ingress_config()
    mode, base, endpoints, middleware = _compute_endpoints(cfg)

    info = {
        "ingress_mode": mode,
        "base_url": base,
        "endpoints": endpoints,
        "middleware_uis": middleware,
        "internal_services": {
            "elasticsearch": "elasticsearch-es-http.platform.svc:9200",
            "redis": "redis-master.platform.svc:6380 (TLS)",
            "postgresql": "postgresql-rw.platform.svc:5432 (Airflow only)",
        },
    }

    if show_secrets:
        info["credentials"] = _get_live_credentials()

    if output_json:
        print(json.dumps(info, indent=2))
        return

    # Human-readable display
    console.print(Panel("[bold]SPI Stack Access Information[/bold]", border_style="cyan"))
    console.print(f"\n  [ready]Ingress mode:[/ready] {mode or 'unknown'}")
    if base:
        console.print(f"  [ready]Base URL:    [/ready] {base}")
    else:
        console.print(
            "  [warning]Base URL not yet available — ingress is still "
            "provisioning. Re-run 'spi info' in a minute.[/warning]"
        )

    if endpoints:
        table = Table(title="OSDU API Endpoints", border_style="cyan")
        table.add_column("Service", style="cyan")
        table.add_column("URL", style="green")
        for svc, url in endpoints.items():
            table.add_row(svc, url)
        console.print(table)

    if middleware:
        table = Table(title="Middleware UIs", border_style="cyan")
        table.add_column("UI", style="cyan")
        table.add_column("URL", style="green")
        for name, url in middleware.items():
            table.add_row(name, url)
        console.print(table)

    table = Table(title="Internal Services", border_style="cyan")
    table.add_column("Service", style="cyan")
    table.add_column("Address", style="green")
    for svc, addr in info["internal_services"].items():
        table.add_row(svc, addr)
    console.print(table)

    if show_secrets and info.get("credentials"):
        table = Table(title="Live Credentials (dev/test only)", border_style="yellow")
        table.add_column("Secret", style="cyan")
        table.add_column("Value", style="yellow")
        for k, v in info["credentials"].items():
            table.add_row(k, v)
        console.print(table)
