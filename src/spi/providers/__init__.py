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

"""Provider dispatch (Azure-only for SPI Stack)."""

from ..config import Config
from ..checks import get_tools_for_provider

from .azure import deploy_azure, cleanup_azure

DEPLOY_FN = deploy_azure
CLEANUP_FN = cleanup_azure
PREREQ_TOOLS = get_tools_for_provider()
