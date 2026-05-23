# Security Policy

## Reporting a vulnerability

Please report security vulnerabilities **privately**, not through public
GitHub issues.

Use GitHub's [private security advisory](https://github.com/danielscholl-osdu/osdu-spi-stack/security/advisories/new)
form. We aim to acknowledge reports within 5 business days.

Include:
- A description of the vulnerability and its impact.
- Steps or a proof of concept to reproduce.
- Any suggested remediation, if applicable.

## Scope

This policy covers code in the `danielscholl-osdu/osdu-spi-stack` repository:
the `spi` Python CLI, the Bicep templates under `infra/`, and the Flux/Helm
manifests under `software/`.

Vulnerabilities in upstream OSDU services, Azure platform services, or
third-party Helm charts are out of scope here; please report those to the
respective upstream maintainers.
