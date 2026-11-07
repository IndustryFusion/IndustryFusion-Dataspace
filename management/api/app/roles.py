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

"""Participant types, as the registry accepts them, and identifiers that are safe to provision."""

import re

ONTOLOGY = "https://industryfusion.github.io/contexts/ontology/v0/dataspace#"
FACTORY_OWNER, MACHINE_BUILDER = "factory_owner", "machine_builder"
MAX_ID_LENGTH = 200
# An id goes into a properties file, a role name and a client id, so it has to stay on one line.
UNSAFE_ID = re.compile(r"[\s\x00-\x1f\x7f]")


def bare_name(participant_type: str) -> str:
    return participant_type.removeprefix(ONTOLOGY).removeprefix("ds:")


def is_known(participant_type: str) -> bool:
    return bare_name(participant_type) in (FACTORY_OWNER, MACHINE_BUILDER)


def full_iri(participant_type: str) -> str:
    return ONTOLOGY + bare_name(participant_type)


def compatible(first: str, second: str) -> bool:
    return is_known(first) and is_known(second) and bare_name(first) != bare_name(second)


def id_is_safe(participant_id: str) -> bool:
    return bool(participant_id) and len(participant_id) <= MAX_ID_LENGTH and not UNSAFE_ID.search(participant_id)
