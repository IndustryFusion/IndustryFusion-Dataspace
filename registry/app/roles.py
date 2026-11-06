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

"""Role names and the rules for which roles may communicate. This is the one place they are defined."""

ONTOLOGY = "https://industryfusion.github.io/contexts/ontology/v0/dataspace#"
PREFIX = "ds:"

KNOWN_ROLES = {"factory_owner", "machine_builder"}

# Directed pairs: the first role may communicate with the second.
COMPATIBLE_ROLES = {
    ("factory_owner", "machine_builder"),
    ("machine_builder", "factory_owner"),
}


class UnknownRole(ValueError):
    pass


def bare_name(role: str) -> str:
    for start in (ONTOLOGY, PREFIX):
        if role.startswith(start):
            return role[len(start) :]
    return role


def normalize(role: str) -> str:
    """Return the full IRI for a bare name, a prefixed name or an IRI."""
    name = bare_name(role)
    if name not in KNOWN_ROLES:
        raise UnknownRole(role)
    return ONTOLOGY + name


def may_communicate(from_iri: str, to_iri: str) -> bool:
    return (bare_name(from_iri), bare_name(to_iri)) in COMPATIBLE_ROLES
