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

"""Configuration models for SPI Stack."""

from enum import Enum
from typing import List

from pydantic import BaseModel


class Profile(str, Enum):
    CORE = "core"
    FULL = "full"


class IngressMode(str, Enum):
    # Auto-FQDN (<label>.<region>.cloudapp.azure.com) + Let's Encrypt TLS.
    # Default. Zero prerequisites.
    AZURE = "azure"
    # Real DNS zone + ExternalDNS + Let's Encrypt TLS. Zone auto-discovered
    # from the current subscription.
    DNS = "dns"
    # Bare IP, HTTP only, no TLS. Hidden fallback for air-gapped debug.
    IP = "ip"


BASE_NAME = "spi-stack"


class Config(BaseModel):
    profile: Profile = Profile.CORE
    env: str = ""
    repo_url: str = "https://github.com/danielscholl-osdu/osdu-spi-stack.git"
    repo_branch: str = "main"
    cluster_name: str = BASE_NAME
    # Azure
    resource_group: str = BASE_NAME
    location: str = "eastus2"
    # Data partitions
    data_partitions: List[str] = ["opendes"]
    # Derived names (set in from_env)
    identity_name: str = ""
    external_dns_identity_name: str = ""
    keyvault_name: str = ""
    acr_name: str = ""
    # Ingress / DNS
    ingress_mode: IngressMode = IngressMode.AZURE
    dns_zone: str = ""           # dns mode: auto-discovered if empty
    dns_zone_rg: str = ""        # dns mode: derived from zone lookup
    ingress_prefix: str = ""     # defaults to env
    acme_email: str = ""         # defaults to admin@<fqdn>|<zone>
    ingress_fqdn: str = ""       # azure mode: resolved LB FQDN
    # Output control
    verbose: bool = False

    @staticmethod
    def from_env(env: str, **kwargs) -> "Config":
        """Create config with names derived from --env suffix."""
        cluster_name = f"{BASE_NAME}-{env}" if env else BASE_NAME
        resource_group = f"{BASE_NAME}-{env}" if env else BASE_NAME

        # Azure naming: alphanumeric only, 3-24 chars for KV, 5-50 for ACR
        safe_env = env.replace("-", "").replace("_", "")
        keyvault_name = f"osdu{safe_env}"[:24] if env else "osduspistack"
        acr_name = f"osdu{safe_env}"[:50] if env else "osduspistack"
        identity_name = f"{cluster_name}-osdu-identity"
        external_dns_identity_name = f"{cluster_name}-external-dns"

        return Config(
            env=env,
            cluster_name=cluster_name,
            resource_group=resource_group,
            identity_name=identity_name,
            external_dns_identity_name=external_dns_identity_name,
            keyvault_name=keyvault_name,
            acr_name=acr_name,
            **kwargs,
        )

    @property
    def env_flag(self) -> str:
        """Return the --env flag string for display in next-steps."""
        return f" --env {self.env}" if self.env else ""

    @property
    def primary_partition(self) -> str:
        """First data partition hosts the system database."""
        return self.data_partitions[0]

    @property
    def resolved_ingress_prefix(self) -> str:
        """DNS-mode hostname prefix. Falls back to env name, then 'spi'."""
        return self.ingress_prefix or self.env or "spi"

    @property
    def dns_label(self) -> str:
        """Azure-mode DNS label for the Istio ingress PIP.

        Uses cluster_name with an '-ingress' suffix so it doesn't collide
        with the AKS-default 'aks-istio-ingressgateway-external' PIP,
        which is provisioned unconditionally by AKS Automatic and may
        briefly receive the same label through annotation races.
        """
        return f"{self.cluster_name}-ingress"
