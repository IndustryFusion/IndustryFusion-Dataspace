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
"""Crossing steps, failed notifications and forged steps. Message ids are fixed, so each order is always tested."""

import asyncio
import contextlib

import httpx
import pytest
from conftest import PEER, auth
from test_two_sided import FO, HOST, MB, Mesh, Side, assert_same, settle
from test_two_sided import two_sided as two_sided_on_postgres

from app.routes import outbox
from app.routes.outbox import OutgoingMessage, _accept

LOW, MIDDLE, HIGH, HIGHEST = (f"{digit * 8}-0000-4000-8000-000000000000" for digit in "1579")


def two_sided(scenario) -> None:
    if not HOST:
        pytest.skip("TEST_POSTGRES_HOST is not set")
    two_sided_on_postgres(scenario)


@contextlib.contextmanager
def message_ids(*ids: str):
    """The ids that the next accepted messages get, in order."""
    upcoming = iter(ids)
    real = outbox.uuid.uuid4
    outbox.uuid.uuid4 = lambda: next(upcoming)
    try:
        yield
    finally:
        outbox.uuid.uuid4 = real


def failing_notifications(side: Side, mesh: Mesh, times: int = 1, after_arrival: bool = False) -> None:
    """The next notifications from this side fail. With after_arrival, they arrive and only the answer is lost."""
    left = {"count": times}

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/transfer-request" and left["count"] > 0:
            left["count"] -= 1
            if after_arrival:
                await mesh.handle(request)
            raise httpx.ConnectError("the peer is restarting")
        return await mesh.handle(request)

    side.services.http._transport = httpx.MockTransport(handle)


def close(outcome: str = "resolved") -> dict:
    return {"conversation_id": "c", "performative": "close", "outcome": outcome}


async def opened(fo: Side, mb: Side) -> None:
    await fo.send(conversation_id="c")
    await settle(fo, mb)


def row_of(conversation: dict, message_id: str) -> dict:
    return next(item for item in conversation["messages"] if item["message_id"] == message_id)


async def applied_of(side: Side, message_id: str) -> bool:
    return row_of(await side.conversation("c"), message_id)["applied"]


def held_notifications(side: Side, mesh: Mesh) -> asyncio.Event:
    """This side's notifications wait until the returned event is set. Its connector step has been done by then."""
    release = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/internal/transfer-request":
            await release.wait()
        return await mesh.handle(request)

    side.services.http._transport = httpx.MockTransport(handle)
    return release


async def both_crossing(fo: Side, mb: Side, mesh: Mesh, fo_fields: dict, mb_fields: dict, ids: tuple[str, str]):
    """Each side accepts its step before either hears of the other's, with these message ids, and then both go."""
    fo_release, mb_release = held_notifications(fo, mesh), held_notifications(mb, mesh)
    with message_ids(*ids):
        first = await fo.send(**fo_fields)
        second = await mb.send(**mb_fields)
    fo_release.set()
    mb_release.set()
    await settle(fo, mb)
    return first, second


ORDERS = {"fo-lower": (LOW, HIGH), "mb-lower": (HIGH, LOW)}


@pytest.mark.parametrize("order", ORDERS)
def test_simultaneous_close_goes_to_the_lower_id(order):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        first, second = await both_crossing(fo, mb, mesh, close("resolved"), close("withdrawn"), ORDERS[order])
        assert (first["applied"], second["applied"]) == (True, True), "Neither had seen the other's when it sent"
        state, outcome = ("CLOSED_RESOLVED", "resolved") if order == "fo-lower" else ("CLOSED_WITHDRAWN", "withdrawn")
        await assert_same(fo, mb, "c", state, outcome)
        winner, loser = (first, second) if order == "fo-lower" else (second, first)
        for side in (fo, mb):
            assert await applied_of(side, winner["message_id"]) is True
            assert await applied_of(side, loser["message_id"]) is False
        assert (await fo.status(first["message_id"]))["status"] == "notified"
        assert (await mb.status(second["message_id"]))["status"] == "notified"

    two_sided(scenario)


