"""Smoke tests that every Bicep template in infra/ compiles cleanly.

Guards against schema drift that would only surface at deploy time. Skipped
when the Azure CLI is not installed (e.g., contributor laptops without az).
"""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
INFRA_DIR = REPO_ROOT / "infra"


def _bicep_files():
    return sorted(INFRA_DIR.rglob("*.bicep"))


@pytest.mark.skipif(shutil.which("az") is None, reason="Azure CLI not installed")
@pytest.mark.parametrize(
    "bicep_file",
    _bicep_files(),
    ids=lambda p: str(p.relative_to(REPO_ROOT)),
)
def test_bicep_compiles(bicep_file: Path):
    result = subprocess.run(
        ["az", "bicep", "build", "--file", str(bicep_file), "--stdout"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"bicep build failed for {bicep_file.relative_to(REPO_ROOT)}:\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )


@pytest.mark.skipif(shutil.which("az") is None, reason="Azure CLI not installed")
def test_bicepparam_files_compile():
    """Each .bicepparam file must resolve against its referenced template."""
    param_files = sorted((INFRA_DIR / "params").glob("*.bicepparam"))
    assert param_files, "expected at least one .bicepparam in infra/params/"
    for pf in param_files:
        result = subprocess.run(
            ["az", "bicep", "build-params", "--file", str(pf), "--stdout"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"bicep build-params failed for {pf.relative_to(REPO_ROOT)}:\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
