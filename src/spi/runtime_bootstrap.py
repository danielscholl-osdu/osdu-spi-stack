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

"""Runtime bootstrap steps that bridge in-cluster middleware and OSDU services.

These actions can only run after Flux has deployed middleware (Redis, ES),
so they execute after the GitOps handoff. They:

  - Copy the Redis and Elasticsearch CA certs into the osdu namespace so
    the osdu-spi-service chart init container can import them into the
    Java truststore.
  - Apply an Istio DestinationRule that disables mTLS for traffic to the
    in-cluster Redis. Lettuce speaks TLS directly; Istio must not double-wrap.
  - Populate Key Vault with the small set of secrets that OSDU services
    fetch via KeyVaultFacade at startup (tbl-storage-endpoint, redis, ES).

This mirrors the reference Terraform in osdu-spi-infra/software/spi-stack/
osdu-common.tf which uses null_resource + local-exec for the same purpose.
"""

import base64
import subprocess
import time
from typing import Optional

from .config import Config
from .helpers import (
    console,
    display_result,
    kubectl_apply_yaml,
    run_command,
)


def _wait_for_secret(
    namespace: str,
    secret_name: str,
    data_key: str,
    label: str,
    timeout_seconds: int = 600,
    poll_interval: int = 10,
) -> Optional[str]:
    """Poll for a kube secret to appear and return the decoded value of one key.

    Returns None if the secret does not appear within timeout_seconds.
    """
    attempts = max(1, timeout_seconds // poll_interval)
    for attempt in range(1, attempts + 1):
        result = subprocess.run(
            [
                "kubectl", "get", "secret", secret_name,
                "-n", namespace,
                "-o", f"jsonpath={{.data.{data_key.replace('.', '\\.')}}}",
            ],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return base64.b64decode(result.stdout.strip()).decode()
            except Exception:
                return None
        console.print(
            f"  [info]Waiting for {label} ({namespace}/{secret_name})... "
            f"attempt {attempt}/{attempts}[/info]"
        )
        time.sleep(poll_interval)
    return None


def _create_ca_secret_in_osdu(dest_name: str, ca_pem: str, label: str):
    """Create a generic opaque secret with a single ca.crt key in the osdu namespace."""
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".crt", delete=False) as f:
        f.write(ca_pem)
        cert_path = f.name

    # Use create --from-file | apply to avoid shell-escaping and preserve trailing newlines.
    create = subprocess.run(
        [
            "kubectl", "create", "secret", "generic", dest_name,
            "-n", "osdu",
            f"--from-file=ca.crt={cert_path}",
            "--dry-run=client", "-o", "yaml",
        ],
        capture_output=True,
        text=True,
    )
    if create.returncode != 0:
        console.print(f"  [error]Failed to render {label} secret: {create.stderr}[/error]")
        return

    kubectl_apply_yaml(create.stdout, f"apply {label} secret in osdu namespace")
    display_result(f"{label} CA cert copied to osdu namespace")


def copy_redis_ca_to_osdu(timeout_seconds: int = 600):
    """Copy the Redis TLS CA from platform to osdu namespace.

    Polls for the cert-manager issued secret, then creates a generic secret
    named redis-ca-cert in osdu that the osdu-spi-service chart mounts into
    its import-ca-certs init container.
    """
    console.print("\n[bold]Copying Redis CA cert to osdu namespace...[/bold]")
    ca = _wait_for_secret(
        namespace="platform",
        secret_name="redis-tls-secret",
        data_key="ca.crt",
        label="Redis TLS CA",
        timeout_seconds=timeout_seconds,
    )
    if not ca:
        console.print("  [warning]Redis CA cert not ready; OSDU services with redisTls will fail to start.[/warning]")
        return
    _create_ca_secret_in_osdu("redis-ca-cert", ca, "Redis")


def copy_elastic_ca_to_osdu(timeout_seconds: int = 600):
    """Copy the Elasticsearch HTTP CA from platform to osdu namespace.

    ECK publishes the HTTP CA as secret elasticsearch-es-http-certs-public.
    Search and indexer services need this CA imported into their truststore.
    """
    console.print("\n[bold]Copying Elasticsearch CA cert to osdu namespace...[/bold]")
    ca = _wait_for_secret(
        namespace="platform",
        secret_name="elasticsearch-es-http-certs-public",
        data_key="ca.crt",
        label="Elasticsearch HTTP CA",
        timeout_seconds=timeout_seconds,
    )
    if not ca:
        console.print("  [warning]Elasticsearch CA cert not ready; search/indexer will fail to start.[/warning]")
        return
    _create_ca_secret_in_osdu("elastic-ca-cert", ca, "Elasticsearch")


def apply_redis_destination_rule():
    """Disable Istio mTLS for traffic to in-cluster Redis.

    Lettuce (the Java Redis client) speaks TLS directly to Redis. Without
    this DestinationRule, Istio also wraps the connection in mTLS and the
    TLS-in-TLS layering breaks.
    """
    console.print("\n[bold]Applying Redis DestinationRule (disable mTLS)...[/bold]")
    yaml_content = """\
apiVersion: networking.istio.io/v1
kind: DestinationRule
metadata:
  name: redis-disable-mtls
  namespace: osdu
  labels:
    app.kubernetes.io/managed-by: osdu-spi-stack
spec:
  host: platform-redis-master.platform.svc.cluster.local
  trafficPolicy:
    tls:
      mode: DISABLE
"""
    kubectl_apply_yaml(yaml_content, "apply redis-disable-mtls DestinationRule")
    display_result("redis-disable-mtls DestinationRule applied")


def write_keyvault_bootstrap_secrets(
    config: Config,
    keyvault_name: str,
    storage_account_name: str,
    elastic_password: str,
    redis_password: str,
):
    """Write the small set of secrets that OSDU services read at startup.

    Partition reads tbl-storage-endpoint to locate its metadata table.
    Indexer and workflow read redis-hostname/redis-password via KeyVaultFacade.
    Search and indexer read {partition}-elastic-* via partition service API.
    """
    console.print("\n[bold]Writing OSDU bootstrap secrets to Key Vault...[/bold]")
    partition = config.primary_partition
    tbl_endpoint = f"https://{storage_account_name}.table.core.windows.net/"
    elastic_endpoint = "https://elasticsearch-es-http.platform.svc.cluster.local:9200"
    redis_hostname = "platform-redis-master.platform.svc.cluster.local"

    secrets_to_write = [
        ("tbl-storage-endpoint", tbl_endpoint),
        ("redis-hostname", redis_hostname),
        ("redis-password", redis_password),
        (f"{partition}-elastic-endpoint", elastic_endpoint),
        (f"{partition}-elastic-username", "elastic"),
        (f"{partition}-elastic-password", elastic_password),
    ]

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
