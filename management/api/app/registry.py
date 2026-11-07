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

"""The participant registry, read and written for administrators."""

from urllib.parse import quote

import httpx
from fastapi import HTTPException


class Registry:
    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self.http = http
        self.base = base_url

    async def _call(self, method: str, path: str, **options) -> httpx.Response:
        try:
            answer = await self.http.request(method, f"{self.base}{path}", **options)
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="The registry is unavailable") from error
        if answer.status_code >= 500:
            raise HTTPException(status_code=503, detail="The registry is unavailable")
        return answer

    @staticmethod
    def _path(participant_id: str) -> str:
        return quote(participant_id, safe=":")

    async def all(self) -> list[dict]:
        return (await self._call("GET", "/participants")).json()

    async def get(self, participant_id: str) -> dict | None:
        answer = await self._call("GET", f"/participants/{self._path(participant_id)}")
        return None if answer.status_code == 404 else answer.json()

    async def compatible(self, participant_id: str) -> list[dict] | None:
        answer = await self._call("GET", f"/participants/compatible/{self._path(participant_id)}")
        return None if answer.status_code == 404 else answer.json()

    async def save(self, record: dict) -> dict:
        answer = await self._call("POST", "/participants", json=record)
        if answer.status_code != 200:
            raise HTTPException(status_code=502, detail=f"The registry answered {answer.status_code} to a new entry")
        return answer.json()

    async def delete(self, participant_id: str) -> bool:
        """Return whether there was such an entry. Anything else the registry answers means it is still there."""
        answer = await self._call("DELETE", f"/participants/{self._path(participant_id)}")
        if answer.status_code == 404:
            return False
        if answer.status_code >= 300:
            raise HTTPException(status_code=502, detail=f"The registry answered {answer.status_code} to a removal")
        return True
