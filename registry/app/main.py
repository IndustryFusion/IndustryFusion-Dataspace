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

"""Participant Registry: the directory of participants and who may talk to whom."""

import asyncio
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator

from app import roles
from app.config import Settings
from app.store import PostgresStore, Store

log = logging.getLogger("registry")

RETRY_SECONDS = 5


class Participant(BaseModel):
    participant_id: str
    participant_type: str
    adapter_url: str | None = None
    dsp_url: str | None = None
    hosted: bool = True
    externally_reachable: bool = False
    peer_notify_url: str | None = None

    @field_validator("participant_id")
    @classmethod
    def id_is_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("participant_id must not be blank")
        return value

    @field_validator("participant_type")
    @classmethod
    def type_is_known(cls, value: str) -> str:
        try:
            return roles.normalize(value)
        except roles.UnknownRole as error:
            raise ValueError(f"unknown participant type: {value}") from error


async def connect_with_retry(
    application: FastAPI,
    connect: Callable[[], Awaitable[Store]],
    retry_seconds: float = RETRY_SECONDS,
) -> None:
    """Keep trying until the database answers. The service stays up meanwhile."""
    while True:
        try:
            application.state.store = await connect()
            log.info("Connected to the database")
            return
        except Exception as error:  # any failure here means "try again"
            log.warning("Database not available, retrying in %s s: %s", retry_seconds, error)
            await asyncio.sleep(retry_seconds)


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    if getattr(application.state, "store", None) is not None:
        yield
        return
    settings = Settings()
    application.state.store = None
    task = asyncio.create_task(connect_with_retry(application, lambda: PostgresStore.connect(settings)))
    yield
    task.cancel()
    store = application.state.store
    if store is not None:
        await store.close()


app = FastAPI(title="Participant Registry", lifespan=lifespan)


@app.exception_handler(asyncpg.PostgresError)
@app.exception_handler(asyncpg.InterfaceError)
@app.exception_handler(OSError)
async def database_unavailable(_: Request, __: Exception) -> JSONResponse:
    """The database can go away after startup too. It answers the same as while waiting for it."""
    return JSONResponse(status_code=503, content={"detail": "The database is not available"})


def store_of(request: Request) -> Store:
    store = getattr(request.app.state, "store", None)
    if store is None:
        raise HTTPException(status_code=503, detail="The database is not available yet")
    return store


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/participants")
async def save_participant(participant: Participant, request: Request) -> dict:
    record = participant.model_dump()
    await store_of(request).save(record)
    return record


@app.get("/participants")
async def list_participants(request: Request, type: str | None = None) -> list[dict]:
    records = await store_of(request).all()
    if type is None:
        return records
    try:
        wanted = roles.normalize(type)
    except roles.UnknownRole as error:
        raise HTTPException(status_code=422, detail=f"Unknown participant type: {type}") from error
    return [record for record in records if record["participant_type"] == wanted]


# Declared before the single-participant route, as "compatible" would otherwise match it.
@app.get("/participants/compatible/{participant_id:path}")
async def compatible_participants(participant_id: str, request: Request) -> list[dict]:
    store = store_of(request)
    me = await store.get(participant_id)
    if me is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return [
        record
        for record in await store.all()
        if record["participant_id"] != participant_id
        and roles.may_communicate(me["participant_type"], record["participant_type"])
    ]


@app.get("/participants/{participant_id:path}")
async def get_participant(participant_id: str, request: Request) -> dict:
    record = await store_of(request).get(participant_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Participant not found")
    return record


@app.delete("/participants/{participant_id:path}", status_code=204)
async def delete_participant(participant_id: str, request: Request) -> Response:
    if not await store_of(request).delete(participant_id):
        raise HTTPException(status_code=404, detail="Participant not found")
    return Response(status_code=204)
