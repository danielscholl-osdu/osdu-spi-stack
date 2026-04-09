#!/usr/bin/env -S uv run --script
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
# /// script
# requires-python = ">=3.8"
# dependencies = [
#     "defusedxml",
# ]
# ///
"""
OSDU Java Integration Test Runner

Runs Java integration tests from an OSDU service repository against a live
SPI Stack environment. Resolves environment configuration (URLs, auth) from
the running cluster via ``uv run spi info --json`` and Azure CLI.

Usage:
  uv run javatest_integration.py --service partition
  uv run javatest_integration.py --service partition --dry-run
  uv run javatest_integration.py --service storage --endpoint https://my.osdu.host

Features:
  - Automatic environment resolution from the live SPI Stack cluster
  - Azure Entra ID authentication via az CLI
  - Config.java parsing to discover required env vars
  - Secure credential handling (secrets never appear in logs or command lines)
  - Surefire XML result parsing with structured output
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from defusedxml import ElementTree

# =============================================================================
# CONSTANTS
# =============================================================================

SECRET_PATTERNS = {"secret", "token", "password", "credential"}

# Service API path prefixes — used by HOST_URL which some services expect to
# include the full API path (e.g., legal expects "https://host/api/legal/v1/")
# Services not listed here get just the base endpoint with trailing slash.
SERVICE_API_PATHS = {
    "legal": "/api/legal/v1/",
    "storage": "/api/storage/v2/",
    "search": "/api/search/v2/",
    "indexer": "/api/indexer/v2/",
    "file": "/api/file/v2/",
    "workflow": "/api/workflow/v1/",
    "notification": "/api/notification/v1/",
    "register": "/api/register/v1/",
    "schema": "/api/schema-service/v1/",
    "dataset": "/api/dataset/v1/",
    "unit": "/api/unit/v3/",
    "crs-catalog": "/api/crs/catalog/",
    "crs-conversion": "/api/crs/converter/",
    "entitlements": "/api/entitlements/v2/",
}

# Static mapping: env var name -> lambda(EnvConfig) -> value
# Only variables discovered in Config.java (or core auth vars) will be set.
# Note: Service URL vars include a trailing slash — many test Config.java files
# expect it (e.g., partition's Config.java: "PARTITION_BASE_URL has a '/' at the end")
MAPPING_RULES = {
    # Service URL variables (trailing slash required by test conventions)
    "PARTITION_BASE_URL": lambda c: c.osdu_endpoint + "/",
    "STORAGE_URL": lambda c: c.osdu_endpoint + "/",
    "LEGAL_URL": lambda c: c.osdu_endpoint + "/",
    "SEARCH_URL": lambda c: c.osdu_endpoint + "/",
    "ENTITLEMENTS_URL": lambda c: c.osdu_endpoint + "/",
    "SCHEMA_URL": lambda c: c.osdu_endpoint + "/",
    "FILE_URL": lambda c: c.osdu_endpoint + "/",
    "WORKFLOW_URL": lambda c: c.osdu_endpoint + "/",
    "UNIT_URL": lambda c: c.osdu_endpoint + "/",
    "REGISTER_URL": lambda c: c.osdu_endpoint + "/",
    "DATASET_URL": lambda c: c.osdu_endpoint + "/",
    "NOTIFICATION_URL": lambda c: c.osdu_endpoint + "/",
    "CRS_CATALOG_URL": lambda c: c.osdu_endpoint + "/",
    "CRS_CONVERSION_URL": lambda c: c.osdu_endpoint + "/",
    # HOST_URL is set dynamically per-service — see build_mapping()
    # Tenant variables
    "MY_TENANT": lambda c: c.tenant,
    "DATA_PARTITION_ID": lambda c: c.tenant,
    "DEFAULT_PARTITION": lambda c: c.tenant,
    "CLIENT_TENANT": lambda _: "common",
    # Azure Entra ID auth variables
    "AZURE_AD_TENANT_ID": lambda c: c.azure_tenant_id,
    "AZURE_AD_APP_RESOURCE_ID": lambda c: c.azure_client_id,
    "AZURE_TESTER_SERVICEPRINCIPAL_SECRET": lambda c: c.azure_token,
    "INTEGRATION_TESTER": lambda c: c.azure_client_id,
    "NO_DATA_ACCESS_TESTER": lambda c: c.azure_client_id,
    "NO_DATA_ACCESS_TESTER_SERVICEPRINCIPAL_SECRET": lambda c: c.azure_token,
    # Azure resource variables
    "AZURE_AD_OTHER_APP_RESOURCE_ID": lambda c: c.azure_client_id,
    "KEYVAULT_URI": lambda c: c.keyvault_uri,
    "STORAGE_ACCOUNT": lambda c: c.storage_account,
    "COSMOS_ENDPOINT": lambda c: c.cosmosdb_endpoint,
    # Environment trigger
    "ENVIRONMENT": lambda _: "dev",
}

# Core auth env vars that are always needed but often referenced via Java
# constants (System.getenv(CONSTANT) instead of System.getenv("literal")),
# so discovery may miss them. Always include these in the mapping.
CORE_AUTH_VARS = {
    "AZURE_AD_TENANT_ID",
    "AZURE_AD_APP_RESOURCE_ID",
    "AZURE_TESTER_SERVICEPRINCIPAL_SECRET",
    "DATA_PARTITION_ID",
}


def log(msg: str) -> None:
    """Print diagnostic message to stderr."""
    print(msg, file=sys.stderr)


def mask_value(key: str, value: str) -> str:
    """Mask sensitive values for display."""
    if any(p in key.lower() for p in SECRET_PATTERNS):
        return "[resolved]"
    return value



# =============================================================================
# ENVIRONMENT RESOLUTION
# =============================================================================


@dataclass
class EnvConfig:
    """Resolved environment configuration from the running SPI Stack cluster."""

    osdu_endpoint: str
    tenant: str
    azure_tenant_id: str
    azure_client_id: str
    azure_token: str
    keyvault_uri: str = ""
    storage_account: str = ""
    cosmosdb_endpoint: str = ""


class SpiEnvironment:
    """Resolve SPI Stack environment from the live cluster via ``spi info``."""

    def __init__(self, endpoint: str | None = None):
        self.endpoint_override = endpoint

    def resolve(self) -> EnvConfig:
        """Query the running cluster for endpoints and credentials."""
        azure_token = self._get_azure_token()
        if self.endpoint_override:
            return self._resolve_manual(self.endpoint_override, azure_token)
        return self._resolve_from_cluster(azure_token)

    def _get_azure_token(self) -> str:
        """Get an access token from Azure CLI."""
        log("Getting Azure access token via 'az account get-access-token'...")
        try:
            result = subprocess.run(
                ["az", "account", "get-access-token", "--query", "accessToken", "-o", "tsv"],
                capture_output=True, text=True, timeout=15,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Azure CLI (az) not found. Install it and run 'az login'."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("'az account get-access-token' timed out.")

        if result.returncode != 0:
            raise RuntimeError(
                "Azure CLI not authenticated.\n"
                "  Run 'az login' to authenticate."
            )

        token = result.stdout.strip()
        if not token:
            raise RuntimeError("Azure CLI returned an empty access token.")
        return token

    def _resolve_from_cluster(self, azure_token: str) -> EnvConfig:
        """Run ``uv run spi info --json --show-secrets`` and parse output."""
        log("Querying cluster via 'uv run spi info --json --show-secrets'...")
        try:
            result = subprocess.run(
                ["uv", "run", "spi", "info", "--json", "--show-secrets"],
                capture_output=True, text=True, timeout=30,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "Cannot run 'uv run spi info'. Make sure you are in the "
                "spi-stack directory and uv is installed."
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("'uv run spi info --json' timed out after 30s.")

        if result.returncode != 0:
            raise RuntimeError(
                "Cannot connect to the SPI Stack cluster.\n"
                "  Make sure your kubeconfig is set and the cluster is running.\n"
                "  Alternatively, use --endpoint to specify the OSDU endpoint manually."
            )

        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            raise RuntimeError(
                f"Failed to parse 'spi info --json' output.\n"
                f"  stdout: {result.stdout[:200]}"
            )

        return self._parse_cluster_info(data, azure_token)

    def _parse_cluster_info(self, data: dict, azure_token: str) -> EnvConfig:
        """Extract EnvConfig from spi info JSON output."""
        endpoints = data.get("endpoints", [])
        config = data.get("config", {})

        # Find OSDU endpoint: prefer gateway
        osdu_endpoint = ""
        for ep in endpoints:
            if "Gateway" in ep.get("name", ""):
                osdu_endpoint = ep["url"]
                break
        if not osdu_endpoint:
            raise ValueError(
                "No gateway endpoint found. Is the SPI Stack deployed?\n"
                "  Run 'uv run spi status' to check deployment progress."
            )

        return EnvConfig(
            osdu_endpoint=osdu_endpoint.rstrip("/"),
            tenant=config.get("DATA_PARTITION", "osdu"),
            azure_tenant_id=config.get("AZURE_TENANT_ID", ""),
            azure_client_id=config.get("AAD_CLIENT_ID", ""),
            azure_token=azure_token,
            keyvault_uri=config.get("KEYVAULT_URI", ""),
            storage_account=config.get("STORAGE_ACCOUNT_NAME", ""),
            cosmosdb_endpoint=config.get("COSMOSDB_ENDPOINT", ""),
        )

    def _resolve_manual(self, endpoint: str, azure_token: str) -> EnvConfig:
        """Build config from a manually-specified endpoint."""
        log(f"Using manual endpoint: {endpoint}")

        # Try to get Azure config from the cluster ConfigMap
        azure_tenant_id = ""
        azure_client_id = ""
        try:
            result = subprocess.run(
                ["kubectl", "get", "configmap", "osdu-config", "-n", "osdu",
                 "-o", "jsonpath={.data}"],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                cm_data = json.loads(result.stdout)
                azure_tenant_id = cm_data.get("AZURE_TENANT_ID", "")
                azure_client_id = cm_data.get("AAD_CLIENT_ID", "")
        except (subprocess.TimeoutExpired, OSError, json.JSONDecodeError):
            pass

        if not azure_tenant_id:
            # Fall back to az CLI
            try:
                result = subprocess.run(
                    ["az", "account", "show", "--query", "tenantId", "-o", "tsv"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    azure_tenant_id = result.stdout.strip()
            except (subprocess.TimeoutExpired, OSError):
                pass

        return EnvConfig(
            osdu_endpoint=endpoint.rstrip("/"),
            tenant="osdu",
            azure_tenant_id=azure_tenant_id,
            azure_client_id=azure_client_id,
            azure_token=azure_token,
        )


# =============================================================================
# SERVICE TEST DISCOVERY
# =============================================================================


@dataclass
class TestInfo:
    """Discovered test module information."""

    pattern: str  # "A" or "B"
    test_module_dir: Path
    needs_core_build: bool
    core_module_dir: Path | None
    java_source_dirs: list[Path] = field(default_factory=list)


class ServiceTestDiscovery:
    """Find service repos and detect test patterns."""

    def __init__(self, workspace: Path):
        self.workspace = workspace

    def find_service(self, service_name: str) -> tuple[Path, TestInfo]:
        """Locate service root and discover test structure."""
        if not re.match(r"^[\w][\w.-]*$", service_name):
            raise ValueError(f"Invalid service name: '{service_name}'")

        service_root = self._find_service_root(service_name)
        test_info = self._detect_test_pattern(service_root, service_name)
        return service_root, test_info

    def find_service_with_pattern(
        self, service_name: str, force_pattern: str | None
    ) -> tuple[Path, TestInfo]:
        """Locate service and optionally force a test pattern."""
        service_root = self._find_service_root(service_name)
        if force_pattern:
            test_info = self._force_pattern(service_root, service_name, force_pattern)
        else:
            test_info = self._detect_test_pattern(service_root, service_name)
        return service_root, test_info

    def _find_service_root(self, service_name: str) -> Path:
        """Find the service repository root directory."""
        candidates = []

        if self.workspace.is_dir():
            base = self.workspace / service_name
            # Worktree layout
            candidates.append(base / "master")
            # Flat clone
            candidates.append(base)

        for candidate in candidates:
            if candidate.is_dir() and (candidate / "pom.xml").is_file():
                return candidate

        raise FileNotFoundError(
            f"Service '{service_name}' not found. Searched:\n"
            + "\n".join(f"  - {c}" for c in candidates)
        )

    def _detect_test_pattern(self, service_root: Path, service_name: str) -> TestInfo:
        """Auto-detect whether the service uses Pattern B or A.

        Pattern B (test-azure) is preferred for SPI Stack environments because
        it uses Azure SP credentials. Pattern A (acceptance-test) uses OIDC auth
        and is the fallback.
        """
        # Pattern B: testing/<service>-test-azure/ (preferred for SPI)
        testing_dir = service_root / "testing"
        if testing_dir.is_dir():
            for child in testing_dir.iterdir():
                if child.name.endswith("-test-azure") and (child / "pom.xml").is_file():
                    core_dir = self._find_core_module(testing_dir)
                    java_dirs = [child / "src"]
                    if core_dir:
                        java_dirs.insert(0, core_dir / "src")
                    return TestInfo(
                        pattern="B",
                        test_module_dir=child,
                        needs_core_build=core_dir is not None,
                        core_module_dir=core_dir,
                        java_source_dirs=java_dirs,
                    )

        # Pattern A: <service>-acceptance-test/ (fallback)
        for child in service_root.iterdir():
            if child.name.endswith("-acceptance-test") and (child / "pom.xml").is_file():
                return TestInfo(
                    pattern="A",
                    test_module_dir=child,
                    needs_core_build=False,
                    core_module_dir=None,
                    java_source_dirs=[child / "src"],
                )

        raise FileNotFoundError(
            f"No integration tests found for '{service_name}' in {service_root}.\n"
            f"Checked: testing/*-test-azure/ and *-acceptance-test/"
        )

    def _force_pattern(self, service_root: Path, service_name: str, pattern: str) -> TestInfo:
        """Force a specific test pattern."""
        if pattern == "B":
            testing_dir = service_root / "testing"
            for child in testing_dir.iterdir() if testing_dir.is_dir() else []:
                if child.name.endswith("-test-azure") and (child / "pom.xml").is_file():
                    core_dir = self._find_core_module(testing_dir)
                    java_dirs = [child / "src"]
                    if core_dir:
                        java_dirs.insert(0, core_dir / "src")
                    return TestInfo(
                        pattern="B",
                        test_module_dir=child,
                        needs_core_build=core_dir is not None,
                        core_module_dir=core_dir,
                        java_source_dirs=java_dirs,
                    )
            raise FileNotFoundError(f"Pattern B test module not found in {testing_dir}")
        else:
            for child in service_root.iterdir():
                if child.name.endswith("-acceptance-test") and (child / "pom.xml").is_file():
                    return TestInfo(
                        pattern="A",
                        test_module_dir=child,
                        needs_core_build=False,
                        core_module_dir=None,
                        java_source_dirs=[child / "src"],
                    )
            raise FileNotFoundError(f"Pattern A acceptance-test module not found in {service_root}")

    def _find_core_module(self, testing_dir: Path) -> Path | None:
        """Find a test-core module in the testing directory."""
        for child in testing_dir.iterdir():
            if child.name.endswith("-test-core") and (child / "pom.xml").is_file():
                return child
        return None


# =============================================================================
# CONFIG.JAVA PARSER
# =============================================================================

# Regex patterns for extracting env var references from Java source
_GETENV_RE = re.compile(r'System\.getenv\(\s*"([^"]+)"\s*\)')
_GETPROP_RE = re.compile(r'System\.getProperty\(\s*"([^"]+)"')


class ConfigJavaParser:
    """Extract required environment variable names from Java test source."""

    @staticmethod
    def discover_env_vars(source_dirs: list[Path]) -> set[str]:
        """Scan Java source files for System.getenv() and System.getProperty() calls."""
        env_vars: set[str] = set()
        for src_dir in source_dirs:
            if not src_dir.is_dir():
                continue
            for java_file in src_dir.rglob("*.java"):
                try:
                    content = java_file.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                env_vars.update(_GETENV_RE.findall(content))
                env_vars.update(_GETPROP_RE.findall(content))
        return env_vars


# =============================================================================
# ENV VAR MAPPER
# =============================================================================


class EnvVarMapper:
    """Map resolved cluster config to test-expected environment variables."""

    @staticmethod
    def build_mapping(env_config: EnvConfig, required_vars: set[str],
                      service_name: str = "") -> dict[str, str]:
        """Build env var dict for the variables the tests need.

        Args:
            env_config: Resolved environment configuration.
            required_vars: Env vars discovered from Java source.
            service_name: Service name (used for HOST_URL path resolution).
        """
        # Always include core auth vars — they're often referenced via Java
        # constants so discovery misses them
        all_vars = required_vars | CORE_AUTH_VARS
        mapped = {}
        unmapped = []

        for var_name in sorted(all_vars):
            rule = MAPPING_RULES.get(var_name)
            if rule is not None:
                mapped[var_name] = rule(env_config)
            else:
                unmapped.append(var_name)

        # Set HOST_URL with service-specific API path if applicable
        if "HOST_URL" in all_vars or "HOST_URL" in required_vars:
            api_path = SERVICE_API_PATHS.get(service_name, "/")
            mapped["HOST_URL"] = env_config.osdu_endpoint + api_path
            # Remove from unmapped since we handle it here
            unmapped = [v for v in unmapped if v != "HOST_URL"]

        if unmapped:
            log(f"Warning: {len(unmapped)} env var(s) not auto-mapped: {', '.join(unmapped)}")
            log("  These may need manual values or have defaults in the test code.")

        return mapped


# =============================================================================
# SSL TRUSTSTORE
# =============================================================================


class SslTruststore:
    """Create a Java truststore with SSL certificates for OSDU endpoints."""

    CACHE_DIR = Path.home() / ".osdu-acceptance-test"
    TRUSTSTORE_PATH = CACHE_DIR / "truststore.jks"
    TRUSTSTORE_PASSWORD = "changeit"
    MAX_AGE_SECONDS = 86400  # 24 hours

    @classmethod
    def ensure_truststore(cls, hostnames: list[str]) -> Path | None:
        """Create or reuse a cached truststore for multiple hosts.

        Downloads the full certificate chain from each hostname (needed for
        Let's Encrypt staging certs) and imports all certs into a single
        Java truststore.

        Args:
            hostnames: List of hostnames to trust (e.g., OSDU endpoint + Keycloak).

        Returns:
            Path to the truststore, or None on failure.
        """
        # Check cache
        if cls.TRUSTSTORE_PATH.is_file():
            age = time.time() - cls.TRUSTSTORE_PATH.stat().st_mtime
            if age < cls.MAX_AGE_SECONDS:
                log(f"Using cached truststore ({int(age)}s old): {cls.TRUSTSTORE_PATH}")
                return cls.TRUSTSTORE_PATH

        # Check tool availability
        if not shutil.which("openssl") or not shutil.which("keytool"):
            log("Warning: openssl or keytool not found — skipping SSL truststore setup.")
            log("  Tests may fail with PKIX path building errors.")
            log("  Install a JDK (provides keytool) and OpenSSL to fix this.")
            return None

        cls.CACHE_DIR.mkdir(parents=True, exist_ok=True)

        # Remove old truststore if it exists
        if cls.TRUSTSTORE_PATH.is_file():
            cls.TRUSTSTORE_PATH.unlink()

        imported = 0
        for hostname in hostnames:
            certs = cls._download_cert_chain(hostname)
            for idx, cert_pem in enumerate(certs):
                alias = f"{hostname.replace('.', '-')}-{idx}"
                cert_path = cls.CACHE_DIR / f"{alias}.pem"
                cert_path.write_text(cert_pem)
                if cls._import_cert(alias, cert_path):
                    imported += 1

        if imported == 0:
            log("Warning: No certificates imported into truststore.")
            return None

        log(f"Truststore created with {imported} cert(s) from {len(hostnames)} host(s): {cls.TRUSTSTORE_PATH}")
        return cls.TRUSTSTORE_PATH

    @classmethod
    def _download_cert_chain(cls, hostname: str) -> list[str]:
        """Download the full certificate chain from a hostname.

        Returns a list of PEM-encoded certificates (leaf + intermediates + root).
        This is critical for Let's Encrypt staging certs where the intermediate
        CA is not in the default Java truststore.
        """
        log(f"Downloading SSL certificate chain from {hostname}...")
        try:
            result = subprocess.run(
                ["openssl", "s_client", "-showcerts", "-servername", hostname,
                 "-connect", f"{hostname}:443"],
                input="",
                capture_output=True,
                text=True,
                timeout=15,
            )
            # Extract ALL PEM certificates from the chain
            certs = re.findall(
                r"(-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----)",
                result.stdout,
                re.DOTALL,
            )
            if not certs:
                log(f"  Warning: Could not extract certificates from {hostname}.")
                return []
            log(f"  Found {len(certs)} cert(s) in chain for {hostname}")
            return certs
        except (subprocess.TimeoutExpired, OSError) as e:
            log(f"  Warning: Failed to download certificate from {hostname}: {e}")
            return []

    @classmethod
    def _import_cert(cls, alias: str, cert_path: Path) -> bool:
        """Import a single PEM certificate into the truststore."""
        try:
            subprocess.run(
                ["keytool", "-importcert", "-noprompt",
                 "-alias", alias,
                 "-file", str(cert_path),
                 "-keystore", str(cls.TRUSTSTORE_PATH),
                 "-storepass", cls.TRUSTSTORE_PASSWORD],
                capture_output=True,
                text=True,
                timeout=15,
                check=True,
            )
            return True
        except (subprocess.CalledProcessError, OSError) as e:
            log(f"  Warning: Failed to import cert {alias}: {e}")
            return False


# =============================================================================
# TEST RUNNER
# =============================================================================


class TestRunner:
    """Build and execute Maven test commands."""

    @staticmethod
    def detect_git_skip(path: Path) -> str:
        """Detect worktree layout and return git-skip flag if needed."""
        git_path = path / ".git"
        if git_path.is_file():  # worktree: .git is a file, not a directory
            return "-Dmaven.gitcommitid.skip=true"
        return ""

    def run(
        self,
        test_info: TestInfo,
        env_mapping: dict[str, str],
        truststore_path: Path | None,
        service_root: Path,
    ) -> int:
        """Execute the full test flow. Returns exit code."""
        git_skip = self.detect_git_skip(service_root)

        # Auto-detect community Maven settings file
        settings_flag = ""
        for candidate in [
            service_root / ".mvn" / "community-maven.settings.xml",
            service_root / ".mvn" / "settings.xml",
        ]:
            if candidate.is_file():
                settings_flag = f"-s {candidate}"
                log(f"Using Maven settings: {candidate}")
                break

        # Build SSL truststore flags
        # Use JAVA_TOOL_OPTIONS so the truststore is inherited by ALL JVM
        # processes — including Surefire's forked test JVM (which ignores
        # MAVEN_OPTS and doesn't use ${argLine} unless the POM configures it).
        exec_env = {**os.environ, **env_mapping}
        if truststore_path:
            ssl_flags = (
                f"-Djavax.net.ssl.trustStore={truststore_path} "
                f"-Djavax.net.ssl.trustStorePassword={SslTruststore.TRUSTSTORE_PASSWORD}"
            )
            java_tool_opts = os.environ.get("JAVA_TOOL_OPTIONS", "")
            java_tool_opts = f"{java_tool_opts} {ssl_flags}".strip()
            exec_env["JAVA_TOOL_OPTIONS"] = java_tool_opts
            log(f"SSL truststore set via JAVA_TOOL_OPTIONS")

        # Phase 1: Build test-core if Pattern B
        if test_info.needs_core_build and test_info.core_module_dir:
            log(f"\n{'=' * 60}")
            log("BUILDING TEST-CORE")
            log(f"{'=' * 60}")
            core_cmd = f"mvn clean install -q {settings_flag} {git_skip}".strip()
            log(f"Command: {core_cmd}")
            log(f"Directory: {test_info.core_module_dir}")

            rc = self._exec(core_cmd, test_info.core_module_dir, exec_env)
            if rc != 0:
                log("\nTest-core build FAILED")
                return rc
            log("Test-core build succeeded")

        # Phase 2: Run tests
        log(f"\n{'=' * 60}")
        log("RUNNING INTEGRATION TESTS")
        log(f"{'=' * 60}")
        test_cmd = f"mvn clean test {settings_flag} {git_skip}".strip()
        log(f"Command: {test_cmd}")
        log(f"Directory: {test_info.test_module_dir}")

        rc = self._exec(test_cmd, test_info.test_module_dir, exec_env)
        return rc

    def _exec(self, command: str, work_dir: Path, env: dict[str, str]) -> int:
        """Execute a maven command via subprocess."""
        try:
            args = shlex.split(command, posix=os.name != "nt")
            if os.name == "nt" and args and args[0].lower() == "mvn":
                # On Windows, Maven is commonly provided as mvn.cmd/mvn.bat.
                # Resolving explicitly avoids WinError 2 when shell=False.
                args[0] = (
                    shutil.which("mvn.cmd")
                    or shutil.which("mvn.bat")
                    or shutil.which("mvn")
                    or "mvn.cmd"
                )
            result = subprocess.run(
                args,
                cwd=work_dir,
                env=env,
                timeout=300,
            )
            return result.returncode
        except subprocess.TimeoutExpired:
            log("Error: Test execution timed out after 5 minutes")
            return 1
        except OSError as e:
            log(f"Error executing command: {e}")
            return 1


# =============================================================================
# SUREFIRE PARSER
# =============================================================================


@dataclass
class TestResult:
    """A single test case result."""

    classname: str
    name: str
    time: float
    status: str  # PASS, FAIL, ERROR, SKIP
    message: str | None = None


class SurefireParser:
    """Parse Maven Surefire XML reports."""

    @staticmethod
    def parse(test_module_dir: Path) -> list[TestResult]:
        """Parse all surefire report XMLs in the test module."""
        reports_dir = test_module_dir / "target" / "surefire-reports"
        if not reports_dir.is_dir():
            return []

        results = []
        for xml_file in sorted(reports_dir.glob("TEST-*.xml")):
            try:
                tree = ElementTree.parse(str(xml_file))
            except Exception:
                continue

            root = tree.getroot()
            for tc in root.findall("testcase"):
                status = "PASS"
                message = None
                if tc.find("failure") is not None:
                    status = "FAIL"
                    elem = tc.find("failure")
                    message = elem.get("message", "") if elem is not None else ""
                elif tc.find("error") is not None:
                    status = "ERROR"
                    elem = tc.find("error")
                    message = elem.get("message", "") if elem is not None else ""
                elif tc.find("skipped") is not None:
                    status = "SKIP"

                results.append(TestResult(
                    classname=tc.get("classname", ""),
                    name=tc.get("name", ""),
                    time=float(tc.get("time", "0")),
                    status=status,
                    message=message[:200] if message else None,
                ))
        return results


# =============================================================================
# OUTPUT FORMATTING
# =============================================================================


def print_results(service_name: str, test_info: TestInfo, results: list[TestResult],
                  env_config: EnvConfig, exit_code: int) -> None:
    """Print structured test results to stdout."""
    passed = sum(1 for r in results if r.status == "PASS")
    failed = sum(1 for r in results if r.status == "FAIL")
    errors = sum(1 for r in results if r.status == "ERROR")
    skipped = sum(1 for r in results if r.status == "SKIP")
    total_time = sum(r.time for r in results)

    overall = "PASSED" if exit_code == 0 else "FAILED"

    print(f"\nIntegration Tests: {service_name}")
    print(f"Test Module: {test_info.test_module_dir.name} (Pattern {test_info.pattern})")
    print(f"Environment: {env_config.osdu_endpoint}")
    print(f"Duration: {total_time:.1f}s")
    print(f"Status: {overall}")
    print()

    if results:
        # Header
        print(f"  {'Test Class':<45} {'Result':<8} {'Time':>6}")
        print(f"  {'-' * 45} {'-' * 8} {'-' * 6}")
        for r in results:
            short_class = r.classname.rsplit(".", 1)[-1] if "." in r.classname else r.classname
            label = f"{short_class}#{r.name}"
            if len(label) > 45:
                label = label[:42] + "..."
            print(f"  {label:<45} {r.status:<8} {r.time:>5.1f}s")

    print()
    print(f"Tests: {passed} passed, {failed} failed, {errors} errors, {skipped} skipped")

    # Show failure details
    failures = [r for r in results if r.status in ("FAIL", "ERROR")]
    if failures:
        print("\nFailures:")
        for r in failures:
            short_class = r.classname.rsplit(".", 1)[-1]
            msg = r.message or "(no message)"
            print(f"  - {short_class}#{r.name}: {msg}")


def print_dry_run(service_name: str, test_info: TestInfo, env_config: EnvConfig,
                  env_mapping: dict[str, str], truststore_path: Path | None,
                  service_root: Path) -> None:
    """Print what would be executed without running."""
    git_skip = TestRunner.detect_git_skip(service_root)

    print(f"=== DRY RUN: Integration Test for {service_name} ===")
    print()
    print("Environment:")
    print(f"  Endpoint:  {env_config.osdu_endpoint}")
    print(f"  Auth:      Azure Entra ID")
    print(f"  Tenant:    {env_config.tenant}")
    print()
    print(f"Test Pattern: {test_info.pattern} ({test_info.test_module_dir.name})")
    print(f"  Test Module: {test_info.test_module_dir}")
    if test_info.core_module_dir:
        print(f"  Core Module: {test_info.core_module_dir}")
    print()
    print(f"Environment Variables ({len(env_mapping)} resolved):")
    for key in sorted(env_mapping):
        display = mask_value(key, env_mapping[key])
        print(f"  {key:<50} = {display}")

    unmapped_note = [v for v in env_mapping if MAPPING_RULES.get(v) is None]
    if unmapped_note:
        print(f"\n  Warning: unmapped vars: {', '.join(unmapped_note)}")

    print()
    print("SSL Truststore:")
    if truststore_path:
        print(f"  Path: {truststore_path}")
    else:
        print("  Not configured (openssl/keytool not available or --skip-ssl-setup)")

    print()
    print("Commands (would execute):")
    step = 1
    if test_info.needs_core_build and test_info.core_module_dir:
        cmd = f"mvn clean install -q {git_skip}".strip()
        print(f"  {step}. cd {test_info.core_module_dir} && {cmd}")
        step += 1
    test_cmd = f"mvn clean test {git_skip}".strip()
    print(f"  {step}. cd {test_info.test_module_dir} && {test_cmd}")


# =============================================================================
# MAIN
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="OSDU Java Integration Test Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --service partition
  %(prog)s --service partition --dry-run
  %(prog)s --service storage --endpoint https://my.osdu.host
  %(prog)s --service legal --pattern B
""",
    )
    parser.add_argument("--service", required=True, help="OSDU service name (e.g., partition)")
    parser.add_argument("--endpoint", help="OSDU endpoint URL (default: auto-detect from cluster)")
    parser.add_argument("--workspace", type=Path, help="OSDU workspace path (default: $OSDU_WORKSPACE)")
    parser.add_argument("--pattern", choices=["A", "B"], help="Force test pattern (default: auto-detect, B preferred)")
    parser.add_argument("--dry-run", action="store_true", help="Show config and commands without executing")
    args = parser.parse_args()

    try:
        # Phase 1: Resolve environment from cluster
        log("Resolving environment...")
        spi_env = SpiEnvironment(endpoint=args.endpoint)
        env_config = spi_env.resolve()
        log(f"  Endpoint: {env_config.osdu_endpoint}")
        log(f"  Tenant:   {env_config.tenant}")
        log(f"  Auth:     Azure Entra ID")

        # Phase 2: Find service and test module
        workspace = args.workspace or Path(os.environ.get("OSDU_WORKSPACE", str(Path.cwd().parent)))
        log(f"\nDiscovering tests for '{args.service}'...")
        discovery = ServiceTestDiscovery(workspace)
        service_root, test_info = discovery.find_service_with_pattern(args.service, args.pattern)
        log(f"  Pattern:     {test_info.pattern}")
        log(f"  Test module: {test_info.test_module_dir}")
        if test_info.core_module_dir:
            log(f"  Core module: {test_info.core_module_dir}")

        # Phase 3: Parse Config.java for required env vars
        log("\nDiscovering required env vars from Java source...")
        required_vars = ConfigJavaParser.discover_env_vars(test_info.java_source_dirs)
        log(f"  Found {len(required_vars)} env var references")

        # Phase 4: Map cluster values to test env vars
        env_mapping = EnvVarMapper.build_mapping(env_config, required_vars, args.service)
        log(f"  Mapped {len(env_mapping)} env vars")

        # Dry run: show what would happen and exit
        if args.dry_run:
            print_dry_run(args.service, test_info, env_config, env_mapping,
                          None, service_root)
            return 0

        # Phase 5: Execute tests (no SSL truststore needed for Azure)
        runner = TestRunner()
        exit_code = runner.run(test_info, env_mapping, None, service_root)

        # Phase 6: Parse and report results
        results = SurefireParser.parse(test_info.test_module_dir)
        print_results(args.service, test_info, results, env_config, exit_code)

        return exit_code

    except (FileNotFoundError, ValueError, RuntimeError) as e:
        log(f"\nError: {e}")
        return 1
    except KeyboardInterrupt:
        log("\nInterrupted")
        return 130


if __name__ == "__main__":
    sys.exit(main())
