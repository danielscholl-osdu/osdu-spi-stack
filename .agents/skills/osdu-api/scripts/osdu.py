# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
# ]
# ///
"""OSDU API helper for CIMPL deployments.

Usage:
    uv run osdu.py connect              Auto-detect CIMPL, start port-forwards
    uv run osdu.py status               Show connection state
    uv run osdu.py services [--probe]   List or probe discovered services
    uv run osdu.py call METHOD PATH     Make an authenticated API call
    uv run osdu.py token                Print current access token
    uv run osdu.py disconnect           Kill port-forwards, clean state
"""
import argparse
import base64
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import requests

STATE_FILE = Path("/tmp/osdu-api-state.json")

# Base port for dynamic allocation. Keycloak gets BASE_PORT; OSDU services
# get BASE_PORT+1, BASE_PORT+2, ... in alphabetical order of service name.
BASE_PORT = 18080
KEYCLOAK_PORT = BASE_PORT
KEYCLOAK_NAMESPACE = "platform"
KEYCLOAK_SERVICE = "keycloak"

# Known API path prefix -> k8s service name. Used for path-based routing.
# Services not listed here are still accessible via --service flag.
PATH_PREFIXES = {
    # Core services
    "/api/storage/":        "storage",
    "/api/search/":         "search",
    "/api/legal/":          "legal",
    "/api/schema-service/": "schema",
    "/api/entitlements/":   "entitlements",
    "/api/partition/":      "partition",
    "/api/file/":           "file",
    "/api/workflow/":       "workflow",
    "/api/indexer/":        "indexer",
    # Reference services
    "/api/unit/":           "unit",
    "/api/crs/converter/":  "crs-conversion",
    "/api/crs/catalog/":    "crs-catalog",
    # Domain services
    "/api/eds/":            "eds-dms",
}

# Exclusion rules for service discovery
_EXCLUDE_NAMES = {"keycloak", "rabbitmq"}
_EXCLUDE_PREFIXES = ("redis-",)
_EXCLUDE_SUFFIXES = ("-bootstrap",)


def run_kubectl(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["kubectl"] + args, capture_output=True, text=True, timeout=15
    )


def load_state() -> dict | None:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return None
    return None


def save_state(state: dict) -> None:
    STATE_FILE.write_text(json.dumps(state, indent=2))


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def is_pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def kill_pid(pid: int) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass


