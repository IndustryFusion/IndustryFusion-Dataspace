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
"""Bundling uploaded files into one ZIP."""

import os
import shutil
import time
import zipfile
from typing import BinaryIO

COPY_CHUNK_BYTES = 1024**2
LONGEST_NAME = 200


def safe_name(raw: str, position: int, taken: set[str]) -> str:
    """A name that stays inside the folder it is unpacked to, and replaces no other file there."""
    base = raw.replace("\\", "/").rsplit("/", 1)[-1]
    base = "".join(character for character in base if character.isprintable()).strip()
    if base in {"", ".", ".."}:
        base = f"file-{position}"
    stem, suffix = os.path.splitext(base)
    stem, suffix = stem[: LONGEST_NAME - len(suffix[:20])], suffix[:20]
    candidate = stem + suffix
    number = 2
    # Some systems don't tell upper and lower case apart when unpacking.
    while candidate.lower() in taken:
        candidate = f"{stem}-{number}{suffix}"
        number += 1
    taken.add(candidate.lower())
    return candidate


def write_bundle(files: list[tuple[str, BinaryIO]], path: str) -> None:
    """Write the files to a ZIP at path, without compressing them. This blocks, so run it in a thread."""
    taken: set[str] = set()
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as archive:
        for position, (name, content) in enumerate(files, start=1):
            entry = zipfile.ZipInfo(safe_name(name, position, taken), date_time=time.gmtime()[:6])
            content.seek(0)
            with archive.open(entry, "w", force_zip64=True) as target:
                shutil.copyfileobj(content, target, COPY_CHUNK_BYTES)
