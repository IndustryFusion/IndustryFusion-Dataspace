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

"""Removes a participant's bucket. Its adapter creates the bucket, and uses it."""

import asyncio

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException

from app.config import Settings

MISSING = {"404", "NoSuchBucket"}


class Buckets:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _client(self):
        return boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key,
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

    async def remove(self, bucket: str) -> bool:
        """Return whether there was such a bucket."""
        if not self.settings.s3_endpoint:
            return False
        try:
            return await asyncio.to_thread(self._remove, bucket)
        except (BotoCoreError, ClientError) as error:
            raise HTTPException(status_code=502, detail="Storage refused or did not answer") from error