@pytest.mark.parametrize("order", ORDERS)
def test_simultaneous_escalate_goes_to_the_lower_id(order):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        escalate = {"conversation_id": "c", "performative": "escalate"}
        await both_crossing(fo, mb, mesh, escalate, escalate, ORDERS[order])
        one, other = await fo.conversation("c"), await mb.conversation("c")
        assert (one["state"], other["state"]) == ("ESCALATING", "ESCALATING")
        assert one["escalated_by"] == other["escalated_by"] == (FO if order == "fo-lower" else MB)

    two_sided(scenario)


@pytest.mark.parametrize("performative", ["close", "escalate"])
@pytest.mark.parametrize("order", ORDERS)
def test_one_side_answered_before_the_other_step_arrives(order, performative):
    """The answer can reach a side long before the other's notification does, and they must still agree."""

    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        fields = close("resolved") if performative == "close" else {"conversation_id": "c", "performative": "escalate"}
        other = close("withdrawn") if performative == "close" else fields
        release = held_notifications(mb, mesh)
        with message_ids(*ORDERS[order]):
            first = await fo.send(**fields)
            second = await mb.send(**other)
        try:
            # The factory owner's notification goes through and is answered, while the machine builder's waits.
            for _ in range(200):
                if (await fo.status(first["message_id"]))["status"] == "notified":
                    break
                await asyncio.sleep(0.01)
            assert (await fo.status(first["message_id"]))["status"] == "notified"
            assert await applied_of(fo, first["message_id"]) is (order == "fo-lower")
        finally:
            release.set()
        await settle(fo, mb)
        one, two = await fo.conversation("c"), await mb.conversation("c")
        assert (one["state"], one["outcome"], one["escalated_by"]) == (
            two["state"],
            two["outcome"],
            two["escalated_by"],
        )
        winner = first if order == "fo-lower" else second
        assert await applied_of(fo, winner["message_id"]) is True
        assert await applied_of(mb, winner["message_id"]) is True

    two_sided(scenario)


@pytest.mark.parametrize("order", ORDERS)
def test_a_close_crossing_an_escalate_leaves_the_copies_as_documented(order):
    """Each refuses the other's. protocol.md gives this as its example."""

    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        escalate = {"conversation_id": "c", "performative": "escalate"}
        first, second = await both_crossing(fo, mb, mesh, close("resolved"), escalate, ORDERS[order])
        one, other = await fo.conversation("c"), await mb.conversation("c")
        assert (one["state"], one["outcome"], one["escalated_by"]) == ("CLOSED_RESOLVED", "resolved", None)
        assert (other["state"], other["outcome"], other["escalated_by"]) == ("ESCALATING", None, MB)
        assert (await fo.status(first["message_id"]))["status"] == "rejected"
        assert (await mb.status(second["message_id"]))["status"] == "rejected"
        assert "conversation_closed" in (await mb.status(second["message_id"]))["error_message"]

        # The escalator's own close: both are closed, and each keeps its own outcome.
        for release_side in (fo, mb):
            release_side.services.http._transport = httpx.MockTransport(mesh.handle)
        last = await mb.send(**close("failed"))
        await settle(fo, mb)
        one, other = await fo.conversation("c"), await mb.conversation("c")
        assert (one["state"], one["outcome"], one["escalated_by"]) == ("CLOSED_RESOLVED", "resolved", None)
        assert (other["state"], other["outcome"], other["escalated_by"]) == ("CLOSED_FAILED", "failed", MB)
        assert (await mb.status(last["message_id"]))["status"] == "notified"
        assert (await mb.status(last["message_id"]))["applied"] is True
        assert row_of(one, last["message_id"])["applied"] is False

    two_sided(scenario)


@pytest.mark.parametrize("order", ORDERS)
def test_a_close_and_reopen_crossing_a_close_leaves_the_copies_as_documented(order):
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        fo_release, mb_release = held_notifications(fo, mesh), held_notifications(mb, mesh)
        with message_ids(*ORDERS[order]):
            await fo.send(**close("resolved"))
            mb_close = await mb.send(**close("withdrawn"))
        await fo.send(conversation_id="c", performative="reopen")
        fo_release.set()
        mb_release.set()
        await settle(fo, mb)
        one, other = await fo.conversation("c"), await mb.conversation("c")
        assert (one["state"], one["outcome"]) == ("CLOSED_WITHDRAWN", "withdrawn")
        assert (other["state"], other["outcome"]) == ("OPEN", None)
        assert (await mb.status(mb_close["message_id"]))["status"] == "notified"

    two_sided(scenario)


