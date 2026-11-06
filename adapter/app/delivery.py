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

"""The work that happens after a route has answered: delivering and fetching messages."""

import asyncio
import logging
import time
from collections.abc import Coroutine
from dataclasses import dataclass, field
from urllib.parse import quote

import httpx
from sqlalchemy import update

from app.auth import OwnToken, TokenVerifier
from app.config import Settings
from app.connector import Connector, ConnectorError
from app.db import Database, InboxMessage, OutboxMessage, now
from app.registry import Registry
from app.storage import Storage

log = logging.getLogger("adapter")

# An inbox row in one of these statuses has nothing left to learn from the transfer flow.
SETTLED_INBOX = ("received", "acked", "error")


@dataclass
class Services:
    settings: Settings
    db: Database
    storage: Storage
    verifier: TokenVerifier
    own_token: OwnToken
    connector: Connector
    registry: Registry
    http: httpx.AsyncClient
    tasks: set[asyncio.Task] = field(default_factory=set)

    def spawn(self, work: Coroutine) -> None:
        task = asyncio.create_task(work)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    async def settle(self) -> None:
        """Wait for background work. Used at shutdown and in tests."""
        while self.tasks:
            await asyncio.gather(*list(self.tasks), return_exceptions=True)


async def set_outbox(services: Services, message_id: str, **values) -> None:
    async with services.db.session() as session:
        await session.execute(
            update(OutboxMessage)
            .where(OutboxMessage.message_id == message_id)
            .values(updated_at=now(), **values)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


async def set_inbox_in_transfer(services: Services, message_id: str, **values) -> None:
    """Update an inbox row from the transfer flow, unless it has already settled."""
    async with services.db.session() as session:
        await session.execute(
            update(InboxMessage)
            .where(InboxMessage.message_id == message_id, InboxMessage.status.not_in(SETTLED_INBOX))
            .values(updated_at=now(), **values)
            .execution_options(synchronize_session=False)
        )
        await session.commit()


def reason_for(error: Exception) -> str:
    """Expected failures explain themselves. Anything else needs its type to make sense."""
    expected = isinstance(error, ConnectorError | httpx.HTTPError | OSError)
    text = str(error) if expected else f"Unexpected {type(error).__name__}: {error}"
    return text[:1000]


async def fail_outbox(services: Services, message_id: str, error: Exception) -> None:
    log.warning("Delivery of %s failed: %s", message_id, reason_for(error))
    try:
        await set_outbox(services, message_id, status="error", error_message=reason_for(error))
    except Exception as second:  # most likely the database is down too, and the row can't be updated
        log.error("Could not record the failed delivery of %s: %s", message_id, second)


async def deliver(services: Services, message: dict, peer: dict) -> None:
    """Offer the content through the connector, then notify the receiver."""
    message_id = message["message_id"]
    settings = services.settings
    try:
        asset_id, provider_dsp = message_id, settings.edc_dsp_url
        if message["content_ref"]:
            asset_id = message["content_ref"]["asset_id"]
            provider_dsp = message["content_ref"]["dsp_url"]
        else:
            source = f"{settings.adapter_url}/internal/payload/{quote(message_id, safe='')}"
            await services.connector.offer(message_id, source)
        await set_outbox(services, message_id, status="registered")

        target = (peer.get("peer_notify_url") or peer.get("adapter_url") or "").rstrip("/")
        if not target:
            raise ConnectorError("The receiver has no address to notify")
        token = await services.own_token.get()
        response = await services.http.post(
            f"{target}/internal/transfer-request",
            json={
                **{key: value for key, value in message.items() if key != "content_ref"},
                "asset_id": asset_id,
                "provider_dsp_url": provider_dsp,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        if response.status_code < 300:
            await set_outbox(services, message_id, status="notified")
        elif response.status_code < 500:
            reason = f"The receiver refused it: {response.status_code} {response.text[:500]}"
            await set_outbox(services, message_id, status="rejected", error_message=reason)
        else:
            reason = f"The receiver gave {response.status_code}: {response.text[:500]}"
            await set_outbox(services, message_id, status="error", error_message=reason)
    except Exception as error:  # a background task has nobody to report to, so the row must say what happened
        await fail_outbox(services, message_id, error)


async def fetch(services: Services, message_id: str, sender: str, asset_id: str, provider_dsp: str) -> None:
    """Negotiate for the content, and have the provider push it to this adapter."""
    settings = services.settings
    connector = services.connector
    deadline = time.monotonic() + settings.transfer_budget_seconds
    try:
        await set_inbox_in_transfer(services, message_id, status="negotiating")
        offer = await connector.find_offer(asset_id, sender, provider_dsp)
        negotiation = await connector.negotiate(offer, asset_id, sender, provider_dsp)
        agreement = await connector.wait_for_agreement(negotiation, deadline)
        await set_inbox_in_transfer(services, message_id, status="negotiated")
        await set_inbox_in_transfer(services, message_id, status="transferring")
        destination = f"{settings.adapter_url}/internal/inbox-receive/{quote(message_id, safe='')}"
        transfer = await connector.push(agreement, provider_dsp, destination)
        await connector.wait_for_transfer(transfer, deadline)
    except Exception as error:  # a background task has nobody to report to, so the row must say what happened
        log.warning("Fetching %s failed: %s", message_id, reason_for(error))
        try:
            await set_inbox_in_transfer(services, message_id, status="error", error_message=reason_for(error))
        except Exception as second:  # most likely the database is down too, and the row can't be updated
            log.error("Could not record the failed fetch of %s: %s", message_id, second)


async def note_transfer(services: Services, message_id: str) -> None:
    """Record the provider's transfer id. It is for information, so failing to get it changes nothing."""
    try:
        transfer_id = await services.connector.transfer_for_asset(message_id)
        if transfer_id:
            await set_outbox(services, message_id, edc_transfer_id=transfer_id)
    except Exception as error:
        log.warning("Could not read the transfer id of %s: %s", message_id, error)
