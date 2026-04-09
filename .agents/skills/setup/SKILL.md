---
name: setup
description: >-
  Install and verify CLI tool dependencies for OSDU SPI Stack development. Checks
  spi-stack prerequisites (az, kubectl, flux, helm), installs uv and glab, and
  configures Azure CLI authentication. Use when a command is not found, when
  the user says "setup", "install dependencies", "check prerequisites", or before
  first use of the SPI CLI.
  Not for: building or testing services.
triggers:
  - "setup"
  - "install dependencies"
  - "check prerequisites"
  - "command not found"
  - "install tools"
  - "configure az"
compatibility: Requires Python 3.10+ and either uv or pip. Internet access required.
---

# OSDU SPI Stack Setup

Install and verify the tools needed for OSDU SPI Stack development.

## Part A: SPI Stack Prerequisites

The spi CLI has a built-in prerequisite checker. Use it first:

```bash
uv run spi check
```

### Required tools

The SPI Stack is Azure-only. These tools are required:

| Tool | Purpose |
|------|---------|
| az | Azure CLI for infrastructure provisioning |
| kubectl | Kubernetes cluster management |
| flux | Flux CD GitOps toolkit |
| helm | Helm chart management |

### Workflow

1. Run `uv run spi check`
2. Review output for any missing tools
3. Install missing tools using the commands below
4. Re-run `uv run spi check` to confirm all pass

### Installing missing tools

**az (Azure CLI)**
```bash
# macOS
brew install azure-cli

# Linux
curl -sL https://aka.ms/InstallAzureCLIDeb | sudo bash
```

**kubectl**
```bash
# macOS
brew install kubectl

# Linux
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl
```

**flux**
```bash
# macOS
brew install fluxcd/tap/flux

# Linux
curl -s https://fluxcd.io/install.sh | sudo bash
```

**helm**
```bash
# macOS
brew install helm

# Linux
curl https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
```

## Part B: Development Tools

### Step 1: Check what's already installed

```bash
uv --version 2>/dev/null && echo "uv: OK" || echo "uv: MISSING"
glab --version 2>/dev/null && echo "glab: OK" || echo "glab: MISSING"
```

### Step 2: Install missing tools

**Always ask the user before installing anything.**

#### uv (Python package manager)

```bash
# macOS / Linux
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### glab (GitLab CLI)

```bash
# macOS
brew install glab
```

After install, authenticate:
```bash
glab auth login --hostname community.opengroup.org
```

### Step 3: Azure Authentication

The SPI Stack requires an authenticated Azure CLI session:

```bash
# Login to Azure
az login

# Set subscription (if needed)
az account set --subscription <subscription-id>

# Verify
az account show --query '{name:name, id:id}' -o table
```

### Step 4: Verify everything

```bash
uv run spi check
az account show --query name -o tsv
```

### Authentication for OSDU GitLab

If working with OSDU service source code, authenticate via glab:

```bash
glab auth login --hostname community.opengroup.org
```

Or set a token directly:
```bash
export GITLAB_TOKEN=glpat-xxxxxxxxxxxxxxxxxxxx
```

Token needs at minimum `read_api` scope. For full access: `read_api`, `read_repository`.