def test_a_failed_step_stays_failed_and_a_later_notified_says_nothing_about_it():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        step = await fo.send(conversation_id="c", performative="escalate")
        await settle(fo, mb)
        assert (await fo.status(step["message_id"]))["status"] == "error"
        assert (await fo.conversation("c"))["state"] == "ESCALATING"
        assert (await mb.conversation("c"))["state"] == "OPEN"

        later = await fo.send(conversation_id="c")
        await settle(fo, mb)
        assert (await fo.status(later["message_id"]))["status"] == "notified"
        assert (await fo.status(step["message_id"]))["status"] == "error"
        assert (await mb.conversation("c"))["state"] == "OPEN"

    two_sided(scenario)


def test_repeating_a_step_whose_notification_failed_moves_the_receiver():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        first = await fo.send(**close("superseded"))
        await settle(fo, mb)
        assert (await fo.status(first["message_id"]))["status"] == "error"
        assert (await mb.conversation("c"))["state"] == "OPEN"

        again = await fo.send(**close("superseded"))
        assert again["applied"] is True
        await assert_same(fo, mb, "c", "CLOSED_SUPERSEDED", "superseded")
        assert (await fo.status(again["message_id"]))["status"] == "notified"
        assert await applied_of(mb, again["message_id"]) is True
        earlier = await fo.status(first["message_id"])
        assert (earlier["status"], earlier["applied"]) == ("error", True), "The earlier row doesn't change"

    two_sided(scenario)


def test_a_repeat_with_another_outcome_gets_the_ordinary_rules():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        await fo.send(**close("resolved"))
        await settle(fo, mb)
        other = await fo.send(**close("failed"))
        assert (other["applied"], other["conversation_state"]) == (False, "CLOSED_RESOLVED")
        await settle(fo, mb)
        assert (await mb.conversation("c"))["state"] == "OPEN"

    two_sided(scenario)


def test_a_repeat_accepted_while_the_first_is_in_progress_is_a_duplicate():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh)
        first = await fo.send(**close("resolved"))
        again = await fo.send(**close("resolved"))
        assert again["applied"] is False
        await settle(fo, mb)
        assert (await fo.status(first["message_id"]))["status"] == "error"
        assert (await mb.conversation("c"))["state"] == "OPEN"

    two_sided(scenario)


def test_a_repeat_after_only_the_answer_was_lost_changes_nothing_there():
    async def scenario(fo: Side, mb: Side, mesh: Mesh) -> None:
        await opened(fo, mb)
        failing_notifications(fo, mesh, after_arrival=True)
        first = await fo.send(**close("resolved"))
        await settle(fo, mb)
        assert (await fo.status(first["message_id"]))["status"] == "error"
        assert (await mb.conversation("c"))["state"] == "CLOSED_RESOLVED"
        again = await fo.send(**close("resolved"))
        await assert_same(fo, mb, "c", "CLOSED_RESOLVED", "resolved")
        assert await applied_of(mb, again["message_id"]) is False
        assert (await fo.status(first["message_id"]))["status"] == "error"

    two_sided(scenario)


def test_a_repeat_of_a_refused_step_goes_as_a_step_and_stays_rejected_if_refused_again(harness):
    harness.send(conversation_id="c1", payload={})
    harness.world.peer_status = 409
    close_it = {"performative": "close", "outcome": "resolved", "conversation_id": "c1", "payload": {}}
    first = harness.send(**close_it).json()
    again = harness.send(**close_it).json()
    assert again["applied"] is True
    assert harness.world.notifications[-1]["body"]["sender_applied"] is True
    for sent in (first, again):
        status = harness.client.get(f"/outbox/messages/{sent['message_id']}/status", headers=auth()).json()
        assert status["status"] == "rejected"


@contextlib.contextmanager
def own_close_in_progress(harness, message_id: str):
    """This side's close is accepted, and its delivery is held at the connector for as long as this lasts."""
    release = []

    async def hold(_asset: str) -> None:
        await release[0].wait()

    async def make() -> None:
        release.append(asyncio.Event())

    async def go() -> None:
        release[0].set()

    harness.run(make)
    harness.send(conversation_id="c1", payload={})
    harness.connector.on_offer = hold
    try:
        with message_ids(message_id):
            harness.client.post(
                "/outbox/messages",
                json={
                    "receiver_participant": PEER,
                    "conversation_id": "c1",
                    "performative": "close",
                    "outcome": "resolved",
                },
                headers=auth(),
            )
        yield
    finally:
        harness.run(go)
        harness.settle()


