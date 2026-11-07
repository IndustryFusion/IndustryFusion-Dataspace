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

"""A participant's bucket and its S3 identity. See "Per-participant S3 identities" in the change's design."""

import asyncio
import json
import time

import boto3
import httpx
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import Settings

MISSING = {"404", "NoSuchBucket"}
IDENTITY_FILE = "/etc/iam/identity.json"
ADMINISTRATOR = "dataspace-management"
IDENTITY_READY_SECONDS = 30


class Buckets:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self, access_key: str | None = None, secret_key: str | None = None):
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=access_key or self.settings.s3_access_key,
            aws_secret_access_key=secret_key or self.settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4", connect_timeout=5),
        )

    def _remove(self, bucket: str) -> bool:
        client = self._client()
        try:
            client.head_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in MISSING:
                return False
            raise
        for page in client.get_paginator("list_objects_v2").paginate(Bucket=bucket):
            keys = [{"Key": entry["Key"]} for entry in page.get("Contents", [])]
            if keys:
                client.delete_objects(Bucket=bucket, Delete={"Objects": keys})
        client.delete_bucket(Bucket=bucket)
        return True

    def _create(self, bucket: str) -> None:
        client = self._client()
        try:
            client.create_bucket(Bucket=bucket)
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise

    async def create(self, bucket: str) -> None:
        try:
            await asyncio.to_thread(self._create, bucket)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage refused or did not answer") from error

    def _wait_usable(self, bucket: str, access_key: str, secret_key: str) -> None:
        client = self._client(access_key, secret_key)
        deadline = time.monotonic() + IDENTITY_READY_SECONDS
        while True:
            try:
                client.head_bucket(Bucket=bucket)
                return
            except ClientError:
                if time.monotonic() > deadline:
                    raise
            time.sleep(0.2)

    async def wait_usable(self, bucket: str, access_key: str, secret_key: str) -> None:
        """Storage takes up a new identity a moment after it is written, and an adapter needs it when it starts."""
        try:
            await asyncio.to_thread(self._wait_usable, bucket, access_key, secret_key)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage didn't take up the new identity") from error

    async def remove(self, bucket: str) -> bool:
        """Return whether there was such a bucket."""
        if not self.settings.s3_endpoint:
            return False
        try:
            return await asyncio.to_thread(self._remove, bucket)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage refused or did not answer") from error


class StorageIdentities:
    """The filer's list of S3 identities. Every entry this service didn't make stays. It has to be the only writer."""

    def __init__(self, settings: Settings, http: httpx.AsyncClient) -> None:
        self.settings = settings
        self.http = http
        self.lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.s3_filer_url)

    async def _read(self) -> dict:
        answer = await self.http.get(f"{self.settings.s3_filer_url}{IDENTITY_FILE}")
        if answer.status_code == 404:
            return {"identities": []}
        answer.raise_for_status()
        # A file with no entries reads as an empty one. Anything else unreadable must not be overwritten.
        return json.loads(answer.content) if answer.content.strip() else {"identities": []}

    async def _write(self, content: dict) -> None:
        answer = await self.http.put(
            # The S3 gateway only takes up a list the filer holds inline.
            f"{self.settings.s3_filer_url}{IDENTITY_FILE}?saveInside=true",
            content=json.dumps(content),
            headers={"Content-Type": "application/json"},
        )
        answer.raise_for_status()

    def _with_administrator(self, identities: list[dict]) -> list[dict]:
        """A list that doesn't hold this service's own key would lock it out."""
        keys = {credential.get("accessKey") for entry in identities for credential in entry.get("credentials", [])}
        if self.settings.s3_access_key in keys:
            return identities
        administrator = {
            "name": ADMINISTRATOR,
            "credentials": [{"accessKey": self.settings.s3_access_key, "secretKey": self.settings.s3_secret_key}],
            "actions": ["Admin", "Read", "Write", "List", "Tagging"],
        }
        return [administrator, *identities]

    async def _change(self, name: str, entry: dict | None) -> bool:
        try:
            async with self.lock:
                content = await self._read()
                identities = content.get("identities", [])
                kept = [item for item in identities if item.get("name") != name]
                existed = len(kept) != len(identities)
                await self._write(
                    {**content, "identities": self._with_administrator([*kept, *([entry] if entry else [])])}
                )
                return existed
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(status_code=502, detail="Storage's list of identities can't be changed") from error

    async def put(self, name: str, access_key: str, secret_key: str, bucket: str) -> bool:
        """Give this identity access to one bucket, and nothing else. Return whether it was there before."""
        entry = {
            "name": name,
            "credentials": [{"accessKey": access_key, "secretKey": secret_key}],
            "actions": [f"{action}:{bucket}" for action in ("Read", "Write", "List", "Tagging")],
        }
        return await self._change(name, entry)

    async def remove(self, name: str) -> bool:
        return await self._change(name, None)
