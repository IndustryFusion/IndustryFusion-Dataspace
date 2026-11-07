#
# Copyright (c) 2026 IndustryFusion Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#


import pathlib
import re


def test_server_keeps_idle_connections_longer_than_the_connectors_client():
    """A connector pushes through here, and a shorter limit makes its push fail now and then."""
    dockerfile = (pathlib.Path(__file__).parent.parent / "Dockerfile").read_text()
    seconds = int(re.search(r'"--timeout-keep-alive", "(\d+)"', dockerfile).group(1))
    assert seconds > 300
