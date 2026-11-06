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

"""Participant lookups in the registry."""

import httpx
from fastapi import HTTPException


class Registry:
    def __init__(self, base_url: str, http: httpx.AsyncClient) -> None:
        self.base = base_url
        self.http = http

    async def _get(self, path: str) -> httpx.Response:
        try:
            response = await self.http.get(f"{self.base}{path}")
        except httpx.HTTPError as error:
            raise HTTPException(status_code=503, detail="The registry is unavailable") from error
        if response.status_code >= 500:
            raise HTTPException(status_code=503, detail="The registry is unavailable")
        return response

    async def receiver(self, own_id: str, receiver_id: str) -> dict:
        """Return the receiver's record, if it is registered and its role is compatible."""
        response = await self._get(f"/participants/{receiver_id}")
        if response.status_code == 404:
            raise HTTPException(status_code=404, detail=f"Receiver is not registered: {receiver_id}")
        record = response.json()
        compatible = await self._get(f"/participants/compatible/{own_id}")
        if compatible.status_code == 404:
            raise HTTPException(status_code=403, detail="This participant is not registered")
        if receiver_id not in {participant["participant_id"] for participant in compatible.json()}:
            raise HTTPException(status_code=403, detail="The receiver's role is not compatible")
        return record
