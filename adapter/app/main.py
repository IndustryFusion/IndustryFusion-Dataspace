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

"""Dataspace Adapter: the protocol, and all access to the connector and storage."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError

from app.auth import OwnToken, TokenVerifier
from app.config import Settings
from app.connector import Connector
from app.db import Database
from app.delivery import Services
from app.limits import BodyLimit
from app.registry import Registry
from app.retention import retention_loop, schema_loop
from app.routes import capabilities, capabilities_internal, conversations, inbox, internal, outbox
from app.storage import S3Storage


def build_services(settings: Settings) -> Services:
    client = httpx.AsyncClient(timeout=30)
    return Services(
        settings=settings,
        db=Database(settings.database_url),
        storage=S3Storage(settings),
        verifier=TokenVerifier(settings, client),
        own_token=OwnToken(settings, client),
        connector=Connector(settings.edc_management_url, settings.edc_api_key, client),
        registry=Registry(settings.registry_url, client),
        http=client,
    )


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        if services is not None:
            application.state.services = services
            yield
            return
        built = build_services(Settings())
        application.state.services = built
        loops = [asyncio.create_task(schema_loop(built)), asyncio.create_task(retention_loop(built))]
        yield
        for loop in loops:
            loop.cancel()
        await built.settle()
        await built.http.aclose()
        await built.db.close()

    application = FastAPI(title="Dataspace Adapter", lifespan=lifespan)
    application.add_middleware(BodyLimit)

    @application.exception_handler(OperationalError)
    @application.exception_handler(DBAPIError)
    @application.exception_handler(OSError)
    @application.exception_handler(BotoCoreError)
    @application.exception_handler(ClientError)
    async def unavailable(_: Request, __: Exception) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "A dependency is unavailable"})

    @application.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    application.include_router(outbox.router)
    application.include_router(inbox.router)
    application.include_router(conversations.router)
    application.include_router(capabilities.router)
    application.include_router(capabilities_internal.router)
    application.include_router(internal.router)
    return application


app = create_app()
