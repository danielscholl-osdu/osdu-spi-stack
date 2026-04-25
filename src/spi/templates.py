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

"""YAML templates for Kubernetes resources."""


def storage_class(
    name: str,
    provisioner: str,
    extra_params: str = "",
    reclaim_policy: str = "Delete",
    allow_volume_expansion: bool = True,
) -> str:
    yaml = f"""\
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: {name}
  labels:
    app.kubernetes.io/managed-by: osdu-spi-stack
provisioner: {provisioner}
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: {reclaim_policy}
allowVolumeExpansion: {str(allow_volume_expansion).lower()}"""
    if extra_params:
        yaml += f"\nparameters:\n{extra_params}"
    return yaml


def osdu_config_configmap(
    domain: str,
    data_partition: str,
    tenant_id: str,
    identity_client_id: str,
    keyvault_uri: str,
    keyvault_name: str,
    cosmosdb_endpoint: str,
    storage_account_name: str,
    servicebus_namespace: str,
    appinsights_key: str = "",
) -> str:
    """ConfigMap with Azure PaaS endpoints for OSDU services."""
    return f"""\
apiVersion: v1
kind: ConfigMap
metadata:
  name: osdu-config
  namespace: osdu
  labels:
    app.kubernetes.io/managed-by: osdu-spi-stack
data:
  DOMAIN: "{domain}"
  DATA_PARTITION: "{data_partition}"
  AZURE_TENANT_ID: "{tenant_id}"
  AAD_CLIENT_ID: "{identity_client_id}"
  KEYVAULT_URI: "{keyvault_uri}"
  KEYVAULT_URL: "{keyvault_uri}"
  KEYVAULT_NAME: "{keyvault_name}"
  COSMOSDB_ENDPOINT: "{cosmosdb_endpoint}"
  COSMOSDB_DATABASE: "osdu-db"
  STORAGE_ACCOUNT_NAME: "{storage_account_name}"
  SERVICEBUS_NAMESPACE: "{servicebus_namespace}"
  REDIS_HOSTNAME: "platform-redis-master.platform.svc.cluster.local"
  REDIS_PORT: "6379"
  SERVER_PORT: "8080"
  APPINSIGHTS_KEY: "{appinsights_key}"
  ELASTICSEARCH_HOST: "elasticsearch-es-http.platform.svc.cluster.local"
"""


def workload_identity_sa(namespace: str, client_id: str, tenant_id: str) -> str:
    """Workload Identity ServiceAccount for OSDU services."""
    return f"""\
apiVersion: v1
kind: ServiceAccount
metadata:
  name: workload-identity-sa
  namespace: {namespace}
  annotations:
    azure.workload.identity/client-id: "{client_id}"
    azure.workload.identity/tenant-id: "{tenant_id}"
  labels:
    azure.workload.identity/use: "true"
    app.kubernetes.io/managed-by: osdu-spi-stack
"""


def spi_init_values_configmap(partitions: list[str]) -> str:
    """ConfigMap consumed by the osdu-spi-init HelmRelease via valuesFrom.

    Lives in flux-system (where the HelmRelease is reconciled) and carries the
    full Helm values YAML. The CLI writes it based on --partition flags so that
    enabling a new partition is a CLI argument change, not a git edit.
    """
    partition_lines = "\n".join(f"    - {p}" for p in partitions)
    return f"""\
apiVersion: v1
kind: ConfigMap
metadata:
  name: spi-init-values
  namespace: flux-system
  labels:
    app.kubernetes.io/managed-by: osdu-spi-stack
data:
  values.yaml: |
    partitions:
{partition_lines}
"""
