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

"""Non-blocking runtime writes that bridge the in-cluster seed into Key Vault.

After Flux is registered, the CLI writes the small set of runtime secrets
OSDU services fetch via KeyVaultFacade at startup (tbl-storage-endpoint,
redis-*, {partition}-elastic-*). The values either come from infra outputs
or from the in-cluster seed (``spi-secrets``) that the CLI generated
earlier, so none of this needs to wait for Flux to reconcile middleware.

The previous cross-namespace CA copies and the Redis Istio DestinationRule
moved into Flux as Pass 1 of ADR-011
(``software/stacks/osdu/bootstrap/``); those were the only blocking steps.
The CLI now returns as soon as this file finishes.
"""

from .config import Config
from .helpers import (
    console,
    display_result,
    run_command,
)


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
