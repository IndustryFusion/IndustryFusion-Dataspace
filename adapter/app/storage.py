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

"""Message content, kept in S3-compatible object storage."""

import asyncio
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.config import Settings


class Storage(Protocol):
    async def ensure_ready(self) -> None: ...

    async def put(self, key: str, content: bytes) -> str: ...

    async def get(self, ref: str) -> bytes | None: ...

    async def delete(self, ref: str) -> None: ...


class S3Storage:
    def __init__(self, settings: Settings) -> None:
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
        )

    def _key(self, ref: str) -> str:
        return ref.split("/", 3)[3]

    async def ensure_ready(self) -> None:
        def create() -> None:
            try:
                self.client.head_bucket(Bucket=self.bucket)
            except ClientError:
                self.client.create_bucket(Bucket=self.bucket)

        await asyncio.to_thread(create)

    async def put(self, key: str, content: bytes) -> str:
        await asyncio.to_thread(self.client.put_object, Bucket=self.bucket, Key=key, Body=content)
        return f"s3://{self.bucket}/{key}"

    async def get(self, ref: str) -> bytes | None:
        def read() -> bytes | None:
            try:
                return self.client.get_object(Bucket=self.bucket, Key=self._key(ref))["Body"].read()
            except ClientError as error:
                if error.response["Error"]["Code"] in {"NoSuchKey", "404"}:
                    return None
                raise

        return await asyncio.to_thread(read)

    async def delete(self, ref: str) -> None:
        await asyncio.to_thread(self.client.delete_object, Bucket=self.bucket, Key=self._key(ref))


class MemoryStorage:
    """Used by tests."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def ensure_ready(self) -> None:
        return None

    async def put(self, key: str, content: bytes) -> str:
        ref = f"s3://test/{key}"
        self.objects[ref] = content
        return ref

    async def get(self, ref: str) -> bytes | None:
        return self.objects.get(ref)

    async def delete(self, ref: str) -> None:
        self.objects.pop(ref, None)
