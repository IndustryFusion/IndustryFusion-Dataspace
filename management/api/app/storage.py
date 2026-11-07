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
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import Settings

MISSING = {"404", "NoSuchBucket"}
USER_MISSING = {"NoSuchEntity", "NoSuchEntityException"}
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
    """Participants' S3 identities, through the storage's IAM API. Each is limited to one bucket."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.lock = asyncio.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.settings.s3_iam_url)

    def _client(self):
        return boto3.client(
            "iam",
            endpoint_url=self.settings.s3_iam_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
            region_name="us-east-1",
            config=Config(connect_timeout=5),
        )

    @staticmethod
    def _keys_of(client, name: str) -> list[str]:
        try:
            return [key["AccessKeyId"] for key in client.list_access_keys(UserName=name)["AccessKeyMetadata"]]
        except ClientError as error:
            if error.response.get("Error", {}).get("Code") in USER_MISSING:
                return []
            raise

    def _ensure(self, name: str, bucket: str, held: tuple[str, str] | None) -> tuple[str, str, bool]:
        client = self._client()
        keys = self._keys_of(client, name)
        if held and held[0] in keys:
            return held[0], held[1], False
        if not keys:
            client.create_user(UserName=name)
        made = client.create_access_key(UserName=name)["AccessKey"]
        statement = {
            "Effect": "Allow",
            "Action": ["s3:*"],
            "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
        }
        document = json.dumps({"Version": "2012-10-17", "Statement": [statement]})
        client.put_user_policy(UserName=name, PolicyName="own-bucket", PolicyDocument=document)
        return made["AccessKeyId"], made["SecretAccessKey"], not keys

    def _remove(self, name: str) -> bool:
        client = self._client()
        if not self._keys_of(client, name):
            return False
        client.delete_user(UserName=name)
        return True

    async def ensure(self, name: str, bucket: str, held: tuple[str, str] | None) -> tuple[str, str, bool]:
        """Return its access key and secret, and whether this call made the identity. Keys it holds already are kept."""
        try:
            async with self.lock:
                return await asyncio.to_thread(self._ensure, name, bucket, held)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage's identities can't be changed") from error

    async def remove(self, name: str) -> bool:
        try:
            async with self.lock:
                return await asyncio.to_thread(self._remove, name)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage's identities can't be changed") from error
