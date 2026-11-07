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

"""Company details from the IFRIC registry. Nothing here may get in the way of a read, so a failure gives no details."""

import asyncio
import logging
import time
from collections.abc import Callable

import httpx

from app.config import Settings

log = logging.getLogger("management.ifric")

CALL_SECONDS = 5
# However slowly the other side answers. A timeout per call only limits the wait between its pieces.
FETCH_SECONDS = 10
# How long a read waits on a fetch. After this it goes on with what is known, and the fetch finishes for later reads.
READ_WAIT_SECONDS = 1
SECONDS_AFTER_A_FAILURE = 30
# A company's field, and the name it has on a participant's record.
FIELDS = {
    "company_name": "company_name",
    "company_category": "company_category",
    "company_city": "city",
    "company_country": "country",
}


class CompanyDirectory:
    def __init__(
        self, settings: Settings, http: httpx.AsyncClient, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.settings = settings
        self.http = http
        self.clock = clock
        self.fetching: asyncio.Task | None = None
        self.companies: dict[str, dict] = {}
        self.good_until = 0.0

    @property
    def configured(self) -> bool:
        wanted = self.settings
        return bool(wanted.ifric_backend_url and wanted.ifric_reader_client_id and wanted.ifric_reader_client_secret)

    async def _token(self) -> str:
        answer = await self.http.post(
            f"{self.settings.issuer}/protocol/openid-connect/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.settings.ifric_reader_client_id,
                "client_secret": self.settings.ifric_reader_client_secret,
            },
            timeout=CALL_SECONDS,
        )
        answer.raise_for_status()
        return answer.json()["access_token"]

    async def _fetch(self) -> dict[str, dict]:
        answer = await self.http.get(
            f"{self.settings.ifric_backend_url}/company/get-all-companies",
            headers={"Authorization": f"Bearer {await self._token()}"},
            timeout=CALL_SECONDS,
        )
        answer.raise_for_status()
        found = {}
        for company in answer.json():
            if isinstance(company, dict) and isinstance(company.get("company_ifric_id"), str):
                shown = FIELDS.items()
                details = {name: company[source] for source, name in shown if isinstance(company.get(source), str)}
                found[company["company_ifric_id"]] = details
        return found

    async def _refresh(self) -> None:
        cache_seconds = self.settings.ifric_lookup_cache_seconds
        try:
            async with asyncio.timeout(FETCH_SECONDS):
                self.companies = await self._fetch()
            self.good_until = self.clock() + cache_seconds
        except (httpx.HTTPError, httpx.InvalidURL, TimeoutError, ValueError, KeyError, TypeError) as error:
            # The error's type is enough: its text can hold addresses.
            log.warning("Company details are unavailable: %s", type(error).__name__)
            self.companies = {}
            self.good_until = self.clock() + min(cache_seconds, SECONDS_AFTER_A_FAILURE)

    async def _lookup(self) -> dict[str, dict]:
        if not self.configured:
            return {}
        if self.clock() >= self.good_until and (self.fetching is None or self.fetching.done()):
            self.fetching = asyncio.create_task(self._refresh())
        if self.fetching is not None and not self.fetching.done():
            await asyncio.wait({self.fetching}, timeout=READ_WAIT_SECONDS)
        return self.companies

    async def add_details(self, records: list[dict]) -> list[dict]:
        companies = await self._lookup()
        return [{**record, **companies.get(record.get("participant_id"), {})} for record in records]
