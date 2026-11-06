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
"""The upload limit, for routes that read a body."""

from starlette.datastructures import Headers
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Content pushed by a connector is checked by its own route, as it also has to mark the message.
OWN_CHECK = "/internal/inbox-receive/"
# A ZIP is a little larger than what was sent in it, so its arrival is allowed this much more.
ARRIVAL_MARGIN_BYTES = 1024**2


class BodyTooLarge(Exception):
    pass


def over_limit(stated: str | None, limit: int) -> bool:
    return stated is not None and stated.isdigit() and int(stated) > limit


class BodyLimit:
    """Refuse a body over the limit, whether or not it states its length, and however a route reads it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"].startswith(OWN_CHECK):
            await self.app(scope, receive, send)
            return
        limit = scope["app"].state.services.settings.max_upload_bytes
        if over_limit(Headers(scope=scope).get("content-length"), limit):
            await self._refuse(send)
            return

        seen = 0
        exceeded = False
        started = False

        async def counting_receive() -> Message:
            nonlocal seen, exceeded
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > limit:
                    exceeded = True
                    raise BodyTooLarge
            return message

        async def guarded_send(message: Message) -> None:
            nonlocal started
            # A route can turn the failed read into an answer of its own. This one is the true answer.
            if exceeded and not started:
                return
            started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, guarded_send)
        except BodyTooLarge:
            pass
        if exceeded and not started:
            await self._refuse(send)

    @staticmethod
    async def _refuse(send: Send) -> None:
        body = b'{"detail":"The request is larger than this service accepts"}'
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())],
            }
        )
        await send({"type": "http.response.body", "body": body})