def test_a_step_still_on_its_way_keeps_the_lower_id(harness):
    with own_close_in_progress(harness, MIDDLE):
        higher = harness.notify(HIGH, conversation_id="c1", performative="close", outcome="failed")
        assert (higher.status_code, higher.json()["kept_step"]) == (202, MIDDLE)
        assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_RESOLVED"

        lower = harness.notify(LOW, conversation_id="c1", performative="close", outcome="withdrawn")
        assert (lower.status_code, lower.json()["kept_step"]) == (202, None)
        assert harness.client.get("/conversations/c1", headers=auth()).json()["state"] == "CLOSED_WITHDRAWN"


@pytest.mark.parametrize("message_id", ["0", "zzz"], ids=["lower-id", "higher-id"])
def test_a_peer_cannot_rewrite_an_answered_close(harness, message_id):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    answer = harness.notify(message_id, conversation_id="c1", performative="close", outcome="failed")
    assert answer.status_code == 202
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert (conversation["state"], conversation["outcome"]) == ("CLOSED_RESOLVED", "resolved")
    assert row_of(conversation, message_id)["applied"] is False
    own = next(
        item for item in conversation["messages"] if item["performative"] == "close" and item["direction"] == "sent"
    )
    assert own["applied"] is True


def test_a_peer_cannot_rewrite_an_answered_escalation(harness):
    harness.send(conversation_id="c1", performative="escalate", payload={})
    answer = harness.notify("0", conversation_id="c1", performative="escalate")
    assert answer.status_code == 409
    assert answer.json()["reason"] == "already_escalated"
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert conversation["escalated_by"] != PEER


def test_a_peers_own_earlier_step_cannot_be_rewritten_by_itself(harness):
    assert harness.notify("m1", conversation_id="c1").status_code == 202
    assert harness.notify("m2", conversation_id="c1", performative="close", outcome="resolved").status_code == 202
    answer = harness.notify("0", conversation_id="c1", performative="close", outcome="failed")
    assert answer.status_code == 202
    assert harness.client.get("/conversations/c1", headers=auth()).json()["outcome"] == "resolved"


def test_a_duplicate_stated_as_not_applied_does_not_settle(harness):
    with own_close_in_progress(harness, MIDDLE):
        answer = harness.notify(LOW, conversation_id="c1", performative="close", outcome="failed", sender_applied=False)
        assert answer.status_code == 202
        assert harness.client.get("/conversations/c1", headers=auth()).json()["outcome"] == "resolved"


@pytest.mark.parametrize(
    "answer",
    [
        {"kept_step": "zzzz"},
        {"kept_step": 5},
        {"kept_step": None},
        ["not", "an", "object"],
        {"conversation_state": "OPEN", "applied": False, "state_message_id": "0"},
    ],
    ids=["a-higher-id", "not-a-string", "none", "not-an-object", "a-copy"],
)
def test_an_answer_that_names_no_lower_step_changes_nothing(harness, answer):
    harness.world.peer_answer = answer
    response = harness.send(conversation_id="c1", performative="escalate", payload={})
    assert response.status_code == 202
    status = harness.client.get(f"/outbox/messages/{response.json()['message_id']}/status", headers=auth()).json()
    assert (status["status"], status["applied"], status["conversation_state"]) == ("notified", True, "ESCALATING")


def test_an_answer_can_not_set_a_state_or_touch_another_step(harness):
    harness.send(conversation_id="c1", performative="escalate", payload={})
    harness.world.peer_answer = {"kept_step": "0"}
    sent = harness.send(conversation_id="c1", payload={}).json()
    conversation = harness.client.get("/conversations/c1", headers=auth()).json()
    assert conversation["state"] == "ESCALATING"
    assert row_of(conversation, sent["message_id"])["applied"] is True


def test_stating_not_applied_does_not_get_past_the_rules(harness):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    answer = harness.notify("late", conversation_id="c1", performative="inform", sender_applied=False)
    assert answer.status_code == 409
    assert answer.json()["reason"] == "conversation_closed"


