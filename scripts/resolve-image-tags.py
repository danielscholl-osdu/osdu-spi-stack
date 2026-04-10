#!/usr/bin/env python3
"""Resolve latest OSDU container image tags from the GitLab registry.

Queries the OSDU community GitLab container registry API for each service
and updates the HelmRelease YAML files under software/stacks/osdu/ with
the correct image repository and tag.

The GitLab cleanup policy prunes old image tags, so hardcoded SHAs go stale.
This script ensures we always deploy with a tag that exists in the registry.

Usage:
    python scripts/resolve-image-tags.py              # resolve and show
    python scripts/resolve-image-tags.py --update     # resolve and update YAML files

Environment variables:
    OSDU_IMAGE_BRANCH         - Branch suffix for image names (default: master)
"""

import json
import os
import re
import sys
import urllib.request
from pathlib import Path

GITLAB_HOST = "https://community.opengroup.org"
DEFAULT_BRANCH = "master"

# Service registry: maps service name to GitLab project ID, image base name,
# and the HelmRelease YAML file to update.
# Project IDs from community.opengroup.org GitLab.
IMAGE_REGISTRY = {
    # Core services (software/stacks/osdu/services/)
    "partition":      {"project_id": 221, "image": "partition",            "file": "services/partition.yaml"},
    "entitlements":   {"project_id": 400, "image": "entitlements",         "file": "services/entitlements.yaml"},
    "legal":          {"project_id": 74,  "image": "legal",               "file": "services/legal.yaml"},
    "schema":         {"project_id": 26,  "image": "schema-service",      "file": "services/schema.yaml"},
    "storage":        {"project_id": 44,  "image": "storage",             "file": "services/storage.yaml"},
    "search":         {"project_id": 19,  "image": "search-service",      "file": "services/search.yaml"},
    "indexer":        {"project_id": 25,  "image": "indexer-service",     "file": "services/indexer.yaml"},
    "indexer-queue":  {"project_id": 73,  "image": "indexer-queue",       "file": "services/indexer-queue.yaml"},
    "file":           {"project_id": 90,  "image": "file",                "file": "services/file.yaml"},
    "workflow":       {"project_id": 146, "image": "ingestion-workflow",  "file": "services/workflow.yaml"},
    # Reference services (software/stacks/osdu/services-reference/)
    "crs-conversion": {"project_id": 22,  "image": "crs-conversion-service", "file": "services-reference/crs-conversion.yaml"},
    "crs-catalog":    {"project_id": 21,  "image": "crs-catalog-service",    "file": "services-reference/crs-catalog.yaml"},
    "unit":           {"project_id": 5,   "image": "unit-service",           "file": "services-reference/unit.yaml"},
}


def gitlab_get(url: str):
    """GET a GitLab API URL, return parsed JSON."""
    req = urllib.request.Request(url, headers={"User-Agent": "spi-stack-resolver"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def resolve_image(svc_name: str, entry: dict, branch: str) -> dict | None:
    """Resolve the latest image tag for a service from the GitLab registry."""
    svc_branch = entry.get("branch", branch)
    image_name = f"{entry['image']}-{svc_branch}"
    project_id = entry["project_id"]

    # List registry repositories for this project
    repos = gitlab_get(f"{GITLAB_HOST}/api/v4/projects/{project_id}/registry/repositories")

    # Find the repository matching our image name
    repo = next((r for r in repos if r["name"] == image_name), None)
    if not repo:
        return None

    # Get the latest tag (first returned)
    tags = gitlab_get(
        f"{GITLAB_HOST}/api/v4/projects/{project_id}/registry/repositories/{repo['id']}/tags?per_page=1"
    )
    if not tags:
        return None

    tag = tags[0]["name"]
    repository = repo["location"].removesuffix(f":{tag}")

    return {"repository": repository, "tag": tag}


def update_yaml_file(filepath: Path, repository: str, tag: str) -> bool:
    """Update image repository and tag in a HelmRelease YAML file."""
    content = filepath.read_text()

    # Update repository line
    new_content = re.sub(
        r"(repository:\s*).+",
        rf"\g<1>{repository}",
        content,
        count=1,
    )
    # Update tag line
    new_content = re.sub(
        r'(tag:\s*)"[^"]+"',
        rf'\g<1>"{tag}"',
        new_content,
        count=1,
    )

    if new_content != content:
        filepath.write_text(new_content)
        return True
    return False


def main():
    update_mode = "--update" in sys.argv
    branch = os.environ.get("OSDU_IMAGE_BRANCH", DEFAULT_BRANCH)
    stacks_dir = Path(__file__).parent.parent / "software" / "stacks" / "osdu"

    print(f"\nResolving OSDU image tags (branch: {branch})...\n")

    resolved = {}
    errors = []

    for svc_name, entry in IMAGE_REGISTRY.items():
        try:
            result = resolve_image(svc_name, entry, branch)
            if result:
                resolved[svc_name] = result
                short_tag = result["tag"][:12]
                repo_suffix = result["repository"].split("/")[-1]
                print(f"  {svc_name:<20} -> {repo_suffix}:{short_tag}")
            else:
                print(f"  {svc_name:<20} -> NOT FOUND")
                errors.append(svc_name)
        except Exception as e:
            print(f"  {svc_name:<20} -> ERROR: {e}")
            errors.append(svc_name)

    print(f"\nResolved {len(resolved)}/{len(IMAGE_REGISTRY)} services")

    if update_mode and resolved:
        print("\nUpdating HelmRelease files...")
        for svc_name, result in resolved.items():
            entry = IMAGE_REGISTRY[svc_name]
            filepath = stacks_dir / entry["file"]
            if filepath.exists():
                changed = update_yaml_file(filepath, result["repository"], result["tag"])
                status = "updated" if changed else "unchanged"
                print(f"  {filepath.name:<25} {status}")
            else:
                print(f"  {filepath.name:<25} NOT FOUND")

    if errors:
        print(f"\nWARNING: {len(errors)} service(s) could not be resolved: {', '.join(errors)}")

    return 0 if resolved else 1


if __name__ == "__main__":
    sys.exit(main())
