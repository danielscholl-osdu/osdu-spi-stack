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

"""Shared path constants."""

from pathlib import Path

# src/spi/paths.py -> three parents up is the repo root.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Bicep templates ship inside the wheel via hatchling force-include
# ("infra" -> "spi/infra"). Fall back to the repo's top-level infra/ when
# running from a source checkout (where the package dir has no infra/).
_PACKAGE_ROOT = Path(__file__).resolve().parent
INFRA_ROOT = _PACKAGE_ROOT / "infra"
if not INFRA_ROOT.exists():
    INFRA_ROOT = REPO_ROOT / "infra"