def test_stating_not_applied_needs_a_conversation(harness):
    answer = harness.notify("orphan", conversation_id="never-opened", sender_applied=False)
    assert answer.status_code == 409
    assert answer.json()["reason"] == "conversation_not_found"
    assert harness.client.get("/conversations/never-opened", headers=auth()).status_code == 404


def test_a_third_party_learns_nothing_from_a_refusal(harness):
    third = "urn:test:third"
    harness.world.registered[third] = {"participant_id": third, "adapter_url": "http://third.test"}
    harness.world.compatible = [PEER, third]
    harness.send(conversation_id="secret", payload={})
    harness.send(conversation_id="secret", performative="close", outcome="rejected", payload={})
    answer = harness.notify("probe", sender=third, conversation_id="secret")
    assert answer.status_code == 409
    body = answer.json()
    assert (body["reason"], body["conversation_state"], body["closed_at"]) == ("counterpart_mismatch", None, None)
    assert "CLOSED" not in answer.text


@pytest.mark.parametrize("registered", [True, False], ids=["incompatible", "unregistered"])
def test_receiver_applies_the_role_rules(harness, registered):
    other = "urn:test:same-role"
    if registered:
        harness.world.registered[other] = {"participant_id": other, "adapter_url": "http://other.test"}
    pushes = []

    async def push(destination: str) -> None:
        pushes.append(destination)

    harness.connector.on_push = push
    answer = harness.notify("role", sender=other, conversation_id="new-one")
    harness.settle()
    assert answer.status_code == 403
    assert pushes == []
    assert harness.client.get("/inbox/messages/role", headers=auth()).status_code == 404
    assert harness.client.get("/conversations/new-one", headers=auth()).status_code == 404


def test_registry_outage_at_the_receiver_is_unavailable(harness):
    harness.world.registry_up = False
    assert harness.notify("m1").status_code == 503


def test_role_refusal_is_visible_to_the_sender(harness):
    harness.world.peer_status = 403
    message_id = harness.send(payload={}).json()["message_id"]
    assert harness.client.get(f"/outbox/messages/{message_id}/status", headers=auth()).json()["status"] == "rejected"


def test_content_cannot_be_pushed_to_a_refused_message(harness):
    harness.send(conversation_id="c1", payload={})
    harness.send(conversation_id="c1", performative="close", outcome="resolved", payload={})
    assert harness.notify("refused", conversation_id="c1").status_code == 409
    assert harness.client.post("/internal/inbox-receive/refused", content=b'{"x": 1}').status_code == 404
    row = harness.client.get("/inbox/messages/refused", headers=auth()).json()
    assert (row["status"], row["applied"], row["payload"]) == ("error", False, None)


def test_a_failed_fetch_can_still_recover(harness):
    assert (
        harness.notify(
            "m1", conversation_id="c1", performative="close", outcome="failed", sender_applied=False
        ).status_code
        == 409
    )
    assert harness.notify("m0", conversation_id="c1").status_code == 202
    harness.connector.fetch_error = RuntimeError("no connection")
    assert harness.notify("m2", conversation_id="c1", sender_applied=False).status_code == 202
    harness.settle()
    assert harness.client.get("/inbox/messages/m2", headers=auth()).json()["status"] == "error"
    assert harness.client.post("/internal/inbox-receive/m2", content=b"{}").status_code == 200


def test_cancelling_accept_does_not_hold_up_the_queue_or_shutdown(harness):
    async def scenario() -> str:
        services = harness.services
        real_session = services.db.session

        class SlowCommit:
            def __init__(self) -> None:
                self.inner = real_session()

            async def __aenter__(self):
                session = await self.inner.__aenter__()
                commit = session.commit

                async def slow() -> None:
                    await asyncio.sleep(0.2)
                    await commit()

                session.commit = slow
                return session

            async def __aexit__(self, *details):
                return await self.inner.__aexit__(*details)

        services.db.session = SlowCommit
        body = OutgoingMessage(receiver_participant=PEER, conversation_id="cancelled", payload={})
        accepting = asyncio.create_task(_accept(services, body, "m", None, {"adapter_url": "http://peer.test"}, False))
        await asyncio.sleep(0.05)
        accepting.cancel()
        await asyncio.gather(accepting, return_exceptions=True)
        services.db.session = real_session
        await asyncio.wait_for(services.settle(), 3)
        return "settled"

    assert harness.run(scenario) == "settled"
    assert harness.world.notifications == []