def start_port_forward(service: str, namespace: str, local_port: int, remote_port: int = 80) -> int:
    """Start a kubectl port-forward as a background process. Returns the PID."""
    proc = subprocess.Popen(
        ["kubectl", "port-forward", "-n", namespace, f"svc/{service}",
         f"{local_port}:{remote_port}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    # Give it a moment to bind
    time.sleep(1.5)
    if proc.poll() is not None:
        raise RuntimeError(
            f"Port-forward to {service}.{namespace} failed to start. "
            f"Is port {local_port} already in use?"
        )
    return proc.pid


def ensure_port_forward(state: dict, service_key: str, service: str,
                        namespace: str, local_port: int) -> dict:
    """Ensure a port-forward is running for the given service. Updates state in place."""
    pf = state.setdefault("port_forwards", {})
    entry = pf.get(service_key)

    if entry and is_pid_alive(entry["pid"]):
        return state

    # All services expose port 80 (kubectl port-forward uses service port, not targetPort)
    remote_port = 80
    pid = start_port_forward(service, namespace, local_port, remote_port)
    pf[service_key] = {
        "pid": pid,
        "local_port": local_port,
        "service": service,
        "namespace": namespace,
        "remote_port": remote_port,
    }
    save_state(state)
    return state


def discover_services() -> dict[str, dict]:
    """Discover OSDU API services from the osdu namespace.

    Scans for ClusterIP services on port 80, excludes infrastructure services.
    Returns dict mapping service_name -> {"namespace": "osdu", "port": <allocated>}.
    """
    result = run_kubectl(["get", "svc", "-n", "osdu", "-o", "json"])
    if result.returncode != 0:
        raise RuntimeError(f"Failed to list services: {result.stderr.strip()}")

    svc_list = json.loads(result.stdout)
    discovered = []

    for item in svc_list.get("items", []):
        name = item["metadata"]["name"]
        spec = item.get("spec", {})

        # Exclude ExternalName services
        if spec.get("type") == "ExternalName":
            continue

        # Exclude by name pattern
        if name in _EXCLUDE_NAMES:
            continue
        if any(name.startswith(p) for p in _EXCLUDE_PREFIXES):
            continue
        if any(name.endswith(s) for s in _EXCLUDE_SUFFIXES):
            continue

        # Only include services with port 80 (OSDU API services)
        ports = spec.get("ports", [])
        if not any(p.get("port") == 80 for p in ports):
            continue

        discovered.append(name)

    # Assign ports deterministically (alphabetical order)
    services = {}
    port = BASE_PORT + 1
    for name in sorted(discovered):
        services[name] = {"namespace": "osdu", "port": port}
        port += 1

    return services


def resolve_service(state: dict, path: str,
                    service_name: str | None = None) -> tuple[str, str, int]:
    """Resolve to (service_name, namespace, local_port).

    If service_name is given (--service flag), look up directly.
    Otherwise, match path against PATH_PREFIXES.
    """
    services = state.get("services", {})
    if not services:
        raise RuntimeError(
            "No services discovered. Run: uv run osdu.py disconnect && uv run osdu.py connect"
        )

    if service_name:
        if service_name not in services:
            raise RuntimeError(
                f"Service '{service_name}' not found. "
                f"Available: {', '.join(sorted(services))}"
            )
        info = services[service_name]
        return service_name, info["namespace"], info["port"]

    # Path-based resolution
    for prefix, svc_name in PATH_PREFIXES.items():
        if path.startswith(prefix):
            if svc_name not in services:
                raise RuntimeError(
                    f"Service '{svc_name}' (from path '{prefix}') not discovered. "
                    f"Available: {', '.join(sorted(services))}"
                )
            info = services[svc_name]
            return svc_name, info["namespace"], info["port"]

    raise RuntimeError(
        f"Cannot resolve service for path: {path}\n"
        f"Use --service NAME to target a specific service.\n"
        f"Available services: {', '.join(sorted(services))}"
    )


def detect_gateway() -> str | None:
    """Detect external gateway IP from the cimpl-gateway in istio-system."""
    result = run_kubectl([
        "get", "gateway", "cimpl-gateway", "-n", "istio-system",
        "-o", "jsonpath={.status.addresses[0].value}",
    ])
    if result.returncode == 0 and result.stdout.strip():
        return result.stdout.strip()
    return None


def detect_cimpl() -> dict:
    """Detect CIMPL environment from kubectl context and extract credentials."""
    result = run_kubectl(["config", "current-context"])
    if result.returncode != 0:
        raise RuntimeError(
            "kubectl not configured or cluster not reachable. "
            "Check your kubeconfig."
        )
    context = result.stdout.strip()

    result = run_kubectl(["get", "namespace", "osdu", "-o", "name"])
    if result.returncode != 0:
        raise RuntimeError(
            f"Namespace 'osdu' not found in context '{context}'. "
            "Is this a CIMPL cluster with OSDU deployed?"
        )

    result = run_kubectl([
        "get", "secret", "datafier-secret", "-n", "osdu", "-o", "json"
    ])
    if result.returncode != 0:
        raise RuntimeError(
            "datafier-secret not found in osdu namespace. "
            "Is the CIMPL stack fully deployed?"
        )

    secret = json.loads(result.stdout)
    data = secret.get("data", {})

    def decode(key: str) -> str:
        val = data.get(key, "")
        return base64.b64decode(val).decode() if val else ""

    client_id = decode("OPENID_PROVIDER_CLIENT_ID") or "datafier"
    client_secret = decode("OPENID_PROVIDER_CLIENT_SECRET")
    provider_url = decode("OPENID_PROVIDER_URL")

    if not client_secret:
        raise RuntimeError(
            "OPENID_PROVIDER_CLIENT_SECRET is empty in datafier-secret."
        )

    gateway_ip = detect_gateway()

    return {
        "cluster_context": context,
        "client_id": client_id,
        "client_secret": client_secret,
        "provider_url": provider_url,
        "gateway_ip": gateway_ip,
        "data_partition": os.environ.get("OSDU_DATA_PARTITION", "osdu"),
    }


def acquire_token(state: dict) -> str:
    """Acquire or refresh a Keycloak access token.

    Always uses port-forward to internal Keycloak so the token ``iss`` claim
    matches what OSDU services expect (``http://keycloak/realms/osdu``).
    """
    token_info = state.get("token", {})
    access_token = token_info.get("access_token")
    expires_at = token_info.get("expires_at", 0)

    if access_token and time.time() < expires_at - 60:
        return access_token

    state = ensure_port_forward(
        state, "keycloak", KEYCLOAK_SERVICE, KEYCLOAK_NAMESPACE, KEYCLOAK_PORT
    )
    token_url = f"http://localhost:{KEYCLOAK_PORT}/realms/osdu/protocol/openid-connect/token"

    # Use Host:keycloak so the token issuer matches what OSDU services expect
    # (http://keycloak/realms/osdu) -- without this, Keycloak sets the issuer
    # to http://localhost:<port>/realms/osdu which services can't validate.
    try:
        resp = requests.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": state["client_id"],
                "client_secret": state["client_secret"],
                "scope": "openid",
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Host": "keycloak",
            },
            timeout=15,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Token acquisition failed: {e}")

    payload = resp.json()
    access_token = payload.get("id_token") or payload.get("access_token")
    if not access_token:
        raise RuntimeError("No access_token or id_token in Keycloak response.")

    state["token"] = {
        "access_token": access_token,
        "expires_at": time.time() + payload.get("expires_in", 300),
    }
    save_state(state)
    return access_token


def make_request(state: dict, method: str, path: str,
                 data: str | None = None, query: str | None = None,
                 partition: str | None = None,
                 service: str | None = None) -> dict | str:
    """Make an authenticated OSDU API request."""
    service_name, namespace, local_port = resolve_service(state, path, service)

    state = ensure_port_forward(state, service_name, service_name, namespace, local_port)

    token = acquire_token(state)

    url = f"http://localhost:{local_port}{path}"
    if query:
        url = f"{url}?{query}"

    headers = {
        "Authorization": f"Bearer {token}",
        "data-partition-id": partition or state.get("data_partition", "osdu"),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = json.loads(data) if data else None

    try:
        resp = requests.request(
            method.upper(), url, json=body, headers=headers, timeout=30
        )
    except requests.RequestException as e:
        raise RuntimeError(f"Request failed: {e}")

    # Auto-refresh token on 401 and retry once
    if resp.status_code == 401:
        state["token"] = {}
        save_state(state)
        token = acquire_token(state)
        headers["Authorization"] = f"Bearer {token}"
        try:
            resp = requests.request(
                method.upper(), url, json=body, headers=headers, timeout=30
            )
        except requests.RequestException as e:
            raise RuntimeError(f"Retry after 401 failed: {e}")

    ct = resp.headers.get("content-type", "")
    if "json" in ct:
        return {"status": resp.status_code, "body": resp.json()}
    return {"status": resp.status_code, "body": resp.text}


def _guess_info_paths(service_name: str) -> list[str]:
    """Generate candidate /info endpoint paths for a service.

    Uses PATH_PREFIXES for known services, otherwise tries common patterns.
    Also tries /about (used by Python-based OSDU services like wellbore).
    """
    paths = []

    # Check known path prefixes first
    for prefix, svc in PATH_PREFIXES.items():
        if svc == service_name:
            for version in ("v2", "v1", "v3"):
                paths.append(f"{prefix.rstrip('/')}/{version}/info")
            paths.append("/about")
            return paths

    # Unknown service: try common OSDU patterns
    for version in ("v2", "v1", "v3"):
        paths.append(f"/api/{service_name}/{version}/info")
    paths.append("/about")

    return paths


# -- Subcommands --

def cmd_connect(args: argparse.Namespace) -> None:
    # Kill existing port-forwards if reconnecting
    old_state = load_state()
    if old_state:
        for entry in old_state.get("port_forwards", {}).values():
            kill_pid(entry.get("pid", 0))

    info = detect_cimpl()
    services = discover_services()

    state = {
        "cluster_context": info["cluster_context"],
        "client_id": info["client_id"],
        "client_secret": info["client_secret"],
        "provider_url": info["provider_url"],
        "gateway_ip": info.get("gateway_ip"),
        "data_partition": info["data_partition"],
        "connected_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "services": services,
        "port_forwards": {},
        "token": {},
    }

    # Acquire token via port-forward with Host:keycloak for correct issuer
    acquire_token(state)

    # Health check using discovered entitlements port
    health_ok = False
    ent = services.get("entitlements")
    if ent:
        try:
            state = ensure_port_forward(
                state, "entitlements", "entitlements", "osdu", ent["port"]
            )
            token = state["token"]["access_token"]
            resp = requests.get(
                f"http://localhost:{ent['port']}/api/entitlements/v2/groups",
                headers={
                    "Authorization": f"Bearer {token}",
                    "data-partition-id": state["data_partition"],
                    "Accept": "application/json",
                },
                timeout=10,
            )
            health_ok = resp.status_code < 500
        except Exception:
            pass

    save_state(state)

    result = {
        "status": "connected",
        "cluster": info["cluster_context"],
        "partition": info["data_partition"],
        "client_id": info["client_id"],
        "gateway": info.get("gateway_ip") or "none (using port-forward)",
        "services_discovered": len(services),
        "services": sorted(services.keys()),
        "token_expires_in": int(state["token"].get("expires_at", 0) - time.time()),
        "port_forwards": list(state["port_forwards"].keys()),
        "health_check": "ok" if health_ok else "warning: entitlements not reachable",
    }
    print(json.dumps(result, indent=2))


def cmd_status(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        print(json.dumps({"status": "disconnected", "message": "No active connection. Run: connect"}))
        return

    pf_status = {}
    for key, entry in state.get("port_forwards", {}).items():
        pid = entry.get("pid", 0)
        pf_status[key] = {
            "pid": pid,
            "port": entry.get("local_port"),
            "alive": is_pid_alive(pid),
        }

    token_info = state.get("token", {})
    expires_at = token_info.get("expires_at", 0)
    ttl = max(0, int(expires_at - time.time()))

    result = {
        "status": "connected",
        "cluster": state.get("cluster_context"),
        "partition": state.get("data_partition"),
        "connected_at": state.get("connected_at"),
        "services_discovered": len(state.get("services", {})),
        "token_ttl_seconds": ttl,
        "token_valid": ttl > 60,
        "port_forwards": pf_status,
    }
    print(json.dumps(result, indent=2))


def cmd_services(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise RuntimeError("Not connected. Run: uv run osdu.py connect")

    services = state.get("services", {})
    if not services:
        raise RuntimeError("No services discovered. Reconnect.")

    if not args.probe:
        result = {
            "count": len(services),
            "services": {
                name: {"port": info["port"]}
                for name, info in sorted(services.items())
            },
        }
        print(json.dumps(result, indent=2))
        return

    # Probe mode: port-forward to each and find their /info endpoint
    probed = {}

    for name in sorted(services):
        info = services[name]
        try:
            state = ensure_port_forward(
                state, name, name, info["namespace"], info["port"]
            )
        except Exception as e:
            probed[name] = {"status": "unreachable", "error": str(e)}
            continue

        # Refresh token each iteration (cached unless near expiry)
        token = acquire_token(state)

        found = False
        for info_path in _guess_info_paths(name):
            try:
                resp = requests.get(
                    f"http://localhost:{info['port']}{info_path}",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "data-partition-id": state.get("data_partition", "osdu"),
                        "Accept": "application/json",
                    },
                    timeout=5,
                )
                if resp.status_code == 200 and "json" in resp.headers.get("content-type", ""):
                    body = resp.json()
                    probed[name] = {
                        "status": "ok",
                        "version": body.get("version", ""),
                        "artifactId": body.get("artifactId", ""),
                        "buildTime": body.get("buildTime", ""),
                    }
                    found = True
                    break
            except Exception:
                continue

        if not found:
            probed[name] = {"status": "reachable", "version": "unknown"}

    save_state(state)
    print(json.dumps({"count": len(probed), "services": probed}, indent=2))


def cmd_call(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise RuntimeError("Not connected. Run: uv run osdu.py connect")

    result = make_request(
        state,
        method=args.method,
        path=args.path,
        data=args.data,
        query=args.query,
        partition=args.partition,
        service=args.service,
    )
    print(json.dumps(result, indent=2))


def cmd_token(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        raise RuntimeError("Not connected. Run: uv run osdu.py connect")

    token = acquire_token(state)
    print(token)


def cmd_disconnect(args: argparse.Namespace) -> None:
    state = load_state()
    if not state:
        print(json.dumps({"status": "already disconnected"}))
        return

    killed = []
    for key, entry in state.get("port_forwards", {}).items():
        pid = entry.get("pid", 0)
        if is_pid_alive(pid):
            kill_pid(pid)
            killed.append(key)

    clear_state()
    print(json.dumps({"status": "disconnected", "stopped": killed}))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="OSDU API helper for CIMPL deployments"
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("connect", help="Auto-detect CIMPL and establish connection")
    sub.add_parser("status", help="Show connection state")
    sub.add_parser("token", help="Print current access token")
    sub.add_parser("disconnect", help="Kill port-forwards and clean state")

    svc_p = sub.add_parser("services", help="List discovered services")
    svc_p.add_argument("--probe", action="store_true",
                        help="Probe each service's /info endpoint for version info")

    call_p = sub.add_parser("call", help="Make an authenticated OSDU API call")
    call_p.add_argument("method", help="HTTP method (GET, POST, PUT, DELETE)")
    call_p.add_argument("path", help="API path (e.g. /api/storage/v2/records/{id})")
    call_p.add_argument("-d", "--data", help="JSON request body")
    call_p.add_argument("-q", "--query", help="Query string (e.g. 'limit=10&offset=0')")
    call_p.add_argument("-p", "--partition", help="Override data partition")
    call_p.add_argument("-s", "--service",
                        help="Target service name directly (bypasses path routing)")

    args = parser.parse_args()

    try:
        {
            "connect": cmd_connect,
            "status": cmd_status,
            "services": cmd_services,
            "call": cmd_call,
            "token": cmd_token,
            "disconnect": cmd_disconnect,
        }[args.command](args)
    except RuntimeError as e:
        print(json.dumps({"error": str(e)}), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
