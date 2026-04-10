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


def git_repository(url: str, branch: str) -> str:
    """Flux GitRepository source for the SPI stack."""
    return f"""\
apiVersion: source.toolkit.fluxcd.io/v1
kind: GitRepository
metadata:
  name: osdu-spi-stack-system
  namespace: flux-system
spec:
  interval: 5m
  url: {url}
  ref:
    branch: {branch}"""


def stack_kustomization(profile: str) -> str:
    """Top-level Flux Kustomization that deploys the selected profile."""
    return f"""\
apiVersion: kustomize.toolkit.fluxcd.io/v1
kind: Kustomization
metadata:
  name: osdu-spi-stack
  namespace: flux-system
spec:
  interval: 10m
  sourceRef:
    kind: GitRepository
    name: osdu-spi-stack-system
  path: ./software/stacks/osdu/profiles/{profile}
  prune: true
  wait: true
  timeout: 30m"""


def storage_class(name: str, provisioner: str, extra_params: str = "") -> str:
    yaml = f"""\
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: {name}
  labels:
    app.kubernetes.io/managed-by: osdu-spi-stack
provisioner: {provisioner}
volumeBindingMode: WaitForFirstConsumer
reclaimPolicy: Delete"""
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
